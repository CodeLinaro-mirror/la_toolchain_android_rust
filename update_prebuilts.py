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

"""Fetch prebuilt artifacts and prepare a prebuilt commit"""

import argparse
import inspect
from functools import cache
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
from typing import KeysView, Optional, Union

from paths import (
    ANDROID_BUILD_CLI_PATH,
    BUILD_COMMAND_RECORD_NAME,
    DOWNLOADS_PATH,
    FETCH_ARTIFACT_PATH,
    PROFILE_NAMES,
    RUST_PREBUILT_PATH,
    SOONG_PATH,
    TOOLCHAIN_ARTIFACTS_PATH,
    TOOLCHAIN_PATH
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

BUILD_SERVER_BRANCH: str = "aosp-rust-toolchain"
BUILD_SERVER_ARCHIVE_FORMAT_PATTERN: str = "rust-%s.tar.gz"

HOST_ARCHIVE_PATTERN: str = "rust-%s-%s.tar.gz"
HOST_TARGET_DEFAULT:  str = "linux-x86"

TOOLCHAIN_PATHS_SEARCH_PATTERN = 'RUST_VERSION_STAGE0:\s+str\s+=\s"[^"]+"'
TOOLCHAIN_PATHS_UPDATE_PATTERN = 'RUST_VERSION_STAGE0: str = "%s"'

RUST_PREBUILT_REPO = GitRepo(RUST_PREBUILT_PATH)
SOONG_REPO         = GitRepo(SOONG_PATH)
TOOLCHAIN_REPO     = GitRepo(TOOLCHAIN_PATH)

#
# String operations
#

def add_extension_prefix(filename: str, extension_prefix: str) -> str:
    comps = filename.split(".", 1)
    comps.insert(1, extension_prefix)
    return ".".join(comps)


def artifact_ident_type(arg: str) -> Union[int, Path]:
    try:
        return int(arg)
    except (SyntaxError, ValueError):
        return Path(arg).resolve()


def make_branch_name(version: str) -> str:
    return BRANCH_NAME_TEMPLATE % version


def make_commit_message(version: str, bid: int, issue: Optional[int]) -> str:
    commit_message: str = f"rustc-{version} Build {bid}\n"

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


def fetch_build_server_artifact(target: str, build_id: int, build_server_pattern: str,
                                host_name: str, strict: bool = False) -> Optional[Path]:

    dest: Path = DOWNLOADS_PATH / host_name

    if dest.exists():
        print(f"Artifact {build_server_pattern} for {target} has already been downloaded as {host_name}")

    else:
        ensure_gcert_valid()

        print(f"Downloading build server artifact {build_server_pattern} for target {target}")

        build_flag = f"--bid={build_id}" if build_id else "--latest"
        result = subprocess.run([
            FETCH_ARTIFACT_PATH,
            f"--branch={BUILD_SERVER_BRANCH}",
            f"--target={target}",
            build_flag,
            build_server_pattern,
            dest],
            stderr=(None if strict else subprocess.DEVNULL))

        if result.returncode != 0:
            if strict:
                sys.exit(f"Failed to fetch build server artifact {build_server_pattern} for target {target}")
            else:
                print(f"No file found on build server matching pattern {build_server_pattern}")
                return None

    return dest


def get_lkgb() -> int:
    ensure_gcert_valid()

    result = subprocess.run([
        ANDROID_BUILD_CLI_PATH,
        "lkgb",
        f"--branch={BUILD_SERVER_BRANCH}",
        "--raw",
        "--custom_raw_format='{o[buildId]}'"
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL)

    if result.returncode == 0:
        bids = set([int(t.strip("'")) for t in result.stdout.decode().strip().split("\n")])

        if len(bids) == 1:
            bid = list(bids)[0]
            print(f"Last Known Good Build: {bid}")
            return bid
        else:
            sys.exit("At least one target is broken; a fully green build is required to update prebuilts")
    else:
        sys.exit("Unable to fetch LKGB build ID")

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=inspect.getdoc(sys.modules[__name__]))
    parser.add_argument(
        "version", metavar="VERSION", type=version_string_type,
        help="Rust version string (e.g. 1.55.0)")

    parser.add_argument(
        "--bid", "-b", metavar="BUILD_ID", type=int,
        help="Build ID to use when fetching artifacts from the build servers")
    parser.add_argument(
        "--download-only", "-d", action="store_true",
        help="Stop after downloading the artifacts")
    parser.add_argument(
        "--chained", "-c", action="store_true",
        help="Fetch the profile optimized version of the Linux perbuilts")
    parser.add_argument(
        "--branch", metavar="NAME", dest="branch",
        help="Branch name to use for this prebuilt update")
    parser.add_argument(
        "--issue", "--bug", "-i", metavar="NUMBER", dest="issue", type=int,
        help="Issue number to include in commit message")
    parser.add_argument(
        "--overwrite", "-o", dest="overwrite", action="store_true",
        help="Overwrite the target branch if it exists")

    return parser.parse_args()


def fetch_prebuilt_artifacts(bid: int, chained: bool) -> tuple[dict[str, Path], Path, list[Path]]:
    """
    Returns a dictionary that maps target names to prebuilt artifact paths, the
    manifest used by the build server, and a list of other build server
    artifacts.
    """

    DOWNLOADS_PATH.mkdir(exist_ok=True)

    prebuilt_path_map: dict[str, Path] = {}
    other_artifacts:   list[Path]      = []

    bs_target_default = "rustc-chained" if chained else "linux"
    bs_archive_name   = BUILD_SERVER_ARCHIVE_FORMAT_PATTERN % bid

    build_server_target_map: dict[str, str] = {
        "darwin-x86": "darwin_mac",
        "linux-x86":  bs_target_default}

    # Fetch the host-specific prebuilt archives and build commands
    for host_target, bs_target in build_server_target_map.items():
        host_archive_name = HOST_ARCHIVE_PATTERN % (bid, host_target if not chained else f"{host_target}-chained")
        prebuilt_path_map[host_target] = fetch_build_server_artifact(
            bs_target, bid, bs_archive_name, host_archive_name, strict=True)

        host_build_command_record_name = add_extension_prefix(BUILD_COMMAND_RECORD_NAME, f"{host_target}.{bid}")
        other_artifacts.append(
            fetch_build_server_artifact(
                bs_target, bid, BUILD_COMMAND_RECORD_NAME, host_build_command_record_name, strict=True))

    # Fetch the manifest
    manifest_name: str  = f"manifest_{bid}.xml"
    manifest_path: Path = fetch_build_server_artifact(bs_target_default, bid, manifest_name, manifest_name, strict=True)
    other_artifacts.append(manifest_path)

    # Fetch the profiles
    if chained:
        for profile_name in PROFILE_NAMES:
            profile_path = fetch_build_server_artifact(
                bs_target_default, bid, profile_name, add_extension_prefix(profile_name, str(bid)))

            if profile_path != None:
                other_artifacts.append(profile_path)

    # Print a newline to make the fetch/cache usage visually distinct
    print()
    return (prebuilt_path_map, manifest_path, other_artifacts)


def unpack_prebuilt_artifacts(artifact_path_map: dict[str, Path], manifest_path: Path,
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
                RUST_PREBUILT_REPO.rm(target_and_version_path / "*")
            else:
                sys.exit(f"Directory {target_and_version_path} already exists and the 'overwrite' option was not set")

        # Note: If the target and version path already existed and overwrite
        # was specified then it will have been removed by Git and will need
        # to be re-created.
        target_and_version_path.mkdir()

        print(f"Extracting archive {artifact_path.name} for {target}/{version}")
        run_quiet_and_exit_on_failure(
            f"tar -xzf {artifact_path}",
            f"Failed to extract prebuilt artifact for {target}/{version}",
            cwd=target_and_version_path)

        if target == HOST_TARGET_DEFAULT:
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
            RUST_PREBUILT_REPO.add(stable_bin_path)


def update_prebuilts(branch_name: str, overwrite: bool, version: str, bid: int,
                     issue: Optional[int], prebuilt_path_map: dict[str, Path],
                     manifest_path: Path) -> None:


    RUST_PREBUILT_REPO.create_or_checkout(branch_name, overwrite)
    unpack_prebuilt_artifacts(prebuilt_path_map, manifest_path, version, overwrite)
    update_symlink(prebuilt_path_map.keys(), version)
    commit_message = make_commit_message(version, bid, issue)
    RUST_PREBUILT_REPO.amend_or_commit(commit_message)


def update_toolchain(branch_name: str, overwrite: bool, version: str, bid: int, issue: Optional[int],
                     other_artifacts: list[Path]) -> None:
    TOOLCHAIN_REPO.create_or_checkout(branch_name, overwrite)

    artifact_version_dir = TOOLCHAIN_ARTIFACTS_PATH / version

    # Initialize artifact directory
    if artifact_version_dir.exists():
        if overwrite:
            shutil.rmtree(artifact_version_dir)
        else:
            sys.exit(f"Toolchain artifact directory already exists: {artifact_version_dir}")

    artifact_version_dir.mkdir(exist_ok=True)

    # Copy over:
    #  * Manifest
    #  * Build commands
    #  * Profiles
    for artifact in other_artifacts:
        shutil.copy(artifact, artifact_version_dir)

    # Update paths.py
    paths_file_path = TOOLCHAIN_PATH / "paths.py"
    with open(paths_file_path, "r+") as f:
        replace_file_contents(f, re.sub(TOOLCHAIN_PATHS_SEARCH_PATTERN, TOOLCHAIN_PATHS_UPDATE_PATTERN % version, f.read()))

    TOOLCHAIN_REPO.add(artifact_version_dir)
    TOOLCHAIN_REPO.add(paths_file_path)
    TOOLCHAIN_REPO.commit(make_commit_message(version, bid, issue))


def update_soong(branch_name: str, overwrite: bool, version: str, bid: int, issue: int) -> None:
    """Update the Rust version number in Soong"""

    print("Updating Soong's RustDefaultVersion")
    SOONG_REPO.create_or_checkout(branch_name, overwrite)
    SOONG_GLOBAL_DEF_PATH: Path = SOONG_PATH / "rust" / "config" / "global.go"
    with open(SOONG_GLOBAL_DEF_PATH, "r+") as f:
        replace_file_contents(f, re.sub(VERSION_PATTERN, version, f.read()))

    # Add the file to Git after we are sure it has been written to and closed.
    SOONG_REPO.add(SOONG_GLOBAL_DEF_PATH)
    SOONG_REPO.commit(make_commit_message(version, bid, issue))


def main() -> None:
    args = parse_args()
    branch_name: str = args.branch or make_branch_name(args.version)
    bid: int = args.bid or get_lkgb()

    TOOLCHAIN_ARTIFACTS_PATH.mkdir(exist_ok=True)

    print()

    prebuilt_path_map, manifest_path, other_artifacts = fetch_prebuilt_artifacts(bid, args.chained)
    if not args.download_only:
        update_prebuilts(branch_name, args.overwrite, args.version, bid, args.issue, prebuilt_path_map, manifest_path)
        update_toolchain(branch_name, args.overwrite, args.version, bid, args.issue, other_artifacts)
        update_soong(branch_name, args.overwrite, args.version, bid, args.issue)

    print("Done")


if __name__ == "__main__":
    main()