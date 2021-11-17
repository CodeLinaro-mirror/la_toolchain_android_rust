# Updating the Android Rust Toolchain

## Preparation (one-off)

The Rust toolchain has its own branch manifest in AOSP, named `rust-toolchain`.
We will checkout this branch in a new directory:

```shell
$ export TOOLCHAIN=~/rust-toolchain
$ mkdir $TOOLCHAIN
$ cd $TOOLCHAIN
$ repo init -u https://android.googlesource.com/platform/manifest -b rust-toolchain
$ repo sync -j16
```

In your Android repo (`aosp-master`), add the new prebuilts path:

```shell
$ git -C prebuilts/rust remote add local $TOOLCHAIN/prebuilts/rust
```

## Create new prebuilts

We are now going to create a new prebuilt toolchain. This includes fetching the
latest toolchain from upstream, building it locally to confirm our extra patches
apply fine and finally uploading the source to Gerrit.

### Fetch latest upstream toolchain

```shell
$ ./toolchain/android_rust/fetch_source.py -i <issue_number> <rust_version>
# e.g. ./toolchain/android_rust/fetch_source.py 1.57.0
```

The `fetch_source.py` script has several more useful options, including support
for overwriting existing branches, manually specifying the branch name, or
fetching beta/nightly archives. Details are listed in the help output.

### Build locally

Select a distribution directory (this is usually provided by the buildserver).
For instance `$TOOLCHAIN/dist`:

```shell
# Optionally set DIST_DIR=$TOOLCHAIN/dist, but that is the default
$ ./toolchain/android_rust/build.py
```

If a patch failed to apply, first check if it was merged upstream. So far all
the patches we have in `patches/` we are trying to upstream, so this is the most
likely cause. If it has been, use `git` to create a commit removing it from the
`patches/` directory, e.g.

```
pushd toolchain/android_rust
repo start update-rustc-$RUST_VERSION
git rm patches/rustc-000n-Already-merged.patch
git commit -m "Remove Foo patch that has landed upstream"
popd
```

Tip: Use the same branch name as you did for `rustc` if you want repo tooling to
help you later.

If the build seems to be going, this will take a while; switch to another task,
get some coffee, etc.

### Upload

Place any changes to `toolchain/android_rust` and `toolchain/rustc` into a
topic, and use `repo` to upload as you usually would:

```
repo upload -t -o l=Presubmit-Ready+1
# You may need to use `-o nokeycheck` too for cargo prebuilts.
```

This may take a while because updates to `rustc` can be hefty in size. Double
check the response from the server to make sure the change went through.

You'll need to get these changes +2'd and merged before you can proceed.

#### Help, Gerrit won't take my update!

First, try again. Sometimes Gerrit is just flaky and will take it on the second
or third try.

If that's still not working, you are likely hitting a size limitation (for
example, because `rustc` updated it's LLVM revision, so the diff is bigger than
usual). In this case, you will need to work with the build team to get them to
use a "direct push" to skip gerrit's hooks. Look at the initial import
[bug](http://b/137197907) for an example conversation about importing oversized
changes.

## Push new prebuilts

Wait for [android build](http://ab/aosp-rust-toolchain) to complete a green
build including your changes. Find the build number of this build (it needs to
have both darwin and linux targets built).

Starting from `$TOOLCHAIN`, bring it up to date with `repo sync -d -j16` if
needed. Then:

```shell
$ ./toolchain/android_rust/update_prebuilts.py -i <issue_number> <build_id> <rust_version>
```

This command will generate CLs in the `prebuilts/rust` and
`toolchain/android_rust` directories.

## Update references to toolchain version

Next, you need to update the `RustDefaultVersion` variable in the
`build/soong/rust/config/global.go` file.

All of the CLs will be automatically tested in presubmit, but if you want to
test locally first:

*   To test the `rustc` build, re-run `DIST_DIR=$TOOLCHAIN/dist
    ./toolchain/android_rust/build.py` from the `$TOOLCHAIN` directory with your
    update staged.
*   To test the sysroot build, `lunch` any target, then `m libstd`
*   To test the Android tree, `lunch` any target, then `m crosvm`, go to
    `external/rust` and run `mma`.

## Publish Compiler Prebuilt

Now that we know the compiler is working, we need to tag it. This tag is not
used by Android, but Chrome is using it to produce an MPM of our compiler
releases for their work.

These commands do not have a review step like uploading a change, so be sure
that you have landed (not just uploaded) the commits from the previous step.

```shell
$ pushd prebuilts/rust
$ git tag rustc-$RUST_VERSION
$ git push aosp rustc-$RUST_VERSION
```

The new compiler will now be automatically made available to Chrome. (Actually
rolling the version of the compiler they're using is up to them, you don't need
to worry about that part.)

## Remove previous prebuilts

Once all of these updates are landed, nobody is using the old compiler version
anymore. Go ahead and remove the old compiler to save space in your colleagues'
checkouts:

```shell
$ pushd prebuilts/rust
$ repo start gc-rust-$OLD_RUST_VERSION
$ git rm -rf {linux-x86,darwin-x86}/$OLD_RUST_VERSION
$ git commit -m "Removing unused rustc-$OLD_RUST_VERSION"
$ popd
```

Once that change is landed, congratulations, you're done rolling the toolchain!

## Troubleshooting a Broken Sysroot Build

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
    on `libstd.static`. `libhashbrown.rust_sysroot` is built only as an `rlib`,
    and is linked as an `rlib` everywhere it is used.

## New Build Breaking Lint/Clippy Errors

New lints/clippys can cause build breakage and may require significant
refactoring as the code base grows. To avoid blocking toolchain upgrades,
explicitly allow the breaking lints/clippys when first upgrading the toolchain.

1.  Allow build breaking lints/clippys by adding them to the list in
    `build/soong/rust/config/lints.go` with the `-A` flag.
2.  If the new lint/clippy is beneficial enough to justify enable going forward,
    file a bug to track the refactor effort.
