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

"""Execute the stages of the Rust Toolchain PGO pipeline locally"""

import argparse
from pathlib import Path
import shutil
import sys

import build
import merge_profiles
from paths import DIST_PATH_DEFAULT, OUT_PATH_PROFILES
import test_compiler
from utils import ResolvedPath, run_build_command

TARGETS = {
    "raven":      "raven",
    "cuttlefish": "cf_x86_64_phone"
}

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Build Rust prebuilts using the PGO pipeline")
    parser.add_argument(
        "--build-name", type=str, default="pgo-pipeline",
        help="Name used in the creation of various artifacts")
    parser.add_argument(
        "--dist", "-d", dest="dist_path", type=ResolvedPath, default=DIST_PATH_DEFAULT,
        help="Where to place distributable artifacts")

    parser.add_argument(
        "--overwrite", "-o", action="store_true",
        help="Overwrite pre-existing PGO pipeline directories in DIST")
    parser.add_argument(
        "--start", "-s", type=float, choices=[1, 2, 2.5, 3, 4, 4.5, 5], default=1,
        help="Which stage to start the pipeline from")

    parser.add_argument(
        "--end", "-e", type=float, choices=[1, 2, 2.5, 3, 4, 4.5, 5], default=5,
        help="Which stage to end the pipeline at")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    def setup_dist_instance(instance_path: str) -> Path:
        dist_path: Path = args.dist_path / instance_path
        if dist_path.exists():
            if args.overwrite:
                shutil.rmtree(dist_path)
            else:
                sys.exit(f"PGO Pipeline stage directory exists: {dist_path}")
        dist_path.mkdir(parents=True)

        return dist_path


    def test_dist_instance(instance_path: str) -> Path:
        dist_path: Path = args.dist_path / instance_path
        if dist_path.exists():
            return dist_path
        else:
            sys.exit(f"Required PGO Pipeline stage directory is missing: {dist_path}")


    #
    # Stage 1: LTO, Static, Section GC, PGO Instrumented
    #

    if args.start <= 1 and 1 <= args.end:
        print("Executing Stage 1")
        dist_path_stage1 = setup_dist_instance("rust-pgo/stage1")
        build.main([
            f"--dist={dist_path_stage1}",
            f"--build-name={args.build_name}-stage1",
            "--lto=thin",
            "--llvm-linkage=static",
            "--gc-sections",
            "--profile-generate",
        ])
    elif args.end > 1:
        dist_path_stage1 = test_dist_instance("rust-pgo/stage1")
        print("Re-using existing Stage 1")

    #
    # Stage 2: Gather profile data
    #

    dist_paths_stage2 = []
    if args.start <= 2 and 2 <= args.end:
        print("Executing Stage 2")
        for short, long in TARGETS.items():
            run_build_command("m clean")
            dist_paths_stage2.append(setup_dist_instance(f"rust-pgo/stage2/{short}"))
            test_compiler.run_test(
                dist_path_stage1,
                f"aosp_{long}-userdebug",
                dist_paths_stage2[-1],
                OUT_PATH_PROFILES,
                None)
    elif args.end < 2:
        sys.exit()
    else:
        dist_paths_stage2 = [test_dist_instance(f"rust-pgo/stage2/{short}") for short in TARGETS.keys()]
        print("Re-using existing Stage 2")

    #
    # Stage 2.5: Merge profiles 1
    #

    if args.start <= 2.5 and 2.5 <= args.end:
        dist_path_merge1 = setup_dist_instance("rust-pgo/stage2.5")
        merge_profiles.merge_project_profiles([
                dist_path_stage1,
                *dist_paths_stage2,
            ],
            dist_path_merge1)

    elif args.end < 2.5:
        sys.exit()
    else:
        dist_path_merge1 = test_dist_instance("rust-pgo/stage2.5")
        print("Re-using existing Stage 2.5")

    #
    # Stage 3: LTO, Static, Section GC, PGO Use, CS-PGO Instrumented
    #

    if args.start <= 3 and 3 <= args.end:
        print("Executing Stage 3")
        dist_path_stage3 = setup_dist_instance("rust-pgo/stage3")
        build.main([
            f"--dist={dist_path_stage3}",
            f"--build-name={args.build_name}-stage3",
            "--lto=thin",
            "--llvm-linkage=static",
            "--gc-sections",
            f"--profile-use={dist_path_merge1}",
            "--cs-profile-generate",
        ])
    elif args.end < 3:
        sys.exit()
    else:
        dist_path_stage3 = test_dist_instance("rust-pgo/stage3")
        print("Re-using existing Stage 3")

    #
    # Stage 4: Gather profile data for aosp_raven-userdebug and cf_x86_64_phone-userdebug
    #

    dist_paths_stage4 = []
    if args.start <= 4 and 4 <= args.end:
        print("Executing Stage 4")
        for short, long in TARGETS.items():
            run_build_command("m clean")
            dist_paths_stage4.append(setup_dist_instance(f"rust-pgo/stage4/{short}"))
            test_compiler.run_test(
                dist_path_stage3,
                f"aosp_{long}-userdebug",
                dist_paths_stage4[-1],
                None,
                OUT_PATH_PROFILES)
    elif args.end < 4:
        sys.exit()
    else:
        dist_paths_stage4 = [test_dist_instance(f"rust-pgo/stage4/{short}") for short in TARGETS.keys()]
        print("Re-using existing Stage 4")

    #
    # Stage 4.5: Merge profiles 2
    #

    if args.start <= 4.5 and 4.5 <= args.end:
        dist_path_merge2 = setup_dist_instance("rust-pgo/stage4.5")
        merge_profiles.merge_project_profiles([
                dist_path_merge1,
                dist_path_stage3,
                *dist_paths_stage4,
            ],
            dist_path_merge2)

    elif args.end < 4.5:
        sys.exit()
    else:
        dist_path_merge2  = test_dist_instance("rust-pgo/stage4.5")
        print("Re-using existing Stage 4.5")

    #
    # Stage 5: LTO, Static, Section GC, PGO Use, BOLT
    #

    if args.start <= 5 and 5 <= args.end:
        print("Executing Stage 5")
        dist_path_stage5 = setup_dist_instance("rust-pgo/stage5")
        build.main([
            f"--dist={dist_path_stage5}",
            f"--build-name={args.build_name}-stage5",
            "--lto=thin",
            "--llvm-linkage=static",
            "--gc-sections",
            f"--profile-use={dist_path_merge2}",
            "--bolt"
        ])


if __name__ == "__main__":
    main()
