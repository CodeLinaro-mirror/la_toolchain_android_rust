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
"""Handles generation of config.toml for the rustc build."""

import argparse
import os
from pathlib import Path
import subprocess
import stat
from string import Template
import sys
from typing import Any

import build_platform
from paths import *


HOST_TARGETS: list[str] = [build_platform.triple()] + build_platform.alt_triples()
DEVICE_TARGETS: list[str] = ["aarch64-linux-android", "armv7-linux-androideabi",
                  "x86_64-linux-android", "i686-linux-android"]

ALL_TARGETS: list[str] = HOST_TARGETS + DEVICE_TARGETS

TARGET_SPECIFIC_LINKER_FLAGS: dict[str, str] = {
    # When performing LTO, the LLVM IR generator doesn't know about these
    # target specific symbols. By telling the linker about them ahead of time
    # we avoid an error when they are encountered when the native code is
    # emitted.  See b/201551165 for more information.
    "armv7-linux-androideabi": "-u __aeabi_uidiv -u __aeabi_idiv0"
}

ANDROID_TARGET_VERSION: str = "31"

CONFIG_TOML_TEMPLATE:           Path = TEMPLATES_PATH / "config.toml.template"
DEVICE_CC_WRAPPER_TEMPLATE:     Path = TEMPLATES_PATH / "device_cc_wrapper.template"
DEVICE_LINKER_WRAPPER_TEMPLATE: Path = TEMPLATES_PATH / "device_linker_wrapper.template"
DEVICE_TARGET_TEMPLATE:         Path = TEMPLATES_PATH / "device_target.template"
HOST_CC_WRAPPER_TEMPLATE:       Path = TEMPLATES_PATH / "host_cc_wrapper.template"
HOST_CXX_WRAPPER_TEMPLATE:      Path = TEMPLATES_PATH / "host_cxx_wrapper.template"
HOST_LINKER_WRAPPER_TEMPLATE:   Path = TEMPLATES_PATH / "host_linker_wrapper.template"
HOST_TARGET_TEMPLATE:           Path = TEMPLATES_PATH / "host_target.template"

# TODO: The vp-counters-per-site value needs to be tuned to eliminate warnings about
#       the innability to allocate counters during context-sensitive profiling.
LINKER_PIC_FLAG:       str = "-Wl,-mllvm,-relocation-model=pic"
MACOSX_VERSION_FLAG:   str = "-mmacosx-version-min=10.14"
LLVM_PROFILE_FLAGS:    str = "-Xclang -mllvm -Xclang -vp-counters-per-site=2"
LLVM_CS_PROFILE_FLAGS: str = "-Xclang -mllvm -Xclang -vp-counters-per-site=20"


def instantiate_template_exec(template_path: Path, output_path: Path, **kwargs: Any) -> None:
    instantiate_template_file(template_path, output_path, make_exec=True, **kwargs)

def instantiate_template_file(template_path: Path, output_path: Path, make_exec: bool = False, **kwargs: Any) -> None:
    with open(template_path) as template_file:
        template = Template(template_file.read())
        with open(output_path, "w") as output_file:
            output_file.write(template.substitute(**kwargs))
    if make_exec:
        output_path.chmod(output_path.stat().st_mode | stat.S_IEXEC)


def host_config(target: str, sysroot: str, linker_flags: str) -> str:
    cc_wrapper_name     = OUT_PATH_WRAPPERS / f"clang-{target}"
    cxx_wrapper_name    = OUT_PATH_WRAPPERS / f"clang++-{target}"
    linker_wrapper_name = OUT_PATH_WRAPPERS / f"linker-{target}"

    macosx_version = MACOSX_VERSION_FLAG if build_platform.is_darwin() else ""

    if target in TARGET_SPECIFIC_LINKER_FLAGS:
        linker_flags += " " + TARGET_SPECIFIC_LINKER_FLAGS[target]

    instantiate_template_exec(
        HOST_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        target=target,
        macosx_flags=macosx_version,
        sysroot=sysroot)

    instantiate_template_exec(
        HOST_CXX_WRAPPER_TEMPLATE,
        cxx_wrapper_name,
        real_cxx=CXX_PATH,
        target=target,
        macosx_flags=macosx_version,
        sysroot=sysroot,
        cxxstd=CXXSTD_PATH)

    instantiate_template_exec(
        HOST_LINKER_WRAPPER_TEMPLATE,
        linker_wrapper_name,
        real_cxx=CXX_PATH,
        target=target,
        macosx_flags=macosx_version,
        sysroot=sysroot,
        linker_flags=linker_flags)

    with open(HOST_TARGET_TEMPLATE, "r") as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cxx_wrapper_name,
            linker=linker_wrapper_name,
            ar=AR_PATH,
            ranlib=RANLIB_PATH)


def device_config(target: str, linker_flags: str) -> str:
    cc_wrapper_name     = OUT_PATH_WRAPPERS / f"clang-{target}"
    linker_wrapper_name = OUT_PATH_WRAPPERS / f"linker-{target}"

    clang_target = target + ANDROID_TARGET_VERSION

    if target in TARGET_SPECIFIC_LINKER_FLAGS:
        linker_flags += " " + TARGET_SPECIFIC_LINKER_FLAGS[target]

    instantiate_template_exec(
        DEVICE_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        target=clang_target,
        sysroot=NDK_SYSROOT_PATH)

    instantiate_template_exec(
        DEVICE_LINKER_WRAPPER_TEMPLATE,
        linker_wrapper_name,
        real_cc=CC_PATH,
        target=clang_target,
        sysroot=NDK_SYSROOT_PATH,
        linker_flags=linker_flags)

    with open(DEVICE_TARGET_TEMPLATE, "r") as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cc_wrapper_name,
            linker=linker_wrapper_name,
            ar=AR_PATH)


def configure(args: argparse.Namespace, env: dict[str, str]) -> None:
    """Generates config.toml and compiler wrapers for the rustc build."""

    #
    # Compute compiler/linker flags
    #

    host_sysroot:     str = ""
    lto_flag:         str = f"-flto={args.lto}" if args.lto != "none" else ""
    llvm_flags:       str = lto_flag
    rustc_pgo_config: str = ""

    if args.profile_generate != None:
        llvm_flags       += f" -fprofile-generate={args.profile_generate / PROFILE_SUBDIR_LLVM} {LLVM_PROFILE_FLAGS}"
        rustc_pgo_config  = f"profile-generate = \"{args.profile_generate / PROFILE_SUBDIR_RUST}\""
    elif args.profile_use != None:
        profile_path_llvm: Path = args.profile_use / PROFILE_NAME_LLVM_CS
        profile_path_rust: Path = args.profile_use / PROFILE_NAME_RUST

        if not profile_path_llvm.exists():
            profile_path_llvm_orig = profile_path_llvm
            profile_path_llvm = args.profile_use / PROFILE_NAME_LLVM
            if not profile_path_llvm.exists():
                sys.exit(f"Required file missing: {profile_path_llvm} or {profile_path_llvm_orig}")
        elif not profile_path_rust.exists():
            sys.exit(f"Required file missing: {profile_path_rust}")

        llvm_flags       += f" -fprofile-use={profile_path_llvm}"
        rustc_pgo_config  = f"profile-use = \"{profile_path_rust}\""

    if args.cs_profile_generate != None:
        llvm_flags += f" -fcs-profile-generate={args.cs_profile_generate / PROFILE_SUBDIR_LLVM_CS} {LLVM_CS_PROFILE_FLAGS}"

    host_linker_flags: list[str] = [
        lto_flag,
        f"-Wl,-rpath,{build_platform.rpath_origin()}/../lib64",
        f"-L{LLVM_CXX_RUNTIME_PATH.as_posix()}"
    ]

    if build_platform.is_linux():
        host_sysroot = GCC_SYSROOT_PATH.as_posix()
        host_linker_flags += [
            "-fuse-ld=lld",
            f"-B{GCC_LIBGCC_PATH}",
            f"-L{GCC_LIBGCC_PATH}",
            f"-L{GCC_LIB_PATH}"
        ]

    elif build_platform.is_darwin():
        # Apple removed the normal sysroot at / on Mojave+, so we need
        # to go hunt for it on OSX
        # On pre-Mojave, this command will output the empty string.
        output = subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"])
        host_sysroot = output.rstrip().decode("utf-8")

    # The `$` character should be escaped in the wrappers but not in the
    # config.toml llvm::ldflags value (it causes Rust's boostrap system to
    # complain and CMake does its own escaping).
    host_linker_flags_str         = " ".join(host_linker_flags)
    host_linker_flags_str_escaped = host_linker_flags_str.replace("$", "\\$")

    device_linker_flags = LINKER_PIC_FLAG

    # Shared linking of LLVM is not supported on Darwin.
    llvm_link_shared = "true" if not build_platform.is_darwin() else "false"

    #
    # Update environment variables
    #

    env["PATH"] = os.pathsep.join(
        [p.as_posix() for p in [
          RUST_HOST_STAGE0_PATH / "bin",
          CMAKE_PREBUILT_PATH / "bin",
          NINJA_PREBUILT_PATH,
          BUILD_TOOLS_PREBUILT_PATH,
        ]] + [env["PATH"]])

    # Only adjust the library path on Linux - on OSX, use the devtools curl
    if build_platform.is_linux():
        if "LIBRARY_PATH" in env:
            old_library_path = f":{env['LIBRARY_PATH']}"
        else:
            old_library_path = ""
        env["LIBRARY_PATH"] = f"{CURL_PREBUILT_PATH / 'lib'}{old_library_path}"

    # Use LD_LIBRARY_PATH to tell the build system where to find libc++.so.1
    # without polluting the rpath of the produced artifacts.
    env["LD_LIBRARY_PATH"] = LLVM_CXX_RUNTIME_PATH.as_posix()

    # Tell the rust bootstrap system where to place its final products
    env["DESTDIR"] = OUT_PATH_PACKAGE.as_posix()

    # Pass additional flags to the Rust compiler
    env["RUSTFLAGS"] = "-C relocation-model=pic"

    if args.lto != "none":
        env["RUSTFLAGS"] += " -C linker-plugin-lto"

    # The LTO flag must be passed via the CFLAGS environment variable due to
    # the fact that including it in the host c/cxx wrappers will cause the
    # CMake compiler detection routine to fail during LLVM configuration.
    #
    # The Rust bootstrap system will include the value of CFLAGS in all
    # invocations of either the C or C++ compiler for all host targets.  The
    # LLVM build system will receive the LTO flag value from the llvm::cflags
    # and llvm::cxxflags values in the config.toml file instantiated below.
    #
    # Because Rust's bootstrap system doesn't pass the linker wrapper into the
    # LLVM build system AND doesn't respect the LDFLAGS environment variable
    # this value gets into the LLVM build system via the llvm::ldflags value in
    # config.toml and the Rust build system via the host linker wrapper, both
    # of which are instantiated below using the same value for host_linker_flags.
    #
    # Note: Rust's bootstrap system will use CFLAGS for both C and C++ compiler
    #       invocations.
    #
    # Note: The Rust bootstrap system will copy CFLAGS into CFLAGS when
    #       invoking the LLVM build system.  As a result the LTO argument will
    #       appear twice in the CMake language flag variables.
    env["CFLAGS"] = lto_flag

    #
    # Intantiate wrappers
    #

    host_configs = "\n".join(
        [host_config(target, host_sysroot, host_linker_flags_str_escaped) for target in HOST_TARGETS])
    device_configs = "\n".join(
        [device_config(target, device_linker_flags) for target in DEVICE_TARGETS])

    all_targets = "[" + ",".join(
        ['"' + target + '"' for target in ALL_TARGETS]) + ']'

    instantiate_template_file(
        CONFIG_TOML_TEMPLATE,
        OUT_PATH_RUST_SOURCE / "config.toml",
        llvm_link_shared=llvm_link_shared,
        llvm_cflags=llvm_flags,
        llvm_cxxflags=llvm_flags,
        llvm_ldflags=host_linker_flags_str,
        all_targets=all_targets,
        cargo=CARGO_PATH,
        rustc=RUSTC_PATH,
        python=PYTHON_PATH,
        pgo_config=rustc_pgo_config,
        host_configs=host_configs,
        device_configs=device_configs)
