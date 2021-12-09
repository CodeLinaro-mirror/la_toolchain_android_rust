#
# Copyright (C) 2021 The Android Open Source Project
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

"""
Package to manage Rust source files when building a toolchain distributable.
"""

from pathlib import Path
import shutil
import subprocess
import sys

import build_platform
from paths import OUT_PATH_PATCHS_LOG
from utils import prepare_command, run_quiet_and_exit_on_failure, run_quiet

def apply_patches(code_dir: Path, patch_dir: Path, no_patch_abort: bool = False) -> None:
    patch_list    = sorted(patch_dir.glob("rustc-*"))
    count_padding = len(str(len(patch_list)))

    # We will overwrite the log file if it already existed.
    with OUT_PATH_PATCHS_LOG.open("w") as f:
        for idx, filepath in enumerate(patch_list):
            print("\33[2K\rApplying patch ({cur:>{width}}/{total}): {name}".format(
                    cur=(idx + 1), width=count_padding, total=len(patch_list), name=filepath.name),
                end="")

            command_list: list[str] = prepare_command(f"patch -p1 -N -r - -i {filepath}")
            # We collect the stdout and stderr output and then print it to the
            # log so that when an error is encountered we can display the
            # relevent message and don't have to refer the user to the log.
            # The log is intended as a resource for investigating patch
            # drift.
            result = subprocess.run(command_list, cwd=code_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            if result.stdout or result.stderr:
                f.write(f"Patch {filepath.name}:\n")
                if result.stdout:
                    f.write(result.stdout.decode("UTF-8") + "\n")
                if result.stderr:
                    f.write(result.stderr.decode("UTF-8") + "\n")

            if result.returncode != 0 and not no_patch_abort:
                print(f"\nBuild failed when applying patch {filepath}")
                print("If developing locally, try the --no-patch-abort flag")
                if result.stdout:
                    print("\nOutput (stdout):")
                    print(result.stdout.decode("UTF-8"))
                if result.stderr:
                    print("\nOutput (stderr):")
                    print(result.stderr.decode("UTF-8"))

                print("Failed")

                f.truncate()
                sys.exit(result.returncode)

        # Remove any possible leftovers from the previous log
        f.truncate()

    # If all patches applied cleanly we need to advance to the next line in the
    # terminal
    print()


def setup_files(input_dir: Path, output_dir: Path, patches_dir: Path, no_patch_abort: bool = False) -> None:
    """Copy source and apply patches in a performant and fault-tolerant manner.

    This function creates a copy-on-write mirror of the source directory and
    applies the patches contained in the patch directory.  If the patches apply
    cleanly then the mirror is renamed to the output directory.
    """

    # Calculate the name of the temporary directory and remove any stale files
    # if they exist.
    tmp_output_dir = output_dir.parent / (output_dir.name + '.tmp')
    if tmp_output_dir.exists():
        shutil.rmtree(tmp_output_dir)

    # Create parent of tmp_source_dir if necessary - so we can call 'cp' below.
    if not tmp_output_dir.parent.exists():
        tmp_output_dir.parent.mkdir(parents=True)

    print("Creating copy of Rust source")

    # Use 'cp' instead of shutil.copytree.  The latter uses copystat and retains
    # timestamps from the source.  We instead use rsync below to only update
    # changed files into source_dir.  Using 'cp' will ensure all changed files
    # get a newer timestamp than files in $source_dir.
    #
    # Note: Darwin builds don't copy symlinks with -r.  Use -R instead.
    command_template = f"cp -Rf %s {input_dir} {tmp_output_dir}"
    reflink          = '--reflink=auto' if build_platform.is_linux() else '-c'
    try:
        run_quiet(command_template % reflink, check=True)
    except subprocess.CalledProcessError:
        # Fallback to normal copy.
        run_quiet_and_exit_on_failure(
            command_template % "",
            f"Failed to copy source to temporary output path {tmp_output_dir}")

    # Patch source tree
    apply_patches(tmp_output_dir, patches_dir, no_patch_abort=no_patch_abort)

    # Copy tmp_output_dir to output_dir if they are different.  This avoids
    # invalidating prior build outputs.
    if not output_dir.exists():
        print('Re-naming temporary output directory')
        tmp_output_dir.rename(output_dir)
    else:
        print('Synchronizing temporary directory with existing output directory')
        # Without a trailing '/' in $SRC, rsync copies $SRC to
        # $DST/BASENAME($SRC) instead of $DST.
        tmp_output_dir_w_trailing_slash = str(tmp_output_dir) + '/'

        # rsync to update only changed files.  Use '-c' to use checksums to find
        # if files have changed instead of only modification time and size -
        # which could have inconsistencies.  Use '--delete' to ensure files not
        # in tmp_source_dir are deleted from $source_dir.
        run_quiet_and_exit_on_failure(
            f"rsync -r --delete --links -c {tmp_output_dir_w_trailing_slash} {output_dir}",
            f"Failed to synchronize temporary ({tmp_output_dir}) and persistant ({output_dir}) output directories")

        shutil.rmtree(tmp_output_dir)
