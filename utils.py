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
from typing import Any, TextIO, Union


GIT_REFERENCE_BRANCH = "aosp/master"

SUBPROCESS_RUN_QUIET_DEFAULTS: dict[str, object] = {
    'stdout': subprocess.DEVNULL,
    'stderr': subprocess.DEVNULL,
}

VERSION_PATTERN = re.compile("\d+\.\d+\.\d+")

#
# Type Functions
#

def version_string_type(arg_string: str) -> str:
    if VERSION_PATTERN.match(arg_string):
        return arg_string
    else:
        raise argparse.ArgumentTypeError("Version string is not properly formatted")

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
    return subprocess.run(prepare_command(command), *args, **(kwargs | SUBPROCESS_RUN_QUIET_DEFAULTS)).returncode

#
# Git
#

class GitRepo:
    COMMAND_GIT_BRANCH_TEST: str = "git rev-parse --verify %s"

    def __init__(self, repo_path: Path) -> None:
        self.path = repo_path

    def add(self, pattern: Union[str, Path]='.') -> None:
        run_quiet_and_exit_on_failure(
            f"git add {pattern}",
            "Failed to add files matching pattern '%s' to Git repo %s" %
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
            "Failed to get target hash for branch '%s' of Git repo %s" %
                (branch_name, self.path),
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL).stdout.rstrip()

    def checkout(self, branch_name: str) -> None:
        run_quiet_and_exit_on_failure(
            f"git checkout {branch_name}",
            "Failed to checkout branch '%s' for Git repo %s" %
                (branch_name, self.path),
            cwd=self.path)

    def commit(self, message: str) -> None:
        run_quiet_and_exit_on_failure(
            f"git commit --no-verify -m '{message}'",
            "Failed to create commit for Git repo %s" % self.path,
            cwd=self.path)

    def create_or_checkout(self, branch_name: str, overwrite: bool) -> bool:
        """Create or checkout a branch, returning true if a new branch was created"""
        if self.branch_exists(branch_name):
            if overwrite:
                print("Checking out branch %s" % branch_name)
                self.checkout(branch_name)
                return False
            else:
                print("Branch %s already exists and the 'overwrite' option was not set" % branch_name)
                exit(-1)
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
            "Failed to compute diff for Git repo %s" % self.path
            exit(-1)


    def rm(self, pattern: Union[str, Path]) -> None:
        run_quiet_and_exit_on_failure(
            f"git rm -fr {pattern}",
            "Failed to remove files matching pattern '%s' from Git repo %s" %
                (pattern, self.path),
            cwd=self.path)

#
# Repo helper
#

def repo_start(path: Path, branch_name: str) -> None:
    run_quiet_and_exit_on_failure(
        f"repo start {branch_name}",
        "Failed to 'repo init' branch '%s' for Git repo %s" % (path, branch_name),
        cwd=path)
