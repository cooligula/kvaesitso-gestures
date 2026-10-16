# Patches

Every `patches/NN-description.patch` is plain `git diff` output, applied in name order with
`git apply` from the root of the upstream source. A patch that stops applying fails the pull
request build, which is the signal to rebase it.

To write or rebase a patch:

```sh
python3 scripts/kvgestures.py fetch                 # clean source in work/kvaesitso
cd work/kvaesitso
git apply ../../patches/*.patch                     # start from the current patches, or edit fresh
# ...edit...
git diff > ../../patches/NN-description.patch
```

Changing, adding or removing a patch changes the build input, so the next merge to `main`
publishes a new revision (`<upstream version>-gestures.<revision>`).
