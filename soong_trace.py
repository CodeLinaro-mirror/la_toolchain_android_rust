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
import gzip
import json
from pathlib import Path
from typing import Tuple

from utils import ResolvedPath

TIME_MS_IN_SECOND = 1000
TIME_MS_IN_MINUTE = TIME_MS_IN_SECOND * 60
TIME_MS_IN_HOUR   = TIME_MS_IN_MINUTE * 60
TIME_MS_IN_DAY    = TIME_MS_IN_HOUR * 24

#
# Helper functions
#

def open_trace(trace_path: Path) -> str:
  if not trace_path.exists():
    print(f"Trace file does not exist: {trace_path.as_posix()}")
    exit(-1)

  if trace_path.suffix == ".gz":
    return gzip.open(trace_path, mode="rt")
  else:
    return open(trace_path, mode="r")


def ms_to_hms(milliseconds: int) -> Tuple[int, int, int]:
  seconds = (milliseconds /  TIME_MS_IN_SECOND) % 60
  minutes = (milliseconds // TIME_MS_IN_MINUTE) % 60
  hours   = (milliseconds // TIME_MS_IN_HOUR) % 24
  days    = (milliseconds // TIME_MS_IN_DAY)

  return (days, hours, minutes, seconds)

#
# Program logic
#


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
      description="Produce a summary of Rust-related information from a Soong build trace")

    parser.add_argument("trace", metavar="TRACE", type=ResolvedPath, help="Soong trace file to process")

    return parser.parse_args()


def main() -> None:
  args = parse_args()

  with open_trace(args.trace) as fd:
    trace = json.load(fd)
    rust_targets  = 0
    rust_duration = 0

    for item in trace:
      if "dur" in item:
        name = item["name"]
        if name.endswith(".rs") or name.endswith(".rlib") or name.endswith(".dylib.so"):
          rust_targets  += 1
          rust_duration += item["dur"]

    dur_parts = ms_to_hms(rust_duration)

    print(f"Total Rust targets: {rust_targets}")
    print(f"Total Rust duration (ms): {rust_duration}")
    print(f"Total Rust duration (dd hh:mm:ss.ms): {dur_parts[0]} {dur_parts[1]}:{dur_parts[2]}:{dur_parts[3]:02.2f}")
    print()


if __name__ == '__main__':
    main()