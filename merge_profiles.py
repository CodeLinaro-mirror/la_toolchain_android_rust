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

"""Merge profiles from multiple Rust toolchain build targets"""


import argparse
from pathlib import Path

from paths import DIST_PATH_DEFAULT, PROFILE_NAME_LLVM, PROFILE_NAME_LLVM_CS, PROFILE_NAME_RUST
from utils import ResolvedPath, profdata_merge

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Merge profiles from multiple Rust toolchain build targets")
    parser.add_argument(
        "indirs", type=ResolvedPath, nargs="+",
        help="Root directory for finding llvm.profdata, llvm-cs.profdata, and rust.profdata files")
    parser.add_argument(
        "--dist", "-d", dest="dist_path", type=ResolvedPath, default=DIST_PATH_DEFAULT,
        help="Where to place distributable artifacts")

    return parser.parse_args()


def merge_profiles(indirs: list[Path], input_names: list[str], outpath: Path) -> None:
    inputs: list[Path] = []
    for indir in indirs:
        for name in input_names:
            inputs += indir.glob(f"**/{name}")

    if inputs:
        profdata_merge(inputs, outpath)


def merge_project_profiles(indirs: list[Path], outdir: Path) -> None:
    merge_profiles(indirs, [PROFILE_NAME_LLVM, PROFILE_NAME_LLVM_CS], outdir / PROFILE_NAME_LLVM)
    merge_profiles(indirs, [PROFILE_NAME_RUST], outdir / PROFILE_NAME_RUST)


def main() -> None:
    args = parse_args()

    args.dist_path.mkdir(exist_ok=True)
    merge_project_profiles(args.indirs, args.dist_path)


if __name__ == "__main__":
    main()
