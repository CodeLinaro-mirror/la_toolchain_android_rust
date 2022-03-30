# Updating the Android Rust Toolchain

A new stable version of Rust is released approximately every six weeks. This
document describes the process to update the Android Rust toolchain for the
latest *Stable* Rust release. Other Googler developers use the artifacts
produced as a result of this process.

In order to resolve issues caused Rust toolchain updates ahead of time we will
perform the release process on the *Beta* version of the toolchain. Testing
against the Beta version of the toolchain can often hint at possible
incompatibilities between the Rust toolchain and the Android code base. However,
sometimes there will be language features available in a *Beta* that have not
been released in the *Stable* branch. Other times issues pop up in the *Stable*
version of the language that weren't in *Beta*, keeping us toolchain developers
on our toes and mindful of what/when we commit changes to the code base.

Testing and deploying the Rust toolchain involves several steps: fetching the
toolchain from upstream, building it locally, modifying the Android source code
to be compatible with the latest release, testing the build, and uploading
compiler prebuilts to Gerrit. Since the *Beta* source is only used for testing
and preparation, only a subset of the steps are performed and the commands used
differ slightly from those used during a Stable release. We enumerate the steps
below and show the distinct workflows. The *Beta Workflow* is when the toolchain
developer is targeting the *Beta* version of the toolchain for the purposes of
diagnosing possible issues. The *Stable Workflow* is when the toolchain
developer is targeting the *Stable* version of the Rust toolchain for the
purpose of providing prebuilts for other developers.

In [Section 1](#section-1-the-steps) we cleanly and concisely describe the steps
for updating the Android Rust toolchain during the initial set-up, *Beta
Workflow* and the *stable workflow*. In
[Section 2](#section-2-how-to-fix-things) we provide more details on the types
of things that can go wrong and provide some guidance on how to get past those.

## Section 1: The-Steps

### Section 1.1: Setting up

The Rust toolchain has its own branch manifest in AOSP, named `rust-toolchain`.

#### Just once

The following step just needs to be done once when setting up. The following
commands will create a repo directory (e.g. `~/rust-toolchain`), initialize it
with the rust-toolchain manifest, and synchronize the repository.

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

Similarly, write the following to create a reference to the `build/soong`
directory

```shell
$ git -C build/soong remote add local-toolchain $TOOLCHAIN/build/soong
```

#### Each time

Each time you start to work on updating the toolchain you will want to sync in
the toolchain and aosp directory.

```shell
$ cd $TOOLCHAIN
$ repo sync -j16
$ // navigate to aosp manifest location
$ repo sync -j16
```

### Section-1.2: Beta Workflow

#### Step 1-B: Fetch latest upstream toolchain

It is best to start the process with a freshly-synchronized repository.

```shell
$ ./toolchain/android_rust/fetch_source.py -i <issue_number> -b <rust_version>
# e.g. ./toolchain/android_rust/fetch_source.py -b 1.57.0
```

The `fetch_source.py` script has several more useful options, including support
for overwriting existing branches, manually specifying the branch name, or
fetching beta/nightly archives. Details are listed in the help output.

#### Step 2-B: Build locally

```shell
$ ./toolchain/android_rust/build.py --lto thin
```

There are various reasons why the build might break. Check out Section 2.1 for
helpful instructions and tips to build Rust.

If the build seems to be going, this will take a while; switch to another task,
get some coffee, etc.

This step will create *rust-dev-tar.gz*.

*Tips:* - Use the same branch name as you did for `rustc` if you want repo
tooling to help you later. E.g. rust-update-source-1.59.0

#### Step 3-B: Update prebuilts

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

If hitting an issue with these steps check Section 2.2 for helpful examples.

#### Step 4-B: Test

We will need to rebuild the Android environment

```shell
source build/envsetup.sh
lunch aosp_cf_x86_64_phone-userdebug
```

To build all Rust sources in Android:

```shell
$ m rust
```

There are various things that can break here. Take a look at Section 2.3 for
instructions on how to fix the build.

Further testing may be performed by building an Android image and booting it.

#### Step 5-B: Boot

```shell
Build new image (*m*).
Flash, boot, and test new image.
```

TODO Chris/Stephen: Add instructions here

## Section 1.3: Stable Workflow

#### Step 6-S: Fetch Source and Build Rust

Use steps 1-B and 2-B from the *Beta Workflow*, but remove the `-b` flag. You
might also need to use the `--overwrite` flag if you've worked on this release
before, say during the *Beta Workflow*

#### Step 7-S: Upload

Place any changes to `toolchain/android_rust` and `toolchain/rustc` into a
topic, and use `repo` to upload as you usually would:

```
repo upload -t -o l=Presubmit-Ready+1
# You may need to use `-o nokeycheck` too for cargo prebuilts.
```

This may take a while because updates to `rustc` can be hefty in size. Double
check the response from the server to make sure the change went through.

You'll need to get these changes +2'd and merged before you can proceed.

Make sure same topic has been added to both CLs:`rust-update-source-1.59.0`,
with an updated Rust version number.

Check out Section 2.4 for tips for possible issues with Gerrit.

#### Step 8-S: Wait for builds

Wait for [android build](http://ab/aosp-rust-toolchain) to complete a green
build including your changes.

The next step (**9-S**) can be done concurrently.

#### Step 9-S: Testing Build

Follow steps 3-B, 4-B, and 5-B in the *Beta workflow*.

#### Step 10-S: Update prebuilts

Find the build number (found at **Step 8-S**) of this build (it needs to have
both darwin and linux targets built) and run the `update_prebuilts.py`script
using the build number:

```shell
$ ./toolchain/android_rust/update_prebuilts.py -i <issue_number> <build_id> <rust_version>
```

#### Step 11-S: Upload to Gerrit

Upload the new commits in `prebuilts/rust` and `build/soong` to Gerrit. Do this
by going into both directories and using:

```shell
$ repo upload --cbr .
```

Note that as a last argument `cbr` will upload the current branch and `.` will
upload this directory. Note that the terminal might flag an issue at this step
with `f..` instructions, but you can just follow the instructions from the
command line and retry this step..

This process should create two CLs. Open up the Gerrit links and mark one of
them as presubmit-ready. Add the same topic to both CLs
`rust-update-prebuilts-1.59.0`, with an updated Rust version number.

#### Step 12-S: Remove previous prebuilts

Take a look at the existing prebuilts. Look for the lowest version number and
remove it.

```shell
$ cd prebuilts/rust
$ repo start gc-rust-$OLD_RUST_VERSION
$ git rm -rf {linux-x86,darwin-x86}/$OLD_RUST_VERSION
$ git commit -m "Removing unused rustc-$OLD_RUST_VERSION"
$ repo upload .
```

TODO Stephen: Are we still removing old versions?

#### Step 13-S: Tagging (Publish Compiler Prebuilt)

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

## Section 2: How to Fix Things

While updating the Rust toolchain there are various issues that can arise.
Things can break, roadblocks can get in the way, and others might need to be
brought in. In this section we describe the different types of issues that can
occur, examples, and instruct on how to move past them.

#### Section 2.1 : The Rust Build

Things that can break during **Step 2-B**:

-   Patch Application
-   Directory Structure Change
-   Binary Incompatibility
-   Compilation Failure
-   New Crate

**Patch Application**

The Android project carries several patches for the Rust toolchain source.
Patches make changes to a code file. In order for a patch file to be
successfully applied the code that it is targeting needs to match the code file
closely enough for the algorithm in the `patch` program to identify the relevant
code. If a patch file fails to be applied then it is likely due to a change in
the targeted code base. In which case, the next step is to figure out if the
patch is still necessary to be applied or if that Patch file can be removed.

To know which patch file failed take a look at the terminal error message. The
error message will also say what *hunk #* and name of the Rust file. Open up the
patch file in `android_rust/patches` and the Rust file. At this point it'll
either look like (1) patch was already applied, (2) the codebase was otherwise
modified.

In the case of (1), it would be useful to verify that the patch was applied.
This can be done by look at the log history for that Rust file.If you do believe
that the patch was merged upstream then you just need to remove the patch from
the `patches/` directory, e.g.

```
pushd toolchain/android_rust
repo start update-rustc-$RUST_VERSION
git rm patches/rustc-000n-Already-merged.patch
git commit -m "Remove Foo patch that has landed upstream"
popd
```

In the case of (2), the codebase was changed in some way. Sometimes the
difference might be very simple. For instance, one time the difference was just
a variable name change and looking at the log history confirmed that.

To be able to successfully apply the patch the code in the patch must match the
code base exactly so go ahead and modify the patch code to match the code base.
If adding or removing lines of code be sure to update the number of lines that
is noted in the patch file. If you are unsure if the change upholds the intent
of the patch go ahead and email the patch owner, but note they will also be
added as a reviewer.

After editing the patch file, upload the change to Gerrit, and ask the patch
owner to review the changes to make sure the intent of the patch is still
Upheld. Use the topic with "source".

Here is an example of updating a patch file to correspond to changes in code
[CL](https://android-review.googlesource.com/c/toolchain/android_rust/+/1999334).

It may also be useful to create a new patch. The following:

```
git format-patch HEAD~
```

will generate a patch file for just the previous commit.

**Directory Structure Change** Sometimes another library needs to be imported.
We can do this by adding to the `STDLIB_SOURCES` definition in the `do_build.py`
script.

For example we got the following:

```shell
error: couldn't read prebuilts/rust/linux-x86/1.59.0/src/stdlibs/library/core/src/../../portable-simd/crates/core_simd/src/mod.rs: No such file or direct
ory (os error 2)
   --> prebuilts/rust/linux-x86/1.59.0/src/stdlibs/library/core/src/lib.rs:415:1
    |
415 | mod core_simd;
    | ^^^^^^^^^^^^^^
error: aborting due to previous error

22:37:34 ninja failed with: exit status 1

#### failed to build some targets (18 seconds) ####

```

and as a result we added the portable-simd library as seen in this
[CL](https://android-review.googlesource.com/c/toolchain/android_rust/+/1999334/4/do_build.py).

**Binary Incompatibility**

*TODO: text here to describe how the user will know this type of error occured
and how to fix it*

**Compilation Failure**

*TODO: text here to describe how the user will know this type of error occured
and how to fix it*

**New Crate**

Sometimes a new crate is added and a modification needs to be made to
`prebuilts/rustc/Android.bp`.

*TODO: text here to describe how the user will know this type of error occured
and how to fix it*

#### Section 2.2: Update prebuilts

Things that can break during **Step 3-B**:

-   File undefined

**File undefined**

Try deleting the branch `git branch -D rust-update-prebuilts-1.59.0-local`

#### Section 2.3: Test

Things that can break during **Step 4-B**:

-   Hermeticity breakage
-   Build system breakage
-   Android Source Warnings
-   Miscompilation
-   Deprecated Flag

**Hermeticity Breakage**

*TODO: text here to describe how the user will know this type of error occured
and how to fix it*

**Build System Breakage**

There can be build breakage issues.

For instance, needing to change `"-C passes='sancov'"`, to `"-C
passes='sancov-module'"`, such as in this
[CL](https://android-review.googlesource.com/c/platform/build/soong/+/2003172/4/rust/sanitize.go).

**Android Source Warnings**

A common issue is that this step triggers new warnings on existing source files.
If the compiler suggests a fix, apply it. Otherwise make the most reasonable
looking change necessary to keep the compiler happy and rely on the original
author to determine correctness during code review.

Here is an example of the workflow to modify file x.rs:

```
# navigate to the repo with file x.rs
repo start rust-1.59.0-fixes
# make changes to x.rs
git add x.rs
git commit
```

The commit message should include the testing strategy and buganizer ticket
number. Here is an example commit message from one of these types of
[CLs](https://android-review.googlesource.com/c/platform/system/security/+/2002316).

```
Changes for the Rust 1.59.0 update

bug: 215232614
Test: TreeHugger and compiling with m rust
Change-Id: I1d25f5550f60ff1046a3a312f7bd210483bf9364
```

Note, that it is preferable to create one commit per big change to a repo, so it
might be helpful to use amend when adding more changes to the code:

```shell
$ git commit --amend --no-edit
```

After committing the changes continue to upload them to Gerrit with

```shell
repo upload .
```

In Gerrit for the corresponding CL include the owners of the file as reviewers
and do not set a `topic`.

Next we will need to periodically check-in on these CLs. If they pass presubmit,
then we are waiting for the CLs to be approved/submitted by the file owners.
This can take a few days and may require a friendly nudge.

If the files do not pass presubmit then the changes may not have been backwards
compatible with Rust and we will need to compile it with the latest version of
Rust. If that is the case on Gerrit include it in the topic
`rust-update-prebuilts-1.59.0`, with an updated Rust version number.

We are not able to move to the final **Step 13-S** until these CLs created in
this process has been submitted/accepted.

**Miscompilation**

A miscompilation may have occured when it successfully compiles but the devices
fail to boot or pass CTS tests.

*TODO: text here to describe how the user will know this type of error occured
and how to fix it*

**Deprecated flag**

The following error:

```shell
warning: `-Z symbol-mangling-version` is deprecated; use `-C symbol-mangling-version`
```

led to changes where that variable was used with `-Z` was changed to `-C` in
`rust/config/global.go`.
[CL](https://android-review.googlesource.com/c/platform/build/soong/+/2003172/5/rust/config/global.go)
.

#### Section 2.4: Upload

Things that can break during **Step 7-S** and **Step 11-S**:

-   Geritt limitation
-   Detached head

**Geritt Limitation**

Help, Gerrit won't take my update!

First, try again. Sometimes Gerrit is just flaky and will take it on the second
or third try.

If that's still not working, you are likely hitting a size limitation (for
example, because `rustc` updated it's LLVM revision, so the diff is bigger than
usual). In this case, you will need to work with the build team to get them to
use a "direct push" to skip gerrit's hooks. Look at the initial import
[bug](http://b/137197907) for an example conversation about importing oversized
changes.

**Detached head**

Use this to get away from detached head:

```shell
git branch -u aosp/master
```

## Section 3: Notes

### Troubleshooting a Broken Sysroot Build

*Question: Should this be added to `Section 2.1 Build Error - Missing Crate` or
is it a different type of error?*

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

*TODO: Merge this text into the previous sections*

New lints/clippys can cause build breakage and may require significant
refactoring as the code base grows. To avoid blocking toolchain upgrades,
explicitly allow the breaking lints/clippys when first upgrading the toolchain.

1.  Allow build breaking lints/clippys by adding them to the list in
    `build/soong/rust/config/lints.go` with the `-A` flag.
2.  If the new lint/clippy is beneficial enough to justify enable going forward,
    file a bug to track the refactor effort.

