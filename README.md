# frigate-build-deps

Copies of everything Troy's Frigate fork (github.com/TroyJ/frigate) downloads when it
builds the Raspberry Pi image and the Arm test devcontainer, so the build no longer
depends on third-party sources staying up or unchanged.

- **`manifest.json`**: the record. One entry per copied thing: what it is, version,
  original URL (or git repository and commit), sha256, size, licence, and which build
  uses it. Our copy of a file is
  `https://github.com/TroyJ/frigate-build-deps/releases/download/<release>/<asset>`;
  base images are `ghcr.io/troyj/<name>` at the same digest as the original.
- **Release files**: one release per project and version (notes list each file, its
  original, sha256 and licence; the licence text sits beside the files as `LICENSE-*`).
  The Python packages are one release per wheelhouse (`python-…`).
- **Not copied**: npm packages (the lockfile pins sha512s; fetched from npm) and Debian
  packages (read from snapshot.debian.org frozen at `debian.snapshot`).

## Workflows

| Workflow | What it does |
|---|---|
| Copy files (`mirror-files.yml`) | Fetches each original whose release file is missing, checks its sha256, uploads it. Never replaces a file. |
| Copy base images (`mirror-images.yml`) | `crane copy` of each image's whole index by digest to ghcr.io/troyj. |
| Python wheelhouse (`wheelhouse.yml`) | Builds the exact set of wheels from `python/*.lock` on an Arm runner in Debian 12, uploads them, records them in the manifest and writes the fork's lock files (`python/fork/`). |
| Weekly check (`weekly-check.yml`) | Mondays: every original still there and unchanged, every copy still here; opens an issue otherwise. |

## Tools

- `tools/mirror.py hash|mirror|check`: what the workflows run (see its docstring).
- `tools/backup.py DEST`: downloads every release file and verifies its sha256, for a
  second copy off GitHub (the Mac, the CORSAIR drive). Re-runnable.

How to add or refresh a copy when the fork moves to a new Frigate: the fork's notes,
bali-home-assistant `frigate-fork/docs/operations.md` §2.
