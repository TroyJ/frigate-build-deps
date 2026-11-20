#!/bin/bash
# Build the Python wheelhouse inside Debian 12 (our copy of debian:12, by digest) on a
# linux/arm64 machine: the same OS, Python 3.11 and build libraries as the fork's
# `wheels` stage, so a package PyPI only has as source is compiled the same way.
#
#   docker run --rm -v "$PWD:/w" -w /w ghcr.io/troyj/debian:12@sha256:... tools/build_wheelhouse.sh
#
# For each lock in python/*-cp311-aarch64.lock (build, wheels, dev):
#   - pip resolves it with --require-hashes (every file checked against PyPI's sha256)
#     and writes a JSON report of where each file came from (out/report-<set>.json);
#   - pip wheel copies each wheel and builds each source archive into a wheel
#     (out/<set>/).
# Network: PyPI, our release files, snapshot.debian.org. tools/wheelhouse.py then
# uploads the result and writes the manifest entries and the fork's lock files.
set -euxo pipefail

SNAPSHOT="$(sed -n 's/.*"snapshot": "\([0-9TZ]*\)".*/\1/p' manifest.json)"
test -n "$SNAPSHOT"

# Debian's dated archive, as in the fork (docker/main/use_debian_snapshot.sh).
sed -i \
  -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${SNAPSHOT}|" \
  -e "s|http://deb.debian.org/debian\$|http://snapshot.debian.org/archive/debian/${SNAPSHOT}|" \
  /etc/apt/sources.list.d/debian.sources
printf 'Acquire::Check-Valid-Until "false";\nAcquire::Retries "5";\n' > /etc/apt/apt.conf.d/99snapshot

export DEBIAN_FRONTEND=noninteractive
apt-get -qq update
# The fork's `wheels` stage list (docker/main/Dockerfile), plus git and ca-certificates.
apt-get -qq install -y --no-install-recommends \
    ca-certificates git wget unzip \
    python3.11 python3.11-dev \
    build-essential cmake pkg-config libgtk-3-dev \
    libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
    libxvidcore-dev libx264-dev libjpeg-dev libpng-dev libtiff-dev \
    gfortran openexr libatlas-base-dev libssl-dev \
    libtbbmalloc2 libtbb-dev libdc1394-dev libopenexr-dev \
    libgstreamer-plugins-base1.0-dev libgstreamer1.0-dev \
    tclsh gcc libopenblas-dev liblapack-dev
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# pip from our frozen get-pip.py (sha256 from the manifest), versions from the build lock.
GETPIP_URL="https://github.com/TroyJ/frigate-build-deps/releases/download/get-pip-2026-11-03/get-pip.py"
GETPIP_SHA256="$(python3 - <<'EOF'
import json
print(next(e["sha256"] for e in json.load(open("manifest.json"))["files"] if e["id"] == "get-pip"))
EOF
)"
wget -q -O /tmp/get-pip.py "$GETPIP_URL"
echo "${GETPIP_SHA256}  /tmp/get-pip.py" | sha256sum -c -
pin() { sed -n "s/^\($1==[^ ]*\).*/\1/p" python/build-cp311-aarch64.lock; }
PIP_BREAK_SYSTEM_PACKAGES=1 python3 /tmp/get-pip.py "$(pin pip)" "$(pin setuptools)" "$(pin wheel)"
python3 -m pip --version

export PIP_BREAK_SYSTEM_PACKAGES=1 PIP_DISABLE_PIP_VERSION_CHECK=1
rm -rf out && mkdir -p out
for set in build wheels dev; do
  lock="python/${set}-cp311-aarch64.lock"
  python3 -m pip install --dry-run --ignore-installed --quiet \
    --require-hashes --report "out/report-${set}.json" -r "$lock"
  python3 -m pip wheel --require-hashes --wheel-dir "out/${set}" -r "$lock"
done
chmod -R a+rwX out
ls out/*/ | wc -l
