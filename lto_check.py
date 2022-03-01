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


from pathlib import Path
import subprocess

from paths import OUT_PATH


def is_llvm_ir_file(path: Path) -> bool:
  result = subprocess.run(["file", "-b", path.as_posix()], stdout=subprocess.PIPE)
  return result.stdout.decode("UTF-8").strip() == "LLVM IR bitcode"


def main() -> None:
  print("\nNon LLVM IR files:\n")
  for file_path in sorted(OUT_PATH.glob("rustc/build/**/*.o")):
    if not is_llvm_ir_file(file_path):
      print(file_path.relative_to(OUT_PATH).as_posix())


if __name__ == '__main__':
    main()