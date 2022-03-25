#!/usr/bin/env python3
#
# Copyright (C) 2019 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Creates a tarball suitable for use as a Rust prebuilt for Android."""

import argparse
import os
import os.path
from pathlib import Path
import shutil
import source_manager
import subprocess
import sys

import build_platform
import config
from paths import *
from utils import ResolvedPath, run_and_exit_on_failure, run_quiet, run_quiet_and_exit_on_failure


STDLIB_SOURCES = [
        "library/alloc",
        "library/backtrace",
        "library/core",
        "library/panic_abort",
        "library/panic_unwind",
        "library/portable-simd",
        "library/proc_macro",
        "library/profiler_builtins",
        "library/std",
        "library/stdarch",
        "library/test",
        "library/unwind",
        "vendor/backtrace",
        "vendor/cfg-if",
        "vendor/compiler_builtins",
        "vendor/getopts",
        "vendor/hashbrown",
        "vendor/libc",
        "vendor/rustc-demangle",
        "vendor/unicode-width",
]

LLVM_BUILD_PATHS_OF_INTEREST: list[str] = [
    "build.ninja",
    "cmake",
    "CMakeCache.txt",
    "CMakeFiles",
    "cmake_install.cmake",
    "compile_commands.json",
    "CPackConfig.cmake",
    "CPackSourceConfig.cmake",
    "install_manifest.txt",
    "llvm.spec"
]

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    """Parses arguments and returns the parsed structure."""
    parser = argparse.ArgumentParser("Build the Rust Toolchain")
    parser.add_argument(
        "--build-name", "-b", default="dev",
        help="Release name for the dist result")
    parser.add_argument(
        "--lto", "-l", default="none", choices=["none", "thin", "full"],
        help="Type of LTO to perform. Valid LTO types: none, thin, full")
    parser.add_argument(
        "--no-patch-abort",
        help="Don't abort on patch failure. Useful for local development.")

    pgo_group = parser.add_mutually_exclusive_group()
    pgo_group.add_argument(
        "--profile-generate", type=ResolvedPath, nargs="?", const=OUT_PATH_PROFILES,
        help="Instrument the compiler and store profiles in the specified directory")
    pgo_group.add_argument(
        "--profile-use", type=ResolvedPath, nargs="?", const=OUT_PATH_PROFILES,
        help="Use the rust.profdata and llvm.profdata files in the provided "
             "directory to optimize the compiler")

    parser.add_argument(
        "--cs-profile-generate", type=ResolvedPath, nargs="?", const=OUT_PATH_PROFILES,
        help="Instrument the LLVM libraries to generate context-sensitive profiles")

    args = parser.parse_args()

    if build_platform.is_darwin() and (args.profile_generate != None or args.profile_use != None):
        sys.exit("PGO is not supported on the Darwin platform")

    return args


def main() -> None:
    """Runs the configure-build-fixup-dist pipeline."""
    args = parse_args()

    # Add some output padding to make the messages easier to read
    print()

    #
    # Initialize directories
    #

    OUT_PATH.mkdir(exist_ok=True)
    OUT_PATH_PACKAGE.mkdir(exist_ok=True)
    OUT_PATH_WRAPPERS.mkdir(exist_ok=True)

    DIST_PATH.mkdir(exist_ok=True)

    #
    # Setup source files
    #

    source_manager.setup_files(
      RUST_SOURCE_PATH, OUT_PATH_RUST_SOURCE, PATCHES_PATH,
      no_patch_abort=args.no_patch_abort)

    #
    # Configure Rust
    #

    env = dict(os.environ)
    config.configure(args, env)

    # Trigger bootstrap to trigger vendoring
    #
    # Call is not checked because this is *expected* to fail - there isn't a
    # user facing way to directly trigger the bootstrap, so we give it a
    # no-op to perform that will require it to write out the cargo config.
    run_quiet([PYTHON_PATH, OUT_PATH_RUST_SOURCE / "x.py", "--help"], cwd=OUT_PATH_RUST_SOURCE)

    # Offline fetch to regenerate lockfile
    #
    # Because some patches may have touched vendored source we will rebuild
    # Cargo.lock
    run_and_exit_on_failure(
        [CARGO_PATH, "fetch", "--offline"],
        "Failed to rebuilt Cargo.lock via cargo-fetch operation",
        cwd=OUT_PATH_RUST_SOURCE, env=env)

    #
    # Build
    #

    # We only need to perform stage 3 of the bootstrap process when we are
    # collecting profile data.
    bootstrap_stage = "3" if args.profile_generate or args.cs_profile_generate else "2"

    result = subprocess.run(
        [PYTHON_PATH, OUT_PATH_RUST_SOURCE / "x.py", "--stage", bootstrap_stage, "install"],
        cwd=OUT_PATH_RUST_SOURCE, env=env)

    if result.returncode != 0:
        print(f"Build stage failed with error {result.returncode}")
        tarball_path = DIST_PATH / "llvm-build-config.tar.gz"
        run_quiet_and_exit_on_failure(
            ["tar", "czf", tarball_path.as_posix()] + LLVM_BUILD_PATHS_OF_INTEREST,
            "Could not generate logs/artifacts archive upon build failure",
            cwd=LLVM_BUILD_PATH)
        sys.exit(result.returncode)

    # Install sources
    if build_platform.is_linux():
        shutil.rmtree(OUT_PATH_STDLIB_SRCS, ignore_errors=True)
        for stdlib in STDLIB_SOURCES:
            shutil.copytree(OUT_PATH_RUST_SOURCE / stdlib, OUT_PATH_STDLIB_SRCS / stdlib)

    # Fixup
    # The Rust build doesn't have an option to auto-strip binaries, so we do
    # it here.
    # We don't attempt to strip .rlibs since it prevents building Rust binaries.
    # We don't attempt to strip anything under rustlib/ since these include
    # both debug symbols which we may want to link into user code and Rust
    # metadata needed at build time.
    #
    # TODO: Investigate the rustc and config.toml stripping mechanisms
    binaries = [path.as_posix() for path in list(
            (OUT_PATH_PACKAGE / "lib").glob("*.so")) + [
            OUT_PATH_PACKAGE / "bin" / "rustc",
            OUT_PATH_PACKAGE / "bin" / "cargo",
            OUT_PATH_PACKAGE / "bin" / "rustdoc"]]
    run_quiet_and_exit_on_failure(
        ["strip", "-S"] + binaries,
        "Failed to strip debugging info from generated binaries")

    # Install the libc++ library to out/package/lib64/
    if build_platform.is_darwin():
        libcxx_name = "libc++.dylib"
    else:
        libcxx_name = "libc++.so.1"

    lib64_path = OUT_PATH_PACKAGE / "lib64"
    lib64_path.mkdir(exist_ok=True)
    shutil.copy2(LLVM_CXX_RUNTIME_PATH / libcxx_name,
                 lib64_path / libcxx_name)

    # Some stdlib crates might include Android.mk or Android.bp files.
    # If they do, filter them out.
    if build_platform.is_linux():
        for f in OUT_PATH_STDLIB_SRCS.glob("**/Android.{mk,bp}"):
            f.unlink()

    # Dist
    print("Creating artifacts")
    archive_path_profiles = DIST_PATH / f"rust-profraw-{args.build_name}.tar.gz"
    generate_arg = args.profile_generate or args.cs_profile_generate
    if generate_arg:
        run_and_exit_on_failure(f"tar czf {archive_path_profiles} .",
                                "Failed to create profiles archive.",
                                cwd=generate_arg)

    if args.profile_use and args.profile_use != DIST_PATH:
        for p in args.profile_use.glob("*.profdata"):
            shutil.copy(p, DIST_PATH)

    archive_path_rust = DIST_PATH / f"rust-{args.build_name}.tar.gz"
    run_and_exit_on_failure(f"tar czf {archive_path_rust} .",
                            "Failed to create distribution archive",
                            cwd=OUT_PATH_PACKAGE)

if __name__ == "__main__":
    main()
