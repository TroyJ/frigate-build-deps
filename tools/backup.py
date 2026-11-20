#!/usr/bin/env python3
"""Download every release file listed in manifest.json and verify its sha256.

For keeping a second copy off GitHub (Troy's Mac, the CORSAIR drive). Standard
library only; run from a clone of this repository:

    python3 tools/backup.py /Volumes/CORSAIR/frigate-build-deps

Files land in DEST/<release>/<asset>. A file already there with the right sha256
is skipped, so the script can be re-run to top up after new copies are added.
Each release's licence file (LICENSE-*) is fetched too when the release has one.
Exits 1 if any file could not be fetched or has the wrong sha256.

--repos also makes a full mirror clone of each standalone repository
(TroyJ/nginx-vod-module) under DEST/repos/ (needs git).

Base images are not downloaded by this script; it prints a `crane pull` command
for each (crane: https://github.com/google/go-containerregistry), which saves
the whole multi-platform image as an OCI layout.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

UA = {"User-Agent": "frigate-build-deps-backup/1"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as out:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            out.write(chunk)
    os.replace(tmp, dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest")
    ap.add_argument("--manifest", default=os.path.join(os.path.dirname(__file__), "..", "manifest.json"))
    ap.add_argument("--repos", action="store_true", help="also mirror-clone the standalone repositories")
    a = ap.parse_args()
    m = json.load(open(a.manifest))
    base = m["copy_base_url"]
    bad, done, skipped, total = [], 0, 0, 0
    licences = {}
    for e in m["files"]:
        d = os.path.join(a.dest, e["release"])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, e["asset"])
        total += e.get("size") or 0
        if os.path.exists(path) and sha256_file(path) == e["sha256"]:
            skipped += 1
        else:
            try:
                fetch(f"{base}/{e['release']}/{e['asset']}", path)
            except Exception as ex:  # noqa: BLE001
                bad.append(f"{e['release']}/{e['asset']}: {ex}")
                continue
            got = sha256_file(path)
            if got != e["sha256"]:
                bad.append(f"{e['release']}/{e['asset']}: sha256 {got}, manifest says {e['sha256']}")
                os.replace(path, path + ".bad")
                continue
            done += 1
        if e.get("licence_url"):
            licences[e["release"]] = "LICENSE-" + e["name"].replace(" ", "-")
    for rel, name in licences.items():
        path = os.path.join(a.dest, rel, name)
        if not os.path.exists(path):
            try:
                fetch(f"{base}/{rel}/{name}", path)
            except Exception as ex:  # noqa: BLE001
                print(f"note: no licence file {rel}/{name}: {ex}")
    if a.repos:
        for r in m.get("repositories", []):
            target = os.path.join(a.dest, "repos", r["id"] + ".git")
            if os.path.isdir(target):
                subprocess.run(["git", "-C", target, "remote", "update", "--prune"], check=False)
            else:
                subprocess.run(["git", "clone", "--mirror", r["copy"], target], check=False)
    print(f"{done} downloaded, {skipped} already present and verified, of {len(m['files'])} files ({total / 1e6:.0f} MB)")
    print("Base images (run with crane to keep them too):")
    for i in m["images"]:
        print(f"  crane pull --format=oci {i['copy'].rsplit(':', 1)[0]}@{i['digest']} {a.dest}/images/{i['id']}")
    if bad:
        print(f"{len(bad)} problem(s):")
        for b in bad:
            print(" - " + b)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
