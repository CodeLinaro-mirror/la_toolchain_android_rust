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

from paths import PROFILE_NAME_LLVM, PROFILE_NAME_LLVM_CS, PROFILE_NAME_RUST, PROFDATA_PATH
from utils import ResolvedPath, run_and_exit_on_failure

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Merge profiles from multiple Rust toolchain build targets")
    parser.add_argument(
        "indir", type=ResolvedPath,
        help="Root directory for finding llvm.profdata, llvm-cs.profdata, and rust.profdata files")
    parser.add_argument(
        "outdir", type=Path,
        help="Where to write the combined files")

    return parser.parse_args()


def merge_profiles(indir: Path, input_names: list[str], outpath: Path) -> None:
    inputs: list[str] = []
    for name in input_names:
        inputs += [p.as_posix() for p in indir.glob(f"**/{name}")]

    run_and_exit_on_failure(
        f"{PROFDATA_PATH} merge -o {outpath} {' '.join(inputs)}",
        f"Failed to produce output {outpath}")


def main() -> None:
    args = parse_args()

    args.outdir.mkdir(exist_ok=True)

    merge_profiles(args.indir, [PROFILE_NAME_LLVM, PROFILE_NAME_LLVM_CS], args.outdir / PROFILE_NAME_LLVM)
    merge_profiles(args.indir, [PROFILE_NAME_RUST], args.outdir / PROFILE_NAME_RUST)


if __name__ == "__main__":
    main()
