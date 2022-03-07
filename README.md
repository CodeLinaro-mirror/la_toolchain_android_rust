# Updating the Android Rust Toolchain

A new stable version of Rust is released approximately every six weeks. This
document describes the process to update the Android Rust toolchain for the
latest *Stable* Rust release. Other Googler developers use the artifacts
produced as a result of this process.

In order to resolve issues caused Rust toolchain updates ahead of time we will
perform the release process on the *Beta* version of the toolchain. Testing
against the Beta version of the toolchain can often hint at possible
incompataibilities between the Rust toolchain and the Android code base.
However, sometimes there will be language features available in a *Beta* that
have not been released in the *Stable* branch. Othertimes issues pop up in the
*Stable* version of the language that weren't in *Beta*, keeping us toolchain
developers on our toes and mindful of what/when we commit changes to the code
base.

Testing and deploying the Rust toolchain involves several steps: fetching the
toolchain from upstream, building it locally, modifying the Android source code
to be compatible with the latest release, testing the build, and uploading
compiler prebuilts to Gerrit. Since the *Beta* source is only used for testing
and preparation, only a subset of the steps are performed and the commands used
differ slightly from those used during a Stable release. We enumerate the steps
below and show the distinct workflows. The *Beta Workflow* is when the toolchain
developer is targetting the *Beta* version of the toolchain for the purposes of
diagnosing out possible issues. The *Stable Workflow* is when the toolchain
developer is targetting the *Stable* version of the Rust toolchain for the
purpose of providing prebuilts for other developers.

## Set-Up

### Initial Set-Up

This bit only needs to be done once and needs to be done before following the
*Beta* or *Stable Workflow*.

The Rust toolchain has its own branch manifest in AOSP, named `rust-toolchain`.
The following commands will create a repo directory (e.g. `~/rust-toolchain`),
initialize it with the rust-toolchain manifest, and synchronize the repository.

```shell
$ export TOOLCHAIN=~/rust-toolchain
$ mkdir $TOOLCHAIN
$ cd $TOOLCHAIN
$ repo init -u https://android.googlesource.com/platform/manifest -b rust-toolchain
$ repo sync -j16
```

To create a remote reference from an AOSP repo's `prebuilts/rust` directory to
the rust-toolchain's version run the following command in the AOSP tree's root:

```shell
$ git -C prebuilts/rust remote add local-toolchain $TOOLCHAIN/prebuilts/rust
```

## Beta Workflow

### Step 1-B: Fetch latest upstream toolchain

It is best to start the process with a freshly-synchronized repository.

```shell
$ ./toolchain/android_rust/fetch_source.py -i <issue_number> -b <rust_version>
# e.g. ./toolchain/android_rust/fetch_source.py -b 1.57.0
```

The `fetch_source.py` script has several more useful options, including support
for overwriting existing branches, manually specifying the branch name, or
fetching beta/nightly archives. Details are listed in the help output.

### Step 2-B: Build locally

```shell
$ ./toolchain/android_rust/build.py --lto thin
```

*Things that can go wrong* 1. If a patch failed to apply, first check if it was
merged upstream. So far all the patches we have in `patches/` we are trying to
upstream, so this is the most likely cause. If it has been, use `git` to create
a commit removing it from the `patches/` directory, e.g.

```
pushd toolchain/android_rust
repo start update-rustc-$RUST_VERSION
git rm patches/rustc-000n-Already-merged.patch
git commit -m "Remove Foo patch that has landed upstream"
popd
```

If the build seems to be going, this will take a while; switch to another task,
get some coffee, etc.

*Tips:* - Use the same branch name as you did for `rustc` if you want repo
tooling to help you later. E.g. rust-update-source-1.59.0

### Step 3-B: Update prebuilts

To test a locally built Rust toolchain you will first need to generate a commit
containing the relevant files:

```shell
$ ./toolchain/android_rust/update_prebuilts.py <archive_path> <rust_version>
```

The `archive_path` will be `$TOOLCHAIN/dist/rust-dev.tar.gz` by default unless
the `--build-name <name>` option was passed to `build.py`, in which case the
archive will be named `rust-<name>.tar.gz`.

Use the `--branch` argument to specify a name like
`rust-update-prebuilts-<version>-local` to avoid conflicts with the branch names
created with the artifacts from the build server.

This command will generate commits in the `prebuilts/rust` and `build/soong`
directories. Further changes to the files in `build/soong/rust` may be necessary
if arguments to the compiler or crate layouts change during the update. It is
important to fetch the changes to `build/soong` along with the prebuilt update
when performing local testing.

Next, in an AOSP repository:

```shell
$ pushd prebuilts/rust
$ git fetch local-toolchain
$ git checkout local-toolchain/rust-update-prebuilts-<version_number>
$ popd
$ pushd build/soong
$ git fetch local-toolchain
$ git checkout local-toolchain/rust-update-prebuilts-<version_number>
```

### Step 4-B: Test (*m rust*)

To build all Rust sources in Android:

```shell
$ m rust
```

This step may trigger new warnings on existing source files. If the compiler
suggests a fix apply it. Otherwise make the most reasonable looking change
necessary to keep the compiler happy and rely on the original author to
determine correctness during code review.

Further testing may be performed by building an Android image and booting it.

### Step 5-B: Boot(*m*)

## Stable Workflow

### Step 6-S: Fetch Source and Build Rust

Use steps 1-B and 2-B from the *Beta Workflow*, but remove the `-b` flag.

### Step 7-S: Upload

Place any changes to `toolchain/android_rust` and `toolchain/rustc` into a
topic, and use `repo` to upload as you usually would:

```
repo upload -t -o l=Presubmit-Ready+1
# You may need to use `-o nokeycheck` too for cargo prebuilts.
```

This may take a while because updates to `rustc` can be hefty in size. Double
check the response from the server to make sure the change went through.

You'll need to get these changes +2'd and merged before you can proceed.

*Things that can go wrong*: 1. Help, Gerrit won't take my update!

First, try again. Sometimes Gerrit is just flaky and will take it on the second
or third try.

If that's still not working, you are likely hitting a size limitation (for
example, because `rustc` updated it's LLVM revision, so the diff is bigger than
usual). In this case, you will need to work with the build team to get them to
use a "direct push" to skip gerrit's hooks. Look at the initial import
[bug](http://b/137197907) for an example conversation about importing oversized
changes.

### Step 8-S: Wait for builds

Wait for [android build](http://ab/aosp-rust-toolchain) to complete a green
build including your changes.

The next step (**9-S**) can be done concurrently.

### Step 9-S: Testing Build

Follow steps 3-B, 4-B, and 5-B in the *Beta workflow*.

### Step 10-S: Update prebuilts

Find the build number (found at **Step 8-S**) of this build (it needs to have
both darwin and linux targets built) and run the update_prebuilts.py`script:

```shell
$ ./toolchain/android_rust/update_prebuilts.py -i <issue_number> <build_id> <rust_version>
```

### Step 11-S: Upload to Gerrit

Upload the new commits in `prebuilts/rust` and `build/soong` to Gerrit, making
sure to include any necessary modifications that were discovered during local
testing. It is also possible to upload the changes from rust-toolchain's copy of
`prebuilts/rust` and the changes to `build/soong` from an AOSP repo.

### Step 12-S: Remove previous prebuilts

Once all of these updates are landed, nobody is using the old compiler version
anymore. Go ahead and remove the old compiler to save space in your colleagues'
checkouts:

```shell
$ cd prebuilts/rust
$ repo start gc-rust-$OLD_RUST_VERSION
$ git rm -rf {linux-x86,darwin-x86}/$OLD_RUST_VERSION
$ git commit -m "Removing unused rustc-$OLD_RUST_VERSION"
```

Once that change is landed, congratulations, you're done rolling the toolchain!

### Step 13-S: Tagging (Publish Compiler Prebuilt)

Once the CL containing the new prebuilts has been merged it needs to be tagged.
This tag is not used by Android, but Chrome is using it to produce an MPM of our
compiler releases for their work.

These commands do not have a review step like uploading a change, so be sure
that you have landed (not just uploaded) the commits from the previous step.

```shell
$ cd prebuilts/rust
$ git tag rustc-$RUST_VERSION
$ git push aosp rustc-$RUST_VERSION
```

The new compiler will now be automatically made available to Chrome. (Actually
rolling the version of the compiler they're using is up to them, you don't need
to worry about that part.)

## Notes

### Troubleshooting a Broken Sysroot Build

If the sysroot build is broken, check whether the error mentions a missing
crate. If it does, there have likely been new components added to the sysroot.
To address this, you will need to:

1.  Add the relevant components to `STDLIB_SOURCES` in
    `toolchain/android_rust/build.py`.
2.  Respin the toolchain via the process above, but with a fresh commit message
    noting the reason for the respin. You may want to test this locally first as
    more than one dependency may have been added. For local testing,
    1.  Build as before, using `DIST_DIR=$TOOLCHAIN/dist
        ./toolchain/android_rust/build.py`
    2.  Make a local commit with the contents of the tarball now in `$DIST_DIR`
    3.  Go to `prebuilts/rust` in your Android tree and use `git fetch local`
        followed by a checkout to get it imported into your Android tree.
3.  Add the missing dependencies to `prebuilts/rust/Android.bp`. Except for
    publicly exported crates (which you're not adding right now), all modules in
    this file must be suffixed with `.rust_sysroot` to avoid confusion with user
    crates. Dependency edges should all be of `rlib` form unless depending on a
    publicly exported crate, in which case the dependency edge should match the
    type of the final product. As examples, `libterm` (exported) depends by
    `dylib` on `libstd`, but `libterm.static` (also exported) depends by `rlib`
    on `libstd.static`.`libhashbrown.rust_sysroot` is built only as an `rlib`,
    and is linked as an `rlib` everywhere it is used.

### New Build Breaking Lint/Clippy Errors

New lints/clippys can cause build breakage and may require significant
refactoring as the code base grows. To avoid blocking toolchain upgrades,
explicitly allow the breaking lints/clippys when first upgrading the toolchain.

1.  Allow build breaking lints/clippys by adding them to the list in
    `build/soong/rust/config/lints.go` with the `-A` flag.
2.  If the new lint/clippy is beneficial enough to justify enable going forward,
    file a bug to track the refactor effort.

