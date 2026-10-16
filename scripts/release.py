#!/usr/bin/env python3
"""Publish the signed APK as a GitHub release: scripts/release.py <signed-dir> <owner/repo>

<signed-dir> holds the signed APK and meta.json. The release body carries a Build-Input marker
that `kvgestures.py plan` uses to skip builds whose inputs did not change.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

signed_dir, repo = Path(sys.argv[1]), sys.argv[2]
meta = json.loads((signed_dir / "meta.json").read_text())
apks = sorted(signed_dir.glob("*.apk"))
if len(apks) != 1:
    sys.exit(f"{signed_dir}: expected one signed APK, found {len(apks)}")
apk = apks[0]
digest = hashlib.sha256(apk.read_bytes()).hexdigest()
sums = apk.with_name(apk.name + ".sha256")
sums.write_text(f"{digest}  {apk.name}\n")

notes = (
    f"{meta['title']} {meta['upstream_version']} with the gesture patches (revision {meta['revision']})\n\n"
    f"Application id: `{meta['application_id']}`\n"
    f"Upstream: [{meta['upstream_slug']}](https://github.com/{meta['upstream_slug']}/releases/tag/{meta['upstream_tag']})"
    f" {meta['upstream_tag']} @ `{meta['upstream_sha']}`\n"
    f"APK SHA-256: `{digest}`\n\n"
)
if meta.get("variant") == "probe":
    notes += (
        "**Probe build**: it logs gesture and lifecycle events to a file for diagnosis. Open the "
        "\"Probe log\" app icon to share the log. Obtainium does not follow it.\n\n"
    )
notes += "Patches applied:\n" + "".join(f"- `{p}`\n" for p in meta["patches"])
notes += f"\nBuild-Input: {meta['input']}\n"
with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as nf:
    nf.write(notes)
title = f"{meta['title']} {meta['version_name']}"
cmd = ["gh", "release", "create", meta["tag"], str(apk), str(sums),
       "--repo", repo, "--title", title, "--notes-file", nf.name]
if meta.get("prerelease"):
    cmd.append("--prerelease")  # Obtainium skips pre-releases unless asked to include them
subprocess.run(cmd, check=True)
print(f"released {meta['tag']}")
