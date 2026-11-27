"""
Release notes for GitHub Releases, from CHANGELOG.md (and, for versions older than the
changelog, the commit messages between tags).

A release's notes cover every version since the previous release: v2.4.6 also lists
2.4.3–2.4.5, which were never released on their own. A stable release counts from the
previous stable release, so it includes any testing builds in between.

    python release_notes.py body v2.4.10        # the full release body (notes + install), to stdout
    python release_notes.py backfill [--dry-run]  # add notes to releases that don't have any

Runs in GitHub Actions with GITHUB_TOKEN and GITHUB_REPOSITORY (see .github/workflows).
"""

import json, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the repo root
REPO = os.environ.get("GITHUB_REPOSITORY", "VitalBio/swqa-test-tracking")
MARK = "## What's new"
INSTALL = os.path.join(HERE, ".github", "release_install.md")


def vtuple(v):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


# ── sources ───────────────────────────────────────────────────────────────────

def changelog():
    """[(version tuple, heading, text)] from CHANGELOG.md."""
    with open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    out = []
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        head, body = m.group(1).strip(), m.group(2).strip()
        v = vtuple(head)
        if v and "and earlier" not in head:
            out.append((v, head, body))
    return out

def commits(prev, tag):
    """Commit subjects between two tags, as a bullet list (for versions before the changelog)."""
    rng = f"{prev}..{tag}" if prev else tag
    try:
        subjects = subprocess.run(["git", "log", "--format=%s", "--reverse", rng], cwd=HERE,
                                  capture_output=True, text=True, check=True).stdout.splitlines()
    except subprocess.CalledProcessError:
        return ""
    lines = []
    for s in subjects:
        if s.startswith("Merge ") or not s.strip() or re.search(
                r"README|INSTALL\.md|CHANGELOG|release notes|workflow|Release builds|install steps", s, re.I):
            continue
        s = re.sub(r"^v\d+\.\d+\.\d+:\s*", "", s).strip()
        if s:
            lines.append(f"- {s[0].upper()}{s[1:]}")
    return "\n".join(lines)


# ── GitHub ────────────────────────────────────────────────────────────────────

def api(path, method="GET", data=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method,
                                 data=json.dumps(data).encode() if data is not None else None)
    req.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "null", strict=False)

def releases():
    out, page = [], 1
    while True:
        got = api(f"/releases?per_page=100&page={page}")
        if not got:
            return out
        out += got
        page += 1


# ── notes ─────────────────────────────────────────────────────────────────────

def previous(tag, prerelease, rels):
    """The release this one follows: the previous stable one (any one, for a testing build)."""
    me = vtuple(tag)
    older = [r for r in rels if vtuple(r["tag_name"]) and vtuple(r["tag_name"]) < me
             and (prerelease or not r["prerelease"])]
    return max(older, key=lambda r: vtuple(r["tag_name"]))["tag_name"] if older else None

def notes(tag, prev):
    """Markdown "What's new" for a release that follows `prev`."""
    me, lo = vtuple(tag), vtuple(prev) if prev else (0, 0, 0)
    secs = [s for s in changelog() if lo < s[0] <= me]
    if secs:
        if len(secs) == 1 and secs[0][0] == me:
            body = secs[0][2]
        else:
            body = "\n\n".join(f"### {head}\n{text}" for _, head, text in secs)
    else:
        body = ("First release." if not prev else commits(prev, tag) or "Small fixes.")
    since = f" (since {prev})" if prev and len(secs) != 1 else ""
    return f"{MARK} in {tag}{since}\n\n{body}\n"

def body(tag, prerelease=False):
    rels = releases()
    with open(INSTALL, encoding="utf-8") as f:
        install = f.read().strip()
    return notes(tag, previous(tag, prerelease, rels)) + "\n---\n\n" + install + "\n"

def backfill(dry_run=False):
    rels = releases()
    for r in sorted(rels, key=lambda r: vtuple(r["tag_name"]) or (0, 0, 0)):
        tag, old = r["tag_name"], (r.get("body") or "").strip()
        if not vtuple(tag) or MARK in old:
            continue
        if old and (not old.startswith("## Install") or "release notes" in old.lower()):
            print(f"{tag}: has its own notes, left as is")
            continue
        new = notes(tag, previous(tag, r["prerelease"], rels)) + ("\n---\n\n" + old if old else "")
        if dry_run:
            print(f"===== {tag}\n{new.split(chr(10) + '---' + chr(10))[0].strip()}\n")
        else:
            api(f"/releases/{r['id']}", "PATCH", {"body": new})
            print(f"{tag}: notes added")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "body" and len(sys.argv) > 2:
        sys.stdout.write(body(sys.argv[2], "--prerelease" in sys.argv))
    elif cmd == "backfill":
        backfill("--dry-run" in sys.argv)
    else:
        print(__doc__)
        sys.exit(2)
