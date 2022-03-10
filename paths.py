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
"""Provides path expansion to components needed for the rustc build."""

import os
from pathlib import Path

import build_platform

RUST_VERSION_STAGE0: str = '1.59.0'
CLANG_REVISION:      str = 'r437112b'
CLANG_NAME:          str = 'clang-{0}'.format(CLANG_REVISION)
GLIBC_VERSION:       str = '2.17-4.8'
GLIBC_SUBVERSION:    str = '4.8.3'

TOOLCHAIN_PATH:   Path = Path(__file__).parent.resolve()
WORKSPACE_PATH:   Path = (TOOLCHAIN_PATH / '..' / '..').resolve()
RUST_SOURCE_PATH: Path = (TOOLCHAIN_PATH / '..' / 'rustc').resolve()

# We take DIST_DIR through an environment variable rather than an
# argument to match the interface for traditional Android builds.
DIST_PATH: Path = (
    Path(os.environ["DIST_DIR"]).resolve() if "DIST_DIR" in os.environ else
    (WORKSPACE_PATH / "dist"))

PATCHES_PATH:   Path = TOOLCHAIN_PATH / 'patches'
TEMPLATES_PATH: Path = TOOLCHAIN_PATH / 'templates'

OUT_PATH:             Path = WORKSPACE_PATH / 'out'
OUT_PATH_RUST_SOURCE: Path = OUT_PATH / 'rustc'
OUT_PATH_PACKAGE:     Path = OUT_PATH / 'package'
OUT_PATH_PATCHS_LOG:  Path = OUT_PATH / 'patches.log'
OUT_PATH_PROFILES:    Path = OUT_PATH / 'profiles'
OUT_PATH_STDLIB_SRCS: Path = OUT_PATH_PACKAGE / 'src' / 'stdlibs'
OUT_PATH_WRAPPERS:    Path = OUT_PATH / 'wrappers'

DOWNLOADS_PATH: Path = WORKSPACE_PATH / '.downloads'

LLVM_BUILD_PATH: Path = OUT_PATH_RUST_SOURCE / 'build' / build_platform.triple() / 'llvm' / 'build'

PREBUILT_PATH:         Path = WORKSPACE_PATH / 'prebuilts'
RUST_PREBUILT_PATH:    Path = PREBUILT_PATH / 'rust'
RUST_HOST_STAGE0_PATH: Path = RUST_PREBUILT_PATH / build_platform.prebuilt() / RUST_VERSION_STAGE0
LLVM_PREBUILT_PATH:    Path = PREBUILT_PATH / 'clang' / 'host' / build_platform.prebuilt() / CLANG_NAME
LLVM_CXX_RUNTIME_PATH: Path = LLVM_PREBUILT_PATH / 'lib64'

GCC_TOOLCHAIN_PATH: Path = PREBUILT_PATH / 'gcc' / build_platform.prebuilt() / 'host' / ('x86_64-linux-glibc' + GLIBC_VERSION)
GCC_LIB_PATH:       Path = GCC_TOOLCHAIN_PATH / 'x86_64-linux' / 'lib64'
GCC_LIBGCC_PATH:    Path = GCC_TOOLCHAIN_PATH / 'lib' / 'gcc' / 'x86_64-linux' / GLIBC_SUBVERSION
GCC_SYSROOT_PATH:   Path = GCC_TOOLCHAIN_PATH / 'sysroot'

PYTHON_PREBUILT_PATH:      Path = PREBUILT_PATH / 'python' / build_platform.prebuilt()
CMAKE_PREBUILT_PATH:       Path = PREBUILT_PATH / 'cmake' / build_platform.prebuilt()
NINJA_PREBUILT_PATH:       Path = PREBUILT_PATH / 'ninja' / build_platform.prebuilt()
BUILD_TOOLS_PREBUILT_PATH: Path = PREBUILT_PATH / 'build-tools' / 'path' / build_platform.prebuilt()
CURL_PREBUILT_PATH:        Path = PREBUILT_PATH / 'android-emulator-build' / 'cur' / build_platform.prebuilt_full()

# Use of the NDK should eventually be removed so as to make this a Platform
# target, but is used for now as a transition stage.
NDK_PATH:         Path = WORKSPACE_PATH / 'toolchain' / 'prebuilts' / 'ndk' / 'r23'
NDK_LLVM_PATH:    Path = NDK_PATH / 'toolchains' / 'llvm' / 'prebuilt' / 'linux-x86_64'
NDK_SYSROOT_PATH: Path = NDK_LLVM_PATH / 'sysroot'

SOONG_PATH: Path = WORKSPACE_PATH / 'build' / 'soong'

#
# Paths to toolchain executables
#

CARGO_PATH:  Path = RUST_HOST_STAGE0_PATH / 'bin' / 'cargo'
RUSTC_PATH:  Path = RUST_HOST_STAGE0_PATH / 'bin' / 'rustc'
PYTHON_PATH: Path = PYTHON_PREBUILT_PATH  / 'bin' / 'python3'
CC_PATH:     Path = LLVM_PREBUILT_PATH    / 'bin' / 'clang'
CXX_PATH:    Path = LLVM_PREBUILT_PATH    / 'bin' / 'clang++'
AR_PATH:     Path = LLVM_PREBUILT_PATH    / 'bin' / 'llvm-ar'
RANLIB_PATH: Path = LLVM_PREBUILT_PATH    / 'bin' / 'llvm-ranlib'
CXXSTD_PATH: Path = LLVM_PREBUILT_PATH    / 'include' / 'c++' / 'v1'

#
# Paths to binfs executables
#

FETCH_ARTIFACT_PATH: Path = Path('/google/data/ro/projects/android/fetch_artifact')
