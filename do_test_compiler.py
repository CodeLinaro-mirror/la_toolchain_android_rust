#!/usr/bin/env python3
#
# Copyright (C) 2022 The Android Open Source Project
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


import argparse
import inspect
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Optional

import build_platform
from paths import (
    DIST_PATH,
    OUT_PATH_PROFILES,
    PROFDATA_PATH,
    PROFILE_NAME_LLVM,
    PROFILE_NAME_LLVM_CS,
    PROFILE_NAME_RUST,
    PROFILE_SUBDIR_LLVM,
    PROFILE_SUBDIR_LLVM_CS,
    PROFILE_SUBDIR_RUST,
    RUST_PREBUILT_PATH)
from utils import ResolvedPath, run_and_exit_on_failure, run_quiet_and_exit_on_failure

RUST_PREBUILT_NAME_PATTERN = re.compile("rust-(?!profraw)(\S*)\.tar\.gz")
RUST_PROFILES_NAME_PATTERN = re.compile("rust-profraw-(\S*)\.tar\.gz")

TEST_VERSION_NUMBER: str = "9.99.9"

#
# Helper functions
#

def resolve_argument_path(arg_path: Path, name_pattern: re.Pattern) -> Optional[Path]:
    # Resolve prebuilt path
    resolved_path: Path = arg_path
    if resolved_path.exists():
        if resolved_path.is_dir():
            matches = [f for f in resolved_path.iterdir() if name_pattern.match(f.name)]
            if len(matches) > 1:
                return None

            resolved_path = matches.pop()

        return resolved_path.resolve()

    else:
        return None

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=inspect.getdoc(sys.modules[__name__]))

    parser.add_argument(
        "--prebuilt-path", type=ResolvedPath, required=True,
        help="Path to either the build artifact or the directory that contains it")
    parser.add_argument(
        "--profile-import", type=ResolvedPath,
        help="Path to either a rust-profraw-*.tar.gz file or a directory that contains one")

    pgo_group = parser.add_mutually_exclusive_group()
    pgo_group.add_argument(
        "--profile-generate", type=Path, nargs="?", const=OUT_PATH_PROFILES,
        help="Path where instrumented prebuilts will place their profiles")
    pgo_group.add_argument(
        "--cs-profile-generate", type=Path, nargs="?", const=OUT_PATH_PROFILES,
        help="Path were context-sensitive instrumented prebuilts will place their profiles")

    parser.add_argument(
        "--target", type=str, required=True,
        help="Device target to build for")

    return parser.parse_args()


def prepare_prebuilts(prebuilt_path: Path) -> None:
    prebuilt_path = resolve_argument_path(prebuilt_path, RUST_PREBUILT_NAME_PATTERN)
    if prebuilt_path == None:
        sys.exit("Failed to resolve prebuilt path.  Path either doesn't exist or contains multiple prebuilt archives.")

    # Prepare host/version path
    target_and_version_path: Path = RUST_PREBUILT_PATH / build_platform.prebuilt() / TEST_VERSION_NUMBER
    if target_and_version_path.exists():
        print("Test prebuilt directory already exists.  Deleting contents.")
        shutil.rmtree(target_and_version_path, ignore_errors=True)

    target_and_version_path.mkdir()

    # Unpack prebuilt
    print(f"Extracting archive {prebuilt_path}")
    run_quiet_and_exit_on_failure(
        f"tar -xzf {prebuilt_path}",
        f"Failed to extract prebuilt archive",
        cwd=target_and_version_path)


def prepare_profiles(profile_import: Optional[Path], generate_arg: Optional[Path]) -> None:
    if profile_import == None:
        return

    if generate_arg == None:
        sys.exit("A 'profile-generate' flag must be passed if 'profile-import' is used.")

    profile_import = resolve_argument_path(profile_import, RUST_PROFILES_NAME_PATTERN)
    if profile_import == None:
        sys.exit("Failed to resolve profiles import path.  Path either doesn't exist or contains multiple profile archives.")

    # Prepare profiles directory
    if generate_arg.exists():
        sys.exit(f"Invalid state: {generate_arg.as_posix()} already exists")
    else:
        generate_arg.mkdir()

    # Unpack imported profiles
    run_quiet_and_exit_on_failure(
        f"tar -xzf {profile_import}",
        f"Failed to extract profiles archive",
        cwd=generate_arg)


def run_tests(target: str) -> int:
    # Run 'm rust && m' for build target
    ENVSETUP_PATH = Path.cwd() / "build" / "envsetup.sh"
    return subprocess.run(
        f". ./{ENVSETUP_PATH} && lunch {target} && " +
        f"RUST_PREBUILTS_VERSION={TEST_VERSION_NUMBER} m rust",
        shell=True, stderr=subprocess.STDOUT)


def export_profiles(profile_import: Optional[Path], profile_generate: Optional[Path], cs_profile_generate: Optional[Path]) -> None:
    if profile_generate != None:
        profraw_llvm = " ".join([p.as_posix() for p in
            (profile_generate / PROFILE_SUBDIR_LLVM).glob("*.profraw")])
        run_and_exit_on_failure(
            f"{PROFDATA_PATH} merge -o {DIST_PATH / PROFILE_NAME_LLVM} {profraw_llvm}",
            "Failed to create LLVM profdata file")

        profraw_rust = " ".join([p.as_posix() for p in
            (profile_generate / PROFILE_SUBDIR_RUST).glob("*.profraw")])
        run_and_exit_on_failure(
            f"{PROFDATA_PATH} merge -o {DIST_PATH / PROFILE_NAME_RUST} {profraw_rust}",
            "Failed to create Rust profdata file")

    elif cs_profile_generate != None:
        profdata_llvm = ""
        if profile_import:
            if profile_import.is_dir():
                llvm_profile = profile_import / PROFILE_NAME_LLVM
                if llvm_profile.exists():
                    profdata_llvm = llvm_profile.as_posix()
            elif profile_import.is_file() and profile_import.name() == PROFILE_NAME_LLVM:
                profdata_llvm = profile_import.as_posix()

        profraw_llvm_cs = " ".join([p.as_posix() for p in
            (cs_profile_generate / PROFILE_SUBDIR_LLVM_CS).glob("*.profraw")])
        run_and_exit_on_failure(
            f"{PROFDATA_PATH} merge -o {DIST_PATH / PROFILE_NAME_LLVM_CS} {profdata_llvm} {profraw_llvm_cs}",
            "Failed to create context-sensitive LLVM profdata file")

        if profile_import:
            if profile_import.is_dir():
                for p in profile_import.glob("*.profdata"):
                    shutil.copy(p, DIST_PATH)
            elif profile_import.is_file() and profile_import:
                shutil.copy(profile_import, DIST_PATH)


def main() -> None:
    args = parse_args()

    prepare_prebuilts(args.prebuilt_path)
    prepare_profiles(args.profile_import, args.profile_generate or args.cs_profile_generate)
    retcode = run_tests(args.target)
    export_profiles(args.profile_import, args.profile_generate, args.cs_profile_generate)

    sys.exit(retcode)

if __name__ == "__main__":
    main()
