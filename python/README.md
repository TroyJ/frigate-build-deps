# Python package sets

`requirements-<set>.in` are the inputs (the fork's lists, see each file's header);
`<set>-cp311-aarch64.lock` the exact resolution with PyPI's sha256 for every file,
generated with uv for Debian 12's platform (glibc 2.36) and CPython 3.11:

    for s in build wheels dev; do
      uv pip compile requirements-$s.in --python-version 3.11 \
        --python-platform aarch64-manylinux_2_36 --generate-hashes --no-header \
        --emit-index-url -o $s-cp311-aarch64.lock
    done

Then run the "Python wheelhouse" workflow with a new release tag. It builds the wheels
in Debian 12 on an Arm runner, uploads them, records them in `manifest.json` and writes
`fork/requirements-<set>-arm64.lock`, which are copied into the fork's `docker/main/`.

Sets: `build` (pip, setuptools 77.0.3, wheel, scikit-build: installed first in the
`wheels` stage), `wheels` (everything Frigate installs), `dev` (ruff and types-peewee,
devcontainer only).
