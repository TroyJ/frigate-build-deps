#!/usr/bin/env python3
"""Keep the copies listed in manifest.json as release files in TroyJ/frigate-build-deps.

Subcommands (run from the repository root; the GitHub ones need `gh` logged in,
or GH_TOKEN set, with write access to this repository):

  hash [--write] [ID ...]
      Download each original whose sha256 is still empty (or the named IDs),
      print its sha256 and size; --write records them in manifest.json. This is
      trust on first use: compare with a hash the project publishes when there
      is one (GitHub release digests, SHASUMS files) before committing.

  mirror [ID ...]
      For every file entry (or the named IDs) whose release file is missing:
      fetch the original (download, or `git archive` of the pinned commit),
      check sha256 and size against the manifest, create the release if needed
      (notes list each file, its original, sha256 and licence) and upload it,
      with the project's licence file beside it. Never replaces an existing
      release file. A git-archive entry with an empty sha256 is recorded on
      first creation (the commit hash is its real pin); pass --write to save it.

  check [--issue]
      The weekly check. For each file: the original is still there and has the
      same sha256 (git sources: the pinned commit is still in the original
      repository); our release file is there with the same sha256 (GitHub's
      digest). For each base image: the pinned digest still exists at the
      original and in our copy. For Python wheels: PyPI still serves the file
      with the same sha256. Exits 1 on any problem; --issue opens (or comments
      on) an issue in this repository listing them.

Standard library only, plus `git` and `gh`; `check` also uses `docker buildx
imagetools` for images.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = "TroyJ/frigate-build-deps"
MANIFEST = "manifest.json"
UA = {"User-Agent": "frigate-build-deps-mirror/1"}


def load():
    with open(MANIFEST) as f:
        return json.load(f)


def save(m):
    with open(MANIFEST, "w") as f:
        json.dump(m, f, indent=1)
        f.write("\n")


def copy_url(m, e):
    return f"{m['copy_base_url']}/{e['release']}/{e['asset']}"


def download(url, dest, tries=4):
    """Download url to dest; return (sha256, size). Retries on network errors."""
    last = None
    for attempt in range(tries):
        try:
            h = hashlib.sha256()
            size = 0
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            return h.hexdigest(), size
        except (urllib.error.URLError, TimeoutError, ConnectionError) as ex:
            last = ex
            if isinstance(ex, urllib.error.HTTPError) and ex.code in (404, 410):
                break
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(), os.path.getsize(path)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def git_archive(e, workdir):
    """Fetch the pinned commit and write `git archive` of it; return the path."""
    src = os.path.join(workdir, "src")
    clone = e.get("clone")
    if clone:
        # Same clone the build used to make, so the history (and anything
        # derived from it, such as ffmpeg's version string) is the same.
        run(["git", "clone", "-q", "--depth", str(clone["depth"]), "-b", clone["branch"], e["git_url"], src])
    else:
        run(["git", "init", "-q", src])
        run(["git", "-C", src, "fetch", "-q", "--depth", "1", e["git_url"], e["commit"]])
    run(["git", "-C", src, "cat-file", "-e", e["commit"] + "^{commit}"])
    out = os.path.join(workdir, e["asset"])
    run(["git", "-C", src, "archive", "--format=tar.gz", f"--prefix={e['archive_prefix']}", "-o", out, e["commit"]])
    return out


def fetch_original(e, workdir):
    if e["kind"] == "download":
        path = os.path.join(workdir, e["asset"])
        download(e["original_url"], path)
        return path
    if e["kind"] == "git-archive":
        return git_archive(e, workdir)
    raise ValueError(f"{e['id']}: kind {e['kind']} is not fetched by this tool")


def gh_json(args):
    return json.loads(run(["gh", "api"] + args))


def release_assets(tag):
    """{asset name: {'digest': 'sha256:..'|None, 'size': n}} or None if no release."""
    try:
        rel = gh_json([f"repos/{REPO}/releases/tags/{tag}"])
    except subprocess.CalledProcessError:
        return None
    return {a["name"]: {"digest": a.get("digest"), "size": a["size"]} for a in rel["assets"]}


def release_notes(m, tag):
    entries = [e for e in m["files"] if e.get("release") == tag]
    first = entries[0]
    lines = [f"**{first['name']} {first['version']}**: {first['description']}", ""]
    lines.append("Copied for Troy's Frigate fork build; the build fetches these files from here and checks each sha256.")
    lines.append("")
    lines.append("| File | Original | sha256 | Licence |")
    lines.append("|---|---|---|---|")
    for e in entries:
        orig = e.get("original_url") or f"{e['git_url']} @ {e['commit']} (git archive, prefix {e['archive_prefix']})"
        lines.append(f"| `{e['asset']}` | {orig} | `{e['sha256']}` | {e['licence']} |")
    if first.get("licence_url"):
        lines.append("")
        lines.append(f"Licence text: `LICENSE-{first['name'].replace(' ', '-')}` beside these files (from {first['licence_url']}).")
    notes = sorted({e["notes"] for e in entries if e.get("notes")})
    if notes:
        lines.append("")
        lines += notes
    lines.append("")
    lines.append("Machine-readable record: manifest.json in this repository.")
    return "\n".join(lines)


def ensure_release(m, tag):
    assets = release_assets(tag)
    if assets is None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(release_notes(m, tag))
            notes = f.name
        run(["gh", "release", "create", tag, "-R", REPO, "--title", tag, "--notes-file", notes, "--target", "main"])
        os.unlink(notes)
        assets = {}
    return assets


def cmd_hash(m, ids, write):
    todo = [e for e in m["files"] if e["kind"] == "download" and ((not ids and not e["sha256"]) or e["id"] in ids)]
    with tempfile.TemporaryDirectory() as d:
        for e in todo:
            path = os.path.join(d, "f")
            sha, size = download(e["original_url"], path)
            os.unlink(path)
            print(f"{e['id']}\t{sha}\t{size}")
            if write:
                e["sha256"], e["size"] = sha, size
    if write:
        save(m)


def cmd_mirror(m, ids, write):
    failures = 0
    by_release = {}
    for e in m["files"]:
        if e["kind"] in ("download", "git-archive") and (not ids or e["id"] in ids):
            by_release.setdefault(e["release"], []).append(e)
    for tag, entries in by_release.items():
        if any(not e["sha256"] and e["kind"] == "download" for e in entries):
            print(f"SKIP {tag}: a download has no sha256 yet (run `hash` first)")
            failures += 1
            continue
        assets = release_assets(tag) or {}
        missing = [e for e in entries if e["asset"] not in assets]
        if not missing:
            print(f"ok   {tag}: all {len(entries)} file(s) present")
            continue
        with tempfile.TemporaryDirectory() as d:
            ready = []
            for e in missing:
                path = fetch_original(e, d)
                sha, size = sha256_file(path)
                if e["kind"] == "git-archive" and not e["sha256"]:
                    print(f"new  {e['id']}: git archive sha256 {sha} size {size} (recorded)")
                    e["sha256"], e["size"] = sha, size
                if sha != e["sha256"] or (e.get("size") and size != e["size"]):
                    print(f"FAIL {e['id']}: original has sha256 {sha} size {size}, manifest says {e['sha256']} {e.get('size')}")
                    failures += 1
                    continue
                e["size"] = size
                ready.append(path)
            if not ready:
                continue
            assets = ensure_release(m, tag)
            first = entries[0]
            lic_name = f"LICENSE-{first['name'].replace(' ', '-')}"
            if first.get("licence_url") and lic_name not in assets:
                lic = os.path.join(d, lic_name)
                try:
                    download(first["licence_url"], lic)
                    ready.append(lic)
                except RuntimeError as ex:
                    print(f"WARN {tag}: licence file not fetched: {ex}")
            run(["gh", "release", "upload", tag, "-R", REPO] + ready)
            # Notes carry the sha256s, which may only now be known.
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(release_notes(m, tag))
            run(["gh", "release", "edit", tag, "-R", REPO, "--notes-file", f.name])
            os.unlink(f.name)
            print(f"up   {tag}: uploaded {', '.join(os.path.basename(p) for p in ready)}")
    if write:
        save(m)
    return failures


def pypi_sha256(name, version, filename):
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    for u in data.get("urls", []):
        if u["filename"] == filename:
            return u["digests"]["sha256"], u.get("yanked", False)
    return None, False


def cmd_check(m, open_issue):
    problems = []
    release_cache = {}

    def ours(e):
        tag = e["release"]
        if tag not in release_cache:
            release_cache[tag] = release_assets(tag)
        assets = release_cache[tag]
        if assets is None:
            return f"our release {tag} is missing"
        a = assets.get(e["asset"])
        if a is None:
            return f"our file {tag}/{e['asset']} is missing"
        if a.get("digest") and a["digest"] != "sha256:" + e["sha256"]:
            return f"our file {tag}/{e['asset']} has {a['digest']}, manifest says {e['sha256']}"
        return None

    with tempfile.TemporaryDirectory() as d:
        for e in m["files"]:
            label = f"{e['id']} ({e.get('description', e.get('name'))})"
            p = ours(e)
            if p:
                problems.append(f"{label}: {p}")
            try:
                if e["kind"] == "download":
                    path = os.path.join(d, "f")
                    sha, size = download(e["original_url"], path)
                    os.unlink(path)
                    if sha != e["sha256"]:
                        floats = "get-pip" in e["id"]
                        problems.append(f"{label}: original {e['original_url']} now has sha256 {sha} (size {size}); our copy has {e['sha256']}"
                                        + (" (expected: this original always serves the latest version)" if floats else ""))
                elif e["kind"] == "git-archive":
                    with tempfile.TemporaryDirectory() as g:
                        run(["git", "init", "-q", g])
                        run(["git", "-C", g, "fetch", "-q", "--depth", "1", e["git_url"], e["commit"]])
                        if e.get("clone"):
                            heads = run(["git", "ls-remote", e["git_url"], f"refs/heads/{e['clone']['branch']}"])
                            if not heads.strip():
                                problems.append(f"{label}: branch {e['clone']['branch']} is gone from {e['git_url']} (the commit is still there)")
                elif e["kind"] == "python-wheel":
                    if e.get("original_url", "").startswith("https://files.pythonhosted.org/"):
                        sha, yanked = pypi_sha256(e["name"], e["version"], e["original_url"].rsplit("/", 1)[1])
                        if sha is None:
                            problems.append(f"{label}: PyPI no longer lists {e['original_url']}")
                        elif sha != e["sha256"]:
                            problems.append(f"{label}: PyPI sha256 {sha} differs from ours {e['sha256']}")
                        elif yanked:
                            problems.append(f"{label}: yanked on PyPI (our copy still works)")
                    elif e.get("source_url"):
                        req = urllib.request.Request(e["source_url"], headers=UA, method="HEAD")
                        urllib.request.urlopen(req, timeout=60).close()
            except Exception as ex:  # noqa: BLE001 - every failure is a finding
                problems.append(f"{label}: original not reachable: {ex}")

    for i in m["images"]:
        for ref, what in ((f"{i['original'].rsplit(':', 1)[0]}@{i['digest']}", "original"),
                          (f"{i['copy'].rsplit(':', 1)[0]}@{i['digest']}", "our copy")):
            r = subprocess.run(["docker", "buildx", "imagetools", "inspect", ref], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append(f"{i['id']} ({i['name']}): {what} {ref} not found: {r.stderr.strip()[:200]}")

    for r in m.get("repositories", []):
        for url in [r["copy"]] + r["originals"]:
            res = subprocess.run(["git", "ls-remote", "--heads", url], capture_output=True, text=True)
            if res.returncode != 0 or not res.stdout.strip():
                problems.append(f"{r['id']}: repository {url} not reachable")

    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(" - " + p)
    else:
        print("everything checked: all originals unchanged and all copies present")
    if problems and open_issue:
        title = "Weekly check: originals or copies changed"
        body = "The weekly check found:\n\n" + "\n".join(f"- {p}" for p in problems)
        run_url = os.environ.get("GITHUB_SERVER_URL", "") + "/" + os.environ.get("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
        body += f"\n\nRun: {run_url}\n"
        existing = gh_json([f"repos/{REPO}/issues?state=open&per_page=100"])
        same = [x for x in existing if x["title"] == title and "pull_request" not in x]
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
        if same:
            run(["gh", "issue", "comment", str(same[0]["number"]), "-R", REPO, "--body-file", f.name])
        else:
            run(["gh", "issue", "create", "-R", REPO, "--title", title, "--body-file", f.name])
        os.unlink(f.name)
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash")
    h.add_argument("--write", action="store_true")
    h.add_argument("ids", nargs="*")
    mi = sub.add_parser("mirror")
    mi.add_argument("--write", action="store_true")
    mi.add_argument("ids", nargs="*")
    c = sub.add_parser("check")
    c.add_argument("--issue", action="store_true")
    a = ap.parse_args()
    m = load()
    if a.cmd == "hash":
        cmd_hash(m, a.ids, a.write)
        return 0
    if a.cmd == "mirror":
        return 1 if cmd_mirror(m, a.ids, a.write) else 0
    return cmd_check(m, a.issue)


if __name__ == "__main__":
    sys.exit(main())
