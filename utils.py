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

"""Code common to different scripts in the Rust toolchain"""


import argparse
from pathlib import Path
import re
import shlex
import shutil
import sys
import subprocess
from typing import Any, TextIO, Union, cast

from paths import DIST_PATH, PROFDATA_PATH

GIT_REFERENCE_BRANCH = "aosp/master"

SUBPROCESS_RUN_QUIET_DEFAULTS: dict[str, object] = {
    'stdout': subprocess.DEVNULL,
    'stderr': subprocess.DEVNULL,
}

VERSION_PATTERN = re.compile("\d+\.\d+\.\d+(p\d+)?")

#
# Type Functions
#

def version_string_type(arg_string: str) -> str:
    if VERSION_PATTERN.match(arg_string):
        return arg_string
    else:
        raise argparse.ArgumentTypeError("Version string is not properly formatted")


def ResolvedPath(arg: str) -> Path:
    return Path(arg).resolve()

#
# Subprocess helpers
#

def prepare_command(command: Union[str, list[Any]]) -> list[str]:
    if isinstance(command, list):
        command_list: list[str] = [str(obj) for obj in command]
    else:
        command_list = shlex.split(command)

    if not Path(command_list[0]).exists():
        resolved_executable = shutil.which(command_list[0])
        if resolved_executable:
            command_list[0] = resolved_executable
        else:
            raise RuntimeError(f"Unable to find executable {command_list[0]}")

    return command_list


def run_and_exit_on_failure(command: Union[str, list[Any]], error_message: str, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Runs a command where failure is a valid outcome"""
    command = prepare_command(command) if not kwargs.get("shell") else command
    result  = subprocess.run(command, *args, **kwargs)
    if result.returncode != 0:
        sys.exit(error_message)

    return result


def run_quiet_and_exit_on_failure(command: Union[str, list[Any]], error_message: str, *args: Any, **kwargs: Any) -> int:
    """Runs a failable command with stdout and stderr directed to /dev/null"""
    return run_and_exit_on_failure(command, error_message, *args, **(kwargs | SUBPROCESS_RUN_QUIET_DEFAULTS)).returncode


def run_quiet(command: Union[str, list[Any]], *args: Any, **kwargs: Any) -> int:
    return subprocess.run(prepare_command(command), *args, **cast(Any,(kwargs | SUBPROCESS_RUN_QUIET_DEFAULTS))).returncode

#
# Git
#

class GitRepo:
    COMMAND_GIT_BRANCH_TEST: str = "git rev-parse --verify %s"

    def __init__(self, repo_path: Path) -> None:
        self.path = repo_path

    def add(self, *patterns: Union[str, Path]) -> None:
        pattern = " ".join([str(p) for p in patterns])
        run_quiet_and_exit_on_failure(
            f"git add {pattern}",
            "Failed to add files matching pattern(s) '%s' to Git repo %s" %
                (pattern, self.path),
            cwd=self.path)

    def amend(self) -> None:
        run_quiet_and_exit_on_failure(
            "git commit --amend --no-edit",
            "Failed to amend previous commit for Git repo %s" % self.path,
            cwd=self.path)

    def amend_or_commit(self, commit_message: str) -> None:
        if not self.diff():
            print("No files updated")
        elif (self.branch_target() !=
              self.branch_target(GIT_REFERENCE_BRANCH)):

            print("Amending previous commit")
            self.amend()
        else:
            print("Committing new files")
            self.commit(commit_message)

    def branch_exists(self, branch_name: str) -> bool:
        return run_quiet(self.COMMAND_GIT_BRANCH_TEST % branch_name, cwd=self.path) == 0

    def branch_target(self, branch_name: str = "HEAD") -> str:
        return run_and_exit_on_failure(
            self.COMMAND_GIT_BRANCH_TEST % branch_name,
            f"Failed to get target hash for branch '{branch_name}' of Git repo {self.path}",
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL).stdout.rstrip()

    def checkout(self, branch_name: str) -> None:
        run_quiet_and_exit_on_failure(
            f"git checkout {branch_name}",
            f"Failed to checkout branch '{branch_name}' for Git repo {self.path}",
            cwd=self.path)

    def commit(self, message: str) -> None:
        run_quiet_and_exit_on_failure(
            f"git commit --no-verify -m '{message}'",
            f"Failed to create commit for Git repo {self.path}",
            cwd=self.path)

    def create_or_checkout(self, branch_name: str, overwrite: bool) -> bool:
        """Create or checkout a branch, returning true if a new branch was created"""
        if self.branch_exists(branch_name):
            if overwrite:
                print(f"Checking out branch {branch_name}")
                self.checkout(branch_name)
                return False
            else:
                sys.exit(f"Branch {branch_name} already exists and the 'overwrite' option was not set")
        else:
            print("Creating branch %s" % branch_name)
            repo_start(self.path, branch_name)
            return True

    def diff(self) -> bool:
        retcode = run_quiet("git diff --cached --quiet", cwd=self.path)

        if retcode == 0:
            return False
        elif retcode == 1:
            return True
        else:
            sys.exit("Failed to compute diff for Git repo {self.path}")


    def rm(self, *patterns: Union[str, Path], options: str ="frq") -> None:
        pattern = " ".join([str(p) for p in patterns])
        run_quiet_and_exit_on_failure(
            f"git rm -{options} {pattern}",
            f"Failed to remove files matching pattern(s) '{pattern}' from Git repo {self.path}",
            cwd=self.path)

#
# Repo helper
#

def repo_start(path: Path, branch_name: str) -> None:
    run_quiet_and_exit_on_failure(
        f"repo start {branch_name}",
        f"Failed to 'repo init' branch '{path}' for Git repo {branch_name}",
        cwd=path)

#
# File helpers
#

def replace_file_contents(f: TextIO, new_contents: str) -> None:
    f.seek(0)
    f.write(new_contents)
    f.truncate()
    f.flush()

#
# LLVM tool helpers
#

def profdate_merge(inputs: list[Path], outpath: Path) -> None:
    run_and_exit_on_failure(
        f"{PROFDATA_PATH} merge -o {outpath} {' '.join([p.as_posix() for p in inputs])}",
        f"Failed to produce merged profile {outpath}")


def export_profile(indir: Path, outname: str) -> None:
    profdate_merge(list(indir.glob("*.profraw")), DIST_PATH / outname)
