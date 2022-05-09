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
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Optional, TextIO

from paths import *
from utils import (
    ResolvedPath,
    extend_suffix,
    get_prebuilt_binary_paths,
    reify_singleton_patterns,
    run_and_exit_on_failure,
    strip_symbols)

#
# Constants
#

BOLT_INSTRUMENTATION_SUBJECTS: list[str] = [
    "lib/librustc_driver-*.so",
    "lib/libstd-*.so",
    "lib/libLLVM-*.so",
]

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    """Parses arguments and returns the parsed structure."""
    parser = argparse.ArgumentParser("Run BOLT on a Rust toolchain archive")
    parser.add_argument(
        "archive_path", type=ResolvedPath,
        help="Release name for the dist result")

    parser.add_argument(
        "outname",
        help="Desired filename for the output archive (w/o extension)")

    parser.add_argument(
        "--dist", "-d", dest="dist_path", type=ResolvedPath, default=DIST_PATH_DEFAULT,
        help="Where to place distributable artifacts")

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--profile-generate", type=ResolvedPath, nargs="?", const=OUT_PATH_PROFILES,
        help="Instrument the toolchain for BOLT profile generation")
    action_group.add_argument(
        "--profile-use", type=ResolvedPath, nargs="?", const=OUT_PATH_PROFILES,
        help="Use the provided profile when optimizing the toolchain")

    return parser.parse_args()


def unpack_archive(archive_path: Path) -> TemporaryDirectory[str]:
    tmpdir = TemporaryDirectory()
    print(f"Unpacking archive into {tmpdir.name}")
    shutil.unpack_archive(archive_path.as_posix(), tmpdir.name)
    return tmpdir


def invoke_bolt(obj_path: Path, bolt_log: TextIO, options: str = "") -> None:
    obj_path_bolted = extend_suffix(obj_path, ".bolt")

    bolt_log.write(f"BOLTing {obj_path.as_posix()}\n")
    bolt_log.flush()
    run_and_exit_on_failure(
        f"{BOLT_PATH} {options} -o {obj_path_bolted} {obj_path}",
        f"Failed to generate BOLTed binary for {obj_path}",
        stdout=bolt_log, stderr=subprocess.STDOUT)

    bolt_log.write("\n")
    bolt_log.flush()

    obj_path.unlink()
    obj_path_bolted.rename(obj_path)


def process_objects(root: Path, profile_generate: Optional[Path], profile_use: Optional[Path], bolt_log: TextIO) -> None:
    print("Processing objects")

    instrumentation_subjects = reify_singleton_patterns(root, BOLT_INSTRUMENTATION_SUBJECTS)
    optimization_subjects    = get_prebuilt_binary_paths(root, toplevel_only=True)

    for obj_path in get_prebuilt_binary_paths(root):
        if obj_path in optimization_subjects:
            options = ["--peepholes=all"]
            if obj_path in instrumentation_subjects:
                if profile_generate:
                    fdata_path  = profile_generate / PROFILE_SUBDIR_BOLT / obj_path.name
                    options += [
                        "--instrument",
                        f"--instrumentation-file={fdata_path}",
                        "--instrumentation-file-append-pid",
                    ]

                elif profile_use:
                    fdata_path = profile_use / PROFILE_SUBDIR_BOLT / (obj_path.name + ".fdata")
                    options += [
                        f"--data={fdata_path}",
                        "--reorder-blocks=cache+",
                        "--reorder-functions=hfsort",
                        "--split-functions=2",
                        "--split-all-cold",
                        "--split-eh",
                        "--dyno-stats",
                    ]

            invoke_bolt(obj_path, bolt_log, " ".join(options))

        else:
            strip_symbols(obj_path)


def pack_archive(srcdir: str, outpath: Path) -> None:
    print(f"Creating BOLTed archive")
    shutil.make_archive(outpath.as_posix(), "gztar", srcdir)


def main() -> None:
    args = parse_args()

    with BOLT_LOG_PATH.open("w") as bolt_log:
        with unpack_archive(args.archive_path) as tmpdir:
            process_objects(Path(tmpdir), args.profile_generate, args.profile_use, bolt_log)
            pack_archive(tmpdir, args.dist_path / f"rust-{args.outname}")


if __name__ == "__main__":
    main()
