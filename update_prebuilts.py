#!/usr/bin/env python3
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

"""Fetch prebuilt archives and prepare a prebuilt commit"""

import argparse
import inspect
from functools import cache
from pathlib import Path
import os
import re
import shutil
import sys
from typing import KeysView, Optional, Union

import build_platform
from paths import (
    DOWNLOADS_PATH,
    FETCH_ARTIFACT_PATH,
    RUST_PREBUILT_PATH,
    SOONG_PATH
)
from utils import (
    GitRepo,
    replace_file_contents,
    run_and_exit_on_failure,
    run_quiet,
    run_quiet_and_exit_on_failure,
    VERSION_PATTERN,
    version_string_type,
)


ANDROID_BP: str = "Android.bp"

BRANCH_NAME_TEMPLATE: str = "rust-update-prebuilts-%s"

BUILD_SERVER_ARCHIVE_PATTERN: str = "rust-%s.tar.gz"
BUILD_SERVER_TARGET_DEFAULT:  str = "linux"
BUILD_SERVER_TARGET_MAP: dict[str, str] = {
  "darwin-x86": "darwin_mac",
  "linux-x86":  "linux"}

HOST_ARCHIVE_PATTERN: str = "rust-%s-%s.tar.gz"
HOST_TARGET_DEFAULT:  str = "linux-x86"

RLIB_NAME_PATTERN: re.Pattern[str] = re.compile("libstd-([a-zA-z\d]+)\.rlib")

RUST_PREBUILT_REPO: GitRepo = GitRepo(RUST_PREBUILT_PATH)
SOONG_REPO: GitRepo = GitRepo(SOONG_PATH)

#
# String operations
#

def artifact_ident_type(arg: str) -> Union[int, Path]:
    try:
        return int(arg)
    except (SyntaxError, ValueError):
        return Path(arg).resolve()


def make_branch_name(version: str, is_local: bool) -> str:
    branch_name = BRANCH_NAME_TEMPLATE % version
    if is_local:
        branch_name += "-local"
    return branch_name


def make_commit_message(version: str, prebuilt_ident: Union[int, Path], issue: Optional[int]) -> str:
    commit_message: str = f"rustc-{version}"
    if isinstance(prebuilt_ident, int):
        commit_message += f" Build {prebuilt_ident}\n"
    else:
        commit_message += " Local Build\n"

    if issue is not None:
        commit_message += f"\nBug: https://issuetracker.google.com/issues/{issue}"

    commit_message += "\nTest: m rust"

    return commit_message

#
# Google3 wrappers
#

@cache
def ensure_gcert_valid() -> None:
    """Ensure gcert valid for > 1 hour."""
    if run_quiet("gcertstatus -quiet -check_ssh=false -check_remaining=1h") < 0:
        run_and_exit_on_failure("gcert", "Failed to obtain authentication credentials")


def fetch_build_server_artifact(target: str, build_id: int, build_server_name: str,
    host_name: Optional[str] = None) -> Path:

    host_name = host_name or build_server_name
    DOWNLOADS_PATH.mkdir(exist_ok=True)
    dest: Path = DOWNLOADS_PATH / host_name

    if dest.exists():
        print(f"Artifact {build_server_name} for {target} has already been downloaded as {host_name}")

    else:
        ensure_gcert_valid()

        print(f"Downloading build server artifact {build_server_name} for target {target}")
        run_and_exit_on_failure(
            f"{FETCH_ARTIFACT_PATH} --target={target} --bid={build_id} {build_server_name} {dest}",
            f"Failed to fetch build server artifact {build_server_name} for target {target}")

    return dest

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=inspect.getdoc(sys.modules[__name__]))

    parser.add_argument(
        "prebuilt_ident", metavar="IDENT", type=artifact_ident_type,
        help="Build number to pull from the server or path to archive")
    parser.add_argument(
        "version", metavar="VERSION", type=version_string_type,
        help="Rust version string (e.g. 1.55.0)")

    parser.add_argument(
        "-b", "--branch", metavar="NAME", dest="branch",
        help="Branch name to use for this prebuilt update")
    parser.add_argument(
        "-i", "--issue", "--bug", metavar="NUMBER", dest="issue", type=int,
        help="Issue number to include in commit message")
    parser.add_argument(
        "-o", "--overwrite", dest="overwrite", action="store_true",
        help="Overwrite the target branch if it exists")

    return parser.parse_args()


def prepare_prebuilt_artifact(ident: Union[int, Path]) -> tuple[dict[str, Path], Optional[Path]]:
    """
    Returns a dictionary that maps target names to prebuilt artifact paths.  If
    the artifacts were downloaded from a build server the manifest for the
    build is returned as the second element of the tuple.
    """

    if isinstance(ident, Path):
        if ident.exists():
            return ({build_platform.prebuilt(): ident}, None)
        else:
            sys.exit(f"Provided prebuilt archive does not exist: {ident.as_posix()}")
    else:
        artifact_path_map: dict[str, Path] = {}

        manifest_name:       str = f"manifest_{ident}.xml"
        bs_archive_name:     str = BUILD_SERVER_ARCHIVE_PATTERN % ident
        host_manifest_path: Path = fetch_build_server_artifact(BUILD_SERVER_TARGET_DEFAULT, ident, manifest_name)

        for target, bs_target in BUILD_SERVER_TARGET_MAP.items():
            artifact_path_map[target] = fetch_build_server_artifact(
                bs_target, ident, bs_archive_name, HOST_ARCHIVE_PATTERN % (ident, target))

        # Print a newline to make the fetch/cache usage visually distinct
        print()
        return (artifact_path_map, host_manifest_path)


def unpack_prebuilt_artifacts(artifact_path_map: dict[str, Path], manifest_path: Optional[Path],
    version: str, overwrite: bool) -> None:

    """
    Use the provided target-to-artifact path map to extract the provided
    archives into the appropriate directories.  If a manifest is present it
    will be copied into the host target / version path.
    """

    for target, artifact_path in artifact_path_map.items():
        target_and_version_path: Path = RUST_PREBUILT_PATH / target / version
        if target_and_version_path.exists():
            if overwrite:
                # Empty out the existing directory so we can overwrite the contents
                RUST_PREBUILT_REPO.rm(target_and_version_path / '*')
            else:
                print(f"Directory {target_and_version_path} already exists and the 'overwrite' option was not set")
                exit(-1)
        else:
            target_and_version_path.mkdir()

        print(f"Extracting archive {artifact_path.name} for {target}/{version}")
        run_quiet_and_exit_on_failure(
            f"tar -xzf {artifact_path}",
            f"Failed to extract prebuilt artifact for {target}/{version}",
            cwd=target_and_version_path)

        if manifest_path and target == HOST_TARGET_DEFAULT:
            shutil.copy(manifest_path, target_and_version_path)

        RUST_PREBUILT_REPO.add(target_and_version_path)


def update_symlink(targets: KeysView[str], version: str) -> None:
    """Update the symlinks in the stable directory when we update a target"""

    STABLE_BINARIES = [
        "rust-analyzer",
        "rustfmt"
    ]

    print("Updating stable symlinks")
    for target in targets:
        stable_root_path: Path = RUST_PREBUILT_PATH / target / "stable"
        for binary in STABLE_BINARIES:
            stable_bin_path = stable_root_path / binary
            stable_bin_path.unlink()
            version_bin_path = RUST_PREBUILT_PATH / target / version / "bin" / binary
            # os.path.relpath() is used here because pathlib.Path.relative_to()
            # requires that one path be a subcomponent of the other.
            stable_bin_path.symlink_to(os.path.relpath(version_bin_path, stable_root_path))


def update_soong(version: str) -> None:
    """Update the Rust version number in Soong"""

    print("Updating Soong's RustDefaultVersion")
    SOONG_GLOBAL_DEF_PATH: Path = SOONG_PATH / "rust" / "config" / "global.go"
    with open(SOONG_GLOBAL_DEF_PATH, "r+") as f:
        replace_file_contents(f, re.sub(VERSION_PATTERN, version, f.read()))

    # Add the file to Git after we are sure it has been written to and closed.
    SOONG_REPO.add(SOONG_GLOBAL_DEF_PATH)
    SOONG_REPO.commit(f"Update `RustDefaultVersion` to {version}")


def main() -> None:
    args = parse_args()
    branch_name: str = args.branch or make_branch_name(args.version, isinstance(args.prebuilt_ident, Path))

    print()
    artifact_path_map, manifest_path = prepare_prebuilt_artifact(args.prebuilt_ident)
    RUST_PREBUILT_REPO.create_or_checkout(branch_name, args.overwrite)
    unpack_prebuilt_artifacts(artifact_path_map, manifest_path, args.version, args.overwrite)
    update_symlink(artifact_path_map.keys(), args.version)
    commit_message = make_commit_message(args.version, args.prebuilt_ident, args.issue)
    RUST_PREBUILT_REPO.amend_or_commit(commit_message)
    update_soong(args.version)
    print("Done")

    sys.exit(0)


if __name__ == "__main__":
    main()