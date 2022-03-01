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

import build_platform
from paths import (RUST_PREBUILT_PATH, SOONG_PATH)
from utils import (replace_file_contents, run_quiet_and_exit_on_failure, VERSION_PATTERN)

TEST_VERSION_NUMBER: str = "9.99.9"

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=inspect.getdoc(sys.modules[__name__]))

    parser.add_argument(
        "--prebuilt-path", type=Path, required=True,
        help="Path to either the build artifact or the directory that contains it")
    parser.add_argument(
        "--target", type=str, required=True,
        help="Device target to build for")

    return parser.parse_args()


def main() -> None:
  args = parse_args()

  # Resolve prebuilt path
  prebuilt_archive: Path = args.prebuilt_path
  if prebuilt_archive.exists():
    if prebuilt_archive.is_dir():
      files = list(prebuilt_archive.glob("*"))
      if len(files) != 1:
        raise RuntimeError(f"Expected 1 file in prebuilt path, instead found {len(files)}")

      prebuilt_archive = files.pop()

    prebuilt_archive = prebuilt_archive.resolve()

  else:
    raise RuntimeError(f"Path {args.prebuilt_path} does not exist")

  # Prepare host/version path
  target_and_version_path: Path = RUST_PREBUILT_PATH / build_platform.prebuilt() / TEST_VERSION_NUMBER
  if target_and_version_path.exists():
    print("Test prebuilt directory already exists.  Deleting contents.")
    shutil.rmtree(target_and_version_path, ignore_errors=True)

  target_and_version_path.mkdir()

  # Unpack prebuilt
  print(f"Extracting archive {prebuilt_archive}")
  run_quiet_and_exit_on_failure(
      f"tar -xzf {prebuilt_archive}",
      f"Failed to extract prebuilt archive",
      cwd=target_and_version_path)

  # Run 'm rust && m' for build target
  ENVSETUP_PATH = Path.cwd() / "build" / "envsetup.sh"
  retcode = subprocess.run(
    f"source {ENVSETUP_PATH} && lunch {args.target} && " +
    f"RUST_PREBUILTS_VERSION={TEST_VERSION_NUMBER} m rust && m",
    shell=True, stderr=subprocess.STDOUT)

  sys.exit(retcode)

if __name__ == "__main__":
    main()
