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
import sys
from typing import Optional

import build_platform
from paths import (
    DIST_PATH_DEFAULT,
    OUT_PATH_PROFILES,
    RUST_PREBUILT_PATH)
from utils import TEST_VERSION_NUMBER, ResolvedPath, export_profiles, run_build_command, run_quiet_and_exit_on_failure

RUST_PREBUILT_NAME_PATTERN = re.compile("rust-(?!profraw)(\S*)\.tar\.gz")
RUST_PROFILES_NAME_PATTERN = re.compile("rust-profraw-(\S*)\.tar\.gz")

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
        "--target", type=str, required=True,
        help="Device target to build for")
    parser.add_argument(
        "--dist", "-d", dest="dist_path", type=ResolvedPath, default=DIST_PATH_DEFAULT,
        help="Where to place distributable artifacts")

    parser.add_argument(
        "--image", "-i", action="store_true",
        help="Build an image as part of the compiler test")

    pgo_group = parser.add_mutually_exclusive_group()
    pgo_group.add_argument(
        "--profile-generate", type=Path, nargs="?", const=OUT_PATH_PROFILES,
        help="Path where instrumented prebuilts will place their profiles")
    pgo_group.add_argument(
        "--cs-profile-generate", type=Path, nargs="?", const=OUT_PATH_PROFILES,
        help="Path were context-sensitive instrumented prebuilts will place their profiles")

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


def build_rust_artifacts(target: str) -> int:
    # Run 'm rust' for build target
    print("Building Rust targets")
    return run_build_command("m rust", target)


def build_image(target: str) -> int:
    # Run 'm' for build target
    print("Building Android image")
    return run_build_command("m", target)


def run_test(prebuilt_path: Path, target: str, dist_path: Path, profile_generate: Optional[Path], cs_profile_generate: Optional[Path]) -> int:
    prepare_prebuilts(prebuilt_path)
    retcode = build_rust_artifacts(target)
    export_profiles(profile_generate or cs_profile_generate, dist_path)
    return retcode


def main() -> None:
    args = parse_args()

    retcode = run_test(
        args.prebuilt_path, args.target, args.dist_path, args.profile_generate, args.cs_profile_generate)

    if retcode == 0 and args.image:
        retcode = build_image(args.target)

    sys.exit(retcode)

if __name__ == "__main__":
    main()
