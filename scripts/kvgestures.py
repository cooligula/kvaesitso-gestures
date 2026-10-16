#!/usr/bin/env python3
"""Build helper for kvaesitso-gestures. Standard library only (Python 3.11+).

Subcommands:
  bump       move the pin in upstream.toml to the newest full upstream release
  check      fetch the pinned upstream source and make sure every patch applies
  plan       decide whether a release is needed and which version it gets
  fetch      shallow-clone the pinned upstream source into work/kvaesitso
  prepare    apply the patches and set the version of a fetched source tree
  obtainium  print the Obtainium links; --write refreshes the README block and obtainium-app.json
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "upstream.toml"
PATCHES = ROOT / "patches"
WORK = ROOT / "work" / "kvaesitso"
BUILD_MARKER = "Build-Input:"
META_NAME = "kvgestures-meta.json"


def load():
    with CONFIG.open("rb") as f:
        return tomllib.load(f)


def run(cmd, **kw):
    kw.setdefault("check", True)
    return subprocess.run(cmd, text=True, **kw)


def out(cmd, **kw):
    return run(cmd, stdout=subprocess.PIPE, **kw).stdout.strip()


def set_output(**values):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")


def patch_files():
    return sorted(PATCHES.glob("*.patch"))


def upstream_url(cfg):
    return f"https://github.com/{cfg['upstream']['slug']}"


def version_of(tag):
    """'v1.41.0' -> (1, 41, 0); None for tags that are not plain release versions."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", tag)
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def input_hash(cfg):
    """Hash of everything that decides the contents of a build."""
    h = hashlib.sha256()
    h.update((ROOT / "build-rev.txt").read_bytes())
    h.update(json.dumps({k: cfg[k] for k in ("upstream", "build", "app")}, sort_keys=True).encode())
    for p in patch_files():
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- fetch / patch

def fetch_into(dest, cfg):
    dest.mkdir(parents=True)
    run(["git", "init", "-q"], cwd=dest)
    run(["git", "remote", "add", "origin", upstream_url(cfg)], cwd=dest)
    run(["git", "fetch", "-q", "--depth", "1", "origin", cfg["upstream"]["sha"]], cwd=dest)
    run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest)


def apply_patches(src):
    """Apply every patch in order. Returns (applied, failed) lists of file names."""
    applied, failed = [], []
    for patch in patch_files():
        try:
            run(["git", "apply", "--check", str(patch)], cwd=src, stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"patch {patch.name} does not apply:\n{e.stdout}")
            failed.append(patch.name)
            continue
        run(["git", "apply", str(patch)], cwd=src)
        applied.append(patch.name)
    return applied, failed


def cmd_fetch(args):
    cfg = load()
    if WORK.exists():
        sys.exit(f"{WORK} already exists")
    fetch_into(WORK, cfg)
    print(f"fetched {upstream_url(cfg)} at {cfg['upstream']['sha']} ({cfg['upstream']['tag']})")


def cmd_check(args):
    cfg = load()
    tmp = Path(tempfile.mkdtemp(prefix="kvgestures-"))
    try:
        src = tmp / "src"
        fetch_into(src, cfg)
        actual = out(["git", "rev-parse", "HEAD"], cwd=src)
        print(f"{cfg['upstream']['tag']} -> {actual}")
        applied, failed = apply_patches(src)
        for name in applied:
            print(f"ok      {name}")
        for name in failed:
            print(f"FAILED  {name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    set_output(patches_ok="false" if failed else "true",
               patches_failed=",".join(failed))
    if failed and not args.soft:
        sys.exit(1)


def sub_once(text, pattern, repl, what):
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        sys.exit(f"prepare: could not find {what}; did the upstream build file change?")
    return new


def cmd_prepare(args):
    cfg = load()
    revision = int(args.revision)
    applied, failed = apply_patches(WORK)
    if failed:
        sys.exit("prepare: patches do not apply: " + ", ".join(failed))

    build_file = WORK / cfg["build"]["build_file"]
    text = build_file.read_text()

    m = re.search(r'versionName\s*=\s*"([^"]*)"', text)
    if not m:
        sys.exit("prepare: could not find versionName")
    upstream_version = m.group(1)
    expected = cfg["upstream"]["tag"].lstrip("v")
    if upstream_version != expected:
        print(f"warning: build file says {upstream_version}, pinned tag is {cfg['upstream']['tag']}")

    m = re.search(r'VERSION_CODE_OVERRIDE"\)\?\.toIntOrNull\(\)\s*\?:\s*(\d+)', text)
    if not m:
        sys.exit("prepare: could not find the versionCode; did the upstream build file change?")
    version_code = int(m.group(1)) + revision
    if version_code >= 2**31 - 1:
        sys.exit(f"prepare: versionCode {version_code} does not fit an int")
    version_name = f"{upstream_version}-gestures.{revision}"

    text = sub_once(text, r'(VERSION_CODE_OVERRIDE"\)\?\.toIntOrNull\(\)\s*\?:\s*)\d+',
                    lambda mm: f"{mm.group(1)}{version_code}", "versionCode")
    text = sub_once(text, r'(versionName\s*=\s*)"[^"]*"',
                    lambda mm: f'{mm.group(1)}"{version_name}"', "versionName")
    build_file.write_text(text)

    meta = {
        "title": cfg["app"]["title"],
        "application_id": cfg["app"]["application_id"],
        "upstream_slug": cfg["upstream"]["slug"],
        "upstream_tag": cfg["upstream"]["tag"],
        "upstream_sha": cfg["upstream"]["sha"],
        "upstream_version": upstream_version,
        "revision": revision,
        "version_code": version_code,
        "version_name": version_name,
        "tag": version_name,
        "input": input_hash(cfg),
        "patches": applied,
    }
    (WORK / META_NAME).write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


# --------------------------------------------------------------------------- planning

def release_info(repo):
    """{tag: body} of the releases of this repository, via gh. Empty when gh is unavailable."""
    try:
        raw = out(["gh", "release", "list", "--repo", repo, "--limit", "200", "--json", "tagName"],
                  stderr=subprocess.DEVNULL)
        tags = [r["tagName"] for r in json.loads(raw or "[]")]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    info = {}
    for tag in tags:
        try:
            info[tag] = out(["gh", "release", "view", tag, "--repo", repo, "--json", "body",
                             "-q", ".body"], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            info[tag] = ""
    return info


def cmd_plan(args):
    cfg = load()
    version = cfg["upstream"]["tag"].lstrip("v")
    digest = input_hash(cfg)
    pattern = re.compile(rf"^{re.escape(version)}-gestures\.(\d+)$")
    releases = release_info(args.repo) if args.repo else {}
    revisions = {int(m.group(1)): tag for tag in releases if (m := pattern.match(tag))}

    latest = max(revisions) if revisions else 0
    previous_input = None
    if latest:
        m = re.search(rf"{BUILD_MARKER}\s*(\w+)", releases[revisions[latest]])
        previous_input = m.group(1) if m else None
    needed = args.all or args.force or previous_input != digest
    revision = latest + 1
    result = {"needed": needed, "revision": revision, "input": digest,
              "version_name": f"{version}-gestures.{revision}", "java": cfg["build"]["java"]}
    print(json.dumps(result))
    set_output(needed=str(needed).lower(), revision=revision, java=cfg["build"]["java"],
               version_name=result["version_name"])


# --------------------------------------------------------------------------- bump

def github_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def resolve_tag(cfg, tag):
    url = upstream_url(cfg)
    lines = out(["git", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"]).splitlines()
    refs = {}
    for line in lines:
        sha, ref = line.split()
        refs[ref] = sha
    sha = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not sha:
        sys.exit(f"bump: tag {tag} not found in {url}")
    return sha


def cmd_bump(args):
    cfg = load()
    # /releases/latest skips drafts and pre-releases: only full releases move the pin.
    latest = github_json(f"https://api.github.com/repos/{cfg['upstream']['slug']}/releases/latest")
    tag = latest["tag_name"]
    current = cfg["upstream"]["tag"]
    new_v, cur_v = version_of(tag), version_of(current)
    if new_v is None:
        sys.exit(f"bump: cannot parse the version of tag {tag}")
    changed = cur_v is None or new_v > cur_v
    if not changed:
        print(f"no changes ({current} is up to date; upstream latest is {tag})")
        set_output(changed="false")
        return
    sha = resolve_tag(cfg, tag)
    text = CONFIG.read_text()
    text = sub_once(text, r'(?m)^(tag\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{tag}"', "tag")
    text = sub_once(text, r'(?m)^(sha\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{sha}"', "sha")
    CONFIG.write_text(text)
    print(f"{current} -> {tag} ({sha})")
    set_output(changed="true", tag=tag, previous=current, sha=sha)


# --------------------------------------------------------------------------- obtainium

README = ROOT / "README.md"
LINK_START, LINK_END = "<!-- obtainium:start -->", "<!-- obtainium:end -->"
REDIRECT = "https://apps.obtainium.imranr.dev/redirect?r="


def default_repo():
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = out(["git", "remote", "get-url", "origin"], cwd=ROOT)
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit("obtainium: cannot work out OWNER/REPO, pass --repo")
    return m.group(1)


def obtainium_entry(cfg, repo):
    """An Obtainium app config. additionalSettings is a JSON string, as Obtainium stores it."""
    settings = {
        "includePrereleases": False,
        "fallbackToOlderReleases": True,
        "apkFilterRegEx": "\\.apk$",
        "autoApkFilterByArch": False,
    }
    return {
        "id": cfg["app"]["application_id"],
        "url": f"https://github.com/{repo}",
        "author": repo.split("/")[0],
        "name": f"{cfg['app']['title']} (gestures)",
        "preferredApkIndex": 0,
        "additionalSettings": json.dumps(settings),
    }


def app_link(entry):
    """Link through Obtainium's own redirect page. It decodes `r` once and then decodes the JSON
    a second time, so the JSON is encoded twice. It only accepts obtainium://app/ and obtainium://add/."""
    compact = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
    inner = "obtainium://app/" + urllib.parse.quote(compact, safe=":,/")
    return REDIRECT + urllib.parse.quote(inner, safe=":,/")


def cmd_obtainium(args):
    cfg = load()
    repo = args.repo or default_repo()
    entry = obtainium_entry(cfg, repo)
    link = app_link(entry)
    print(link)
    if not args.write:
        return
    (ROOT / "obtainium-app.json").write_text(json.dumps({"apps": [entry]}, indent=2) + "\n")
    text = README.read_text()
    if LINK_START not in text or LINK_END not in text:
        sys.exit("obtainium: README.md has no obtainium markers")
    head, rest = text.split(LINK_START, 1)
    tail = rest.split(LINK_END, 1)[1]
    block = "\n".join([
        LINK_START,
        "<!-- generated by `python3 scripts/kvgestures.py obtainium --write`; do not edit by hand -->",
        f"[Add Kvaesitso (gestures) to Obtainium]({link})",
        LINK_END,
    ])
    README.write_text(head + block + tail)
    print("wrote README.md and obtainium-app.json")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("bump")
    s.set_defaults(fn=cmd_bump)

    s = sp.add_parser("check")
    s.add_argument("--soft", action="store_true", help="report failing patches without a failing exit code")
    s.set_defaults(fn=cmd_check)

    s = sp.add_parser("plan")
    s.add_argument("--repo", help="owner/name, to compare with the existing releases")
    s.add_argument("--all", action="store_true", help="a build is needed whatever the releases say")
    s.add_argument("--force", action="store_true", help="rebuild even when the inputs did not change")
    s.set_defaults(fn=cmd_plan)

    s = sp.add_parser("fetch")
    s.set_defaults(fn=cmd_fetch)

    s = sp.add_parser("prepare")
    s.add_argument("--revision", default="1", help="patch revision of this upstream version")
    s.set_defaults(fn=cmd_prepare)

    s = sp.add_parser("obtainium")
    s.add_argument("--repo", help="owner/name; default: GITHUB_REPOSITORY or the origin remote")
    s.add_argument("--write", action="store_true")
    s.set_defaults(fn=cmd_obtainium)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
