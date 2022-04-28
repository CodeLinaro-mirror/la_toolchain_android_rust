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
from typing import Any, Tuple

import build_platform
from paths import *
from utils import profdata_merge

#
# Constants
#

HOST_TARGETS:   list[str] = [build_platform.triple()] + build_platform.alt_triples()
BARE_TARGETS:   list[str] = [
    "aarch64-unknown-none",
    "riscv32i-unknown-none-elf",
]
DEVICE_TARGETS: list[str] = [
    "aarch64-linux-android",
    "armv7-linux-androideabi",
    "x86_64-linux-android",
    "i686-linux-android",
]

ALL_TARGETS: list[str] = HOST_TARGETS + BARE_TARGETS + DEVICE_TARGETS

ANDROID_TARGET_VERSION: str = "31"

BARE_CC_WRAPPER_TEMPLATE:       Path = TEMPLATES_PATH / "bare_cc_wrapper.template"
BARE_LINKER_WRAPPER_TEMPLATE:   Path = TEMPLATES_PATH / "bare_linker_wrapper.template"
BARE_TARGET_TEMPLATE:           Path = TEMPLATES_PATH / "bare_target.template"
CONFIG_TOML_TEMPLATE:           Path = TEMPLATES_PATH / "config.toml.template"
DEVICE_CC_WRAPPER_TEMPLATE:     Path = TEMPLATES_PATH / "device_cc_wrapper.template"
DEVICE_LINKER_WRAPPER_TEMPLATE: Path = TEMPLATES_PATH / "device_linker_wrapper.template"
DEVICE_TARGET_TEMPLATE:         Path = TEMPLATES_PATH / "device_target.template"
HOST_CC_WRAPPER_TEMPLATE:       Path = TEMPLATES_PATH / "host_cc_wrapper.template"
HOST_CXX_WRAPPER_TEMPLATE:      Path = TEMPLATES_PATH / "host_cxx_wrapper.template"
HOST_LINKER_WRAPPER_TEMPLATE:   Path = TEMPLATES_PATH / "host_linker_wrapper.template"
HOST_TARGET_TEMPLATE:           Path = TEMPLATES_PATH / "host_target.template"

#
# Helper functions
#

def vp_counters_flags(num_counters: int) -> str:
    return f"-Xclang -mllvm -Xclang -vp-counters-per-site={num_counters}"


def apply_target_flags(target: str, cc_flags: list[str], cxx_flags: list[str], ld_flags: list[str], android_version: str = "", escape: bool = True) -> Tuple[str, str, str]:
    target_flag = [f"--target={target}{android_version}"]

    cc_flags_str = " ".join(
        target_flag +
        TARGET_COMMON_FLAGS.get(target, []) +
        TARGET_CC_FLAGS.get(target, []) +
        cc_flags)

    cxx_flags_str = " ".join(
        target_flag +
        TARGET_COMMON_FLAGS.get(target, []) +
        TARGET_CC_FLAGS.get(target, []) +
        TARGET_CXX_FLAGS.get(target, []) +
        cxx_flags)

    ld_flags_str = " ".join(
        target_flag +
        TARGET_COMMON_FLAGS.get(target, []) +
        TARGET_LD_FLAGS.get(target, []) +
        ld_flags)

    if escape:
        cc_flags_str  = cc_flags_str.replace("$", "\\$")
        cxx_flags_str = cxx_flags_str.replace("$", "\\$")
        ld_flags_str  = ld_flags_str.replace("$", "\\$")

    return (cc_flags_str, cxx_flags_str, ld_flags_str)


def darwin_sysroot() -> str:
    if build_platform.is_darwin():
        # Apple removed the normal sysroot at / on Mojave+, so we need
        # to go hunt for it on OSX
        # On pre-Mojave, this command will output the empty string.
        output = subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"])
        return output.rstrip().decode("utf-8")
    return ""


def instantiate_template_exec(template_path: Path, output_path: Path, **kwargs: Any) -> None:
    instantiate_template_file(template_path, output_path, make_exec=True, **kwargs)


def instantiate_template_file(template_path: Path, output_path: Path, make_exec: bool = False, **kwargs: Any) -> None:
    with open(template_path) as template_file:
        template = Template(template_file.read())
        with open(output_path, "w") as output_file:
            output_file.write(template.substitute(**kwargs))
    if make_exec:
        output_path.chmod(output_path.stat().st_mode | stat.S_IEXEC)


def print_flags(target: str, cc_flags: str, cxx_flags: str, ld_flags: str) -> None:
    print(f"Compiler/linker flags for {target}")
    print(f"CC  Flags: {cc_flags}")
    if cxx_flags:
        print(f"CXX Flags: {cxx_flags}")
    print(f"LD  Flags: {ld_flags}\n")


def get_wrapper_paths(target: str) -> Tuple[Path, Path, Path]:
    return (
        OUT_PATH_WRAPPERS / f"clang-{target}",
        OUT_PATH_WRAPPERS / f"clang++-{target}",
        OUT_PATH_WRAPPERS / f"linker-{target}",
    )

#
# Target configuration
#

def host_config(target: str, cc_flags: list[str], cxx_flags: list[str], ld_flags: list[str]) -> str:
    cc_wrapper_name, cxx_wrapper_name, ld_wrapper_name = get_wrapper_paths(target)
    cc_flags_str, cxx_flags_str, ld_flags_str = apply_target_flags(target, cc_flags, cxx_flags, ld_flags)
    print_flags(target, cc_flags_str, cxx_flags_str, ld_flags_str)

    instantiate_template_exec(
        HOST_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        cc_flags=cc_flags_str)

    instantiate_template_exec(
        HOST_CXX_WRAPPER_TEMPLATE,
        cxx_wrapper_name,
        real_cxx=CXX_PATH,
        cxx_flags=cxx_flags_str)

    instantiate_template_exec(
        HOST_LINKER_WRAPPER_TEMPLATE,
        ld_wrapper_name,
        real_cxx=CXX_PATH,
        ld_flags=ld_flags_str)

    with open(HOST_TARGET_TEMPLATE, "r") as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cxx_wrapper_name,
            linker=ld_wrapper_name,
            ar=AR_PATH,
            ranlib=RANLIB_PATH)


def bare_config(target: str, cc_flags: list[str], ld_flags: list[str]) -> str:
    cc_wrapper_name, _, ld_wrapper_name = get_wrapper_paths(target)
    cc_flags_str, _, ld_flags_str = apply_target_flags(target, cc_flags, [], ld_flags)
    print_flags(target, cc_flags_str, "", ld_flags_str)

    instantiate_template_exec(
        BARE_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        cc_flags=cc_flags_str)

    instantiate_template_exec(
        BARE_LINKER_WRAPPER_TEMPLATE,
        ld_wrapper_name,
        real_cc=CC_PATH,
        ld_flags=ld_flags_str)

    with open(BARE_TARGET_TEMPLATE, "r") as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cc_wrapper_name,
            linker=ld_wrapper_name,
            ar=AR_PATH)


def device_config(target: str, cc_flags: list[str], ld_flags: list[str]) -> str:
    cc_wrapper_name, _, ld_wrapper_name = get_wrapper_paths(target)
    cc_flags_str,    _, ld_flags_str    = apply_target_flags(
        target, cc_flags, [], ld_flags, android_version=ANDROID_TARGET_VERSION)

    print_flags(target, cc_flags_str, "", ld_flags_str)

    instantiate_template_exec(
        DEVICE_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        cc_flags=cc_flags_str)

    instantiate_template_exec(
        DEVICE_LINKER_WRAPPER_TEMPLATE,
        ld_wrapper_name,
        real_cc=CC_PATH,
        ld_flags=ld_flags_str)

    with open(DEVICE_TARGET_TEMPLATE, "r") as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cc_wrapper_name,
            linker=ld_wrapper_name,
            ar=AR_PATH)

#
# Main configuration
#

CC_FLAG_PIC:     str = "-fpic"
LD_FLAG_PIC:     str = "-Wl,-mllvm,--relocation-model=pic"
LD_FLAG_USE_LLD: str = "-fuse-ld=lld"

MACOSX_VERSION_FLAG: str = "-mmacosx-version-min=10.14"

HOST_SYSROOTS: dict[str, str] = {
    "x86_64-unknown-linux-gnu": GCC_SYSROOT_PATH.as_posix(),
    "i686-unknown-linux-gnu":   GCC_SYSROOT_PATH.as_posix(),
    "x86_64-apple-darwin":      darwin_sysroot(),
}


TARGET_COMMON_FLAGS: dict[str, list[str]] = {}
for arch, sysroot in HOST_SYSROOTS.items():
    sysroot_flag = f"--sysroot={sysroot}"
    if arch in TARGET_COMMON_FLAGS:
        TARGET_COMMON_FLAGS[arch].append(sysroot_flag)
    else:
        TARGET_COMMON_FLAGS[arch] = [sysroot_flag]

TARGET_CC_FLAGS:  dict[str, list[str]] = {}
TARGET_CXX_FLAGS: dict[str, list[str]] = {}

HOST_LINUX_LD_FLAGS: list[str] = [
    LD_FLAG_USE_LLD,
    "--rtlib=compiler-rt",
    # Reply on rust.llvm-libunwind="in-tree" in config.toml to link host
    # binaries against the in-tree built LLVM libunwind.  The version of
    # libunwind in our prebuilts is for devices only.
    #"-lunwind",
    f"-B{GCC_LIBGCC_PATH}",
    f"-L{GCC_LIBGCC_PATH}",
    f"-L{GCC_LIB_PATH}",
    f"-L{LLVM_CXX_RUNTIME_PATH}",
]
TARGET_LD_FLAGS: dict[str, list[str]] = {
    # When performing LTO, the LLVM IR generator doesn't know about these
    # target specific symbols. By telling the linker about them ahead of time
    # we avoid an error when they are encountered when the native code is
    # emitted.  See b/201551165 for more information.
    "armv7-linux-androideabi": [
        "-u __aeabi_uidiv",
        "-u __aeabi_idiv0",
    ],

    "x86_64-unknown-linux-gnu": HOST_LINUX_LD_FLAGS,
    "i686-unknown-linux-gnu":   HOST_LINUX_LD_FLAGS,

    "x86_64-apple-darwin": [
        f"-L{LLVM_CXX_RUNTIME_PATH}",
    ],
}


def configure(args: argparse.Namespace, env: dict[str, str]) -> None:
    """Generates config.toml and compiler wrapers for the rustc build."""

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

    #
    # Flag set definitions
    #

    common_cc_flags = []
    # `-fuse-ld=lld` will cause Clang to use the prebuilt version of LLD.  This
    # is not desired on Darwin hosts as only the system linker can successfully
    # link binaries for the platform.  As such this flag is not included here
    # and is instead listed in `bare_ld_flags`, `device_ld_flags` and specific
    # host target flags.
    common_ld_flags = []

    host_common_flags = []
    host_cc_flags     = [CC_FLAG_PIC]
    # All flags from host_cc_flags will be added to host_cxx_flags
    host_cxx_flags    = [
        "--stdlib=libc++",
        f"-I{CXXSTD_PATH}",
    ]
    host_ld_flags     = [
        LD_FLAG_PIC,
        f"-Wl,-rpath,{build_platform.rpath_origin()}/../lib64",
    ]

    bare_cc_flags: list[str] = []
    bare_ld_flags: list[str] = [LD_FLAG_USE_LLD]

    device_common_flags = [f"--sysroot={NDK_SYSROOT_PATH}"]
    device_cc_flags     = [CC_FLAG_PIC]
    # No need to pass `--rtlib=compiler-rt -lunwind` arguments here because NDK
    # r23+ only has compiler-rt
    device_ld_flags     = [
        LD_FLAG_USE_LLD,
        LD_FLAG_PIC,
    ]

    llvm_common_flags = []
    llvm_cc_flags     = []
    llvm_ld_flags     = []

    env_cflags: list[str] = []
    env_rustflags         = ["-C relocation-model=pic"]

    #
    # Build platform based configuration
    #

    if build_platform.is_darwin():
        host_common_flags.append(MACOSX_VERSION_FLAG)

    #
    # Command-line based configuration
    #

    # LTO

    if args.lto != "none":
        lto_flag = f"-flto={args.lto}"

        # The LTO flag must be passed to the compiler via the CFLAGS environment
        # variable due to the fact that including it in the host c/cxx wrappers
        # will cause the CMake compiler detection routine to fail during LLVM
        # configuration.
        #
        # The Rust bootstrap system will include the value of CFLAGS in all
        # invocations of either the C or C++ compiler for all host targets.  The
        # LLVM build system will receive the LTO flag value from the
        # llvm::cflags and llvm::cxxflags values in the config.toml file
        # instantiated below.
        #
        # Because Rust's bootstrap system doesn't pass the linker wrapper into
        # the LLVM build system AND doesn't respect the LDFLAGS environment
        # variable this value gets into the LLVM build system via the
        # llvm::ldflags value in config.toml and the Rust build system via the
        # host linker wrapper, both of which are instantiated below using the
        # same value for host_ld_flags.
        #
        # Note: Rust's bootstrap system will use CFLAGS for both C and C++
        #       compiler invocations.
        env_cflags.append(lto_flag)

        llvm_cc_flags.append(lto_flag)
        host_ld_flags.append(lto_flag)
        device_ld_flags.append(lto_flag)

        env_rustflags.append("-C linker-plugin-lto")

    # PGO

    rustc_pgo_config: str = ""
    if args.profile_generate != None:
        profile_name = PROFILE_SUBDIR_LLVM if args.llvm_linkage == "shared" else PROFILE_SUBDIR_RUST
        profile_path = args.profile_generate / profile_name
        llvm_common_flags += [
            f"-fprofile-generate={profile_path}",
            vp_counters_flags(16 if args.llvm_linkage == "static" else 4),
        ]

        rustc_pgo_config = f"profile-generate = \"{args.profile_generate / PROFILE_SUBDIR_RUST}\""

    elif args.profile_use != None:
        profile_path_llvm: Path = args.profile_use / PROFILE_NAME_LLVM_CS
        profile_path_rust: Path = args.profile_use / PROFILE_NAME_RUST

        # LLVM
        if not profile_path_llvm.exists():
            profile_path_llvm = args.profile_use / PROFILE_NAME_LLVM

        if profile_path_llvm.exists():
            llvm_common_flags += [
                f"-fprofile-use={profile_path_llvm}",
            ]

        # Rust

        if profile_path_rust.exists():
            rustc_pgo_config  = f"profile-use = \"{profile_path_rust}\""

        if not (profile_path_llvm.exists() or profile_path_rust.exists()):
            sys.exit(f"No profiles found in specified directory: {args.profile_use}")


    if args.cs_profile_generate != None:
        # TODO: The vp-counters-per-site value needs to be tuned to eliminate
        #       warnings about the inability to allocate counters during
        #       context-sensitive profiling.

        if args.llvm_linkage == "shared":
            profile_path = args.cs_profile_generate / PROFILE_SUBDIR_LLVM_CS
            llvm_common_flags += [
                f"-fcs-profile-generate={profile_path}",
                vp_counters_flags(32),
            ]

        else: # args.llvm_linkage == "static"
            if args.lto == None:
                raise RuntimeError("Context-sensitive PGO with static LLVM linkage requires LTO to be enabled")

            profile_path = args.cs_profile_generate / PROFILE_SUBDIR_RUST

            llvm_common_flags += [
                f"-fcs-profile-generate={profile_path}",
                vp_counters_flags(32),
            ]
            llvm_ld_flags += [
                " -Wl,--lto-cs-profile-generate",
                f"-Wl,--lto-cs-profile-file={profile_path}",
            ]

            env_rustflags += [
                f"-C link-arg=-fcs-profile-generate={profile_path}",
                " -C link-arg=-Wl,--lto-cs-profile-generate",
                f"-C link-arg=-Wl,--lto-cs-profile-file={profile_path}"
            ]


    # Misc.

    if args.bolt or args.emit_relocs:
        host_ld_flags.append("-Wl,--emit-relocs")

    if args.gc_sections:
        common_cc_flags += ["-ffunction-sections", "-fdata-sections"]
        common_ld_flags.append("-Wl,--gc-sections")

    llvm_link_shared = "true" if args.llvm_linkage == "shared" else "false"

    # Coalesce flags

    host_cc_flags  = common_cc_flags + host_common_flags + host_cc_flags
    host_cxx_flags = host_cc_flags + host_cxx_flags
    host_ld_flags  = common_ld_flags + host_common_flags + host_ld_flags

    bare_cc_flags = common_cc_flags + bare_cc_flags
    bare_ld_flags = common_ld_flags + bare_ld_flags

    device_cc_flags = common_cc_flags + device_common_flags + device_cc_flags
    device_ld_flags = common_ld_flags + device_common_flags + device_ld_flags

    llvm_cc_flags_str = " ".join(llvm_common_flags + llvm_cc_flags)
    llvm_ld_flags_str = " ".join(
        TARGET_COMMON_FLAGS[build_platform.triple()] +
        TARGET_LD_FLAGS[build_platform.triple()] +
        host_ld_flags +
        llvm_common_flags +
        llvm_ld_flags)

    env["CFLAGS"]    = " ".join(env_cflags)
    env["RUSTFLAGS"] = " ".join(env_rustflags)

    # Display final flag strings

    print()
    print("Compiler/Linker Flags")
    print()
    print(f"env CFLAGS   : {env['CFLAGS']}")
    print(f"env RUSTFLAGS: {env['RUSTFLAGS']}")
    print()
    print(f"LLVM CC Flags: {llvm_cc_flags_str}")
    print(f"LLVM LD Flags: {llvm_ld_flags_str}")
    print()

    #
    # Intantiate wrappers
    #

    host_configs = "\n".join(
        [host_config(target, host_cc_flags, host_cxx_flags, host_ld_flags) for target in HOST_TARGETS])
    bare_configs = "\n".join(
        [bare_config(target, bare_cc_flags, bare_ld_flags) for target in BARE_TARGETS])
    device_configs = "\n".join(
        [device_config(target, device_cc_flags, device_ld_flags) for target in DEVICE_TARGETS])

    quoted_target_list = ",".join([f'\"{target}\"' for target in ALL_TARGETS])
    all_targets_str    = f"[{quoted_target_list}]"

    instantiate_template_file(
        CONFIG_TOML_TEMPLATE,
        OUT_PATH_RUST_SOURCE / "config.toml",
        llvm_link_shared=llvm_link_shared,
        llvm_cflags=llvm_cc_flags_str,
        llvm_cxxflags=llvm_cc_flags_str,
        llvm_ldflags=llvm_ld_flags_str,
        all_targets=all_targets_str,
        cargo=CARGO_PATH,
        rustc=RUSTC_PATH,
        python=PYTHON_PATH,
        pgo_config=rustc_pgo_config,
        host_configs=host_configs,
        bare_configs=bare_configs,
        device_configs=device_configs)
