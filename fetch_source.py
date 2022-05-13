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


import argparse

from paths import RUST_SOURCE_PATH
import utils

BRANCH_NAME_TEMPLATE: str = "rust-update-source-%s"

COMMAND_FETCH_AND_EXTRACT: str = "curl --proto '=https' --tlsv1.2 -f %s | tar xz --strip-components=1"

COMMIT_MESSAGE: str = "Importing rustc-%s"

RUST_REPO = utils.GitRepo(RUST_SOURCE_PATH)

RUST_SOURCE_URL_VERSION_TEMPLATE: str = "https://static.rust-lang.org/dist/rustc-%s-src.tar.gz"
RUST_SOURCE_URL_BETA            : str = "https://static.rust-lang.org/dist/rustc-beta-src.tar.gz"
RUST_SOURCE_URL_NIGHTLY         : str = "https://static.rust-lang.org/dist/rustc-nightly-src.tar.gz"

#
# String operations
#

def construct_archive_url(build_type: str, rust_version: str) -> str:
    if build_type == 'nightly':
        return RUST_SOURCE_URL_NIGHTLY
    elif build_type == 'beta':
        return RUST_SOURCE_URL_BETA
    else:
        return RUST_SOURCE_URL_VERSION_TEMPLATE % rust_version


def get_extra_tag(build_type: str) -> str:
    if build_type:
        return '-' + build_type
    else:
        return ''


def make_commit_message(version: str, issue: int) -> str:
    commit_message: str = f"Importing rustc-{version}\n"

    if issue:
        commit_message += f"\nBug: {issue}"

    commit_message += "\nTest: ./build.py --lto=thin"

    return commit_message

#
# Program logic
#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Fetch and unpack a Rust source archive')

    exclusive_group = parser.add_mutually_exclusive_group()
    exclusive_group.add_argument(
        "--beta", "-b", dest="build_type", action="store_const",
        default='', const='beta', help="fetch the beta archive")
    exclusive_group.add_argument(
        "--nightly", "-n", dest="build_type", action="store_const",
        default='', const='nightly', help="fetch the nightly archive")
    parser.add_argument(
        "--branch", metavar="NAME", dest="branch",
        help="Branch name to use for this prebuilt update")
    parser.add_argument(
        "--issue", "-i", "--bug", metavar="NUMBER", dest="issue",
        help="Issue number to include in commit message")
    parser.add_argument(
        "--overwrite", "-o", dest="overwrite", action="store_true",
        help="Overwrite the target branch if it exists")

    parser.add_argument("rust_version", action="store", type=utils.version_string_type)

    return parser.parse_args()


def clean_repository() -> None:
    print("Deleting old files")
    # Save the blank Android.mk file to prevent Soong from digging into the
    # rustc directory.
    RUST_REPO.rm(*[p.name for p in RUST_REPO.path.glob("*") if p.name not in ["Android.mk", ".git"]])


def fetch_and_extract_archive(build_type: str, rust_version: str) -> None:
    archive_url = construct_archive_url(build_type, rust_version)
    print("Fetching archive %s\n" % archive_url)
    utils.run_and_exit_on_failure(
        COMMAND_FETCH_AND_EXTRACT % archive_url,
        "Error fetching source for Rust version %s" % rust_version,
        cwd=RUST_SOURCE_PATH,
        shell=True)
    # Add newline padding to the output
    print()
    RUST_REPO.add('.')


def main() -> None:
    args              = parse_args()
    rust_version: str = args.rust_version + get_extra_tag(args.build_type)
    branch_name:  str = args.branch or (BRANCH_NAME_TEMPLATE % rust_version)

    print('')
    RUST_REPO.create_or_checkout(branch_name, args.overwrite)
    clean_repository()
    fetch_and_extract_archive(args.build_type, rust_version)
    RUST_REPO.amend_or_commit(make_commit_message(rust_version, args.issue))
    print("Done")


if __name__ == '__main__':
    main()
