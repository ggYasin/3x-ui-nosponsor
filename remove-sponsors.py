#!/usr/bin/env python3
"""Remove sponsored content from a 3x-ui source tree.

Usage: python3 remove-sponsors.py <path-to-3x-ui-source> [--repo OWNER/NAME]

Layers, from most generic (survives upstream rewrites) to most specific:

1. DNS guard: adds internal/nosponsor, which makes the panel process unable to
   resolve BLOCKED_DOMAIN or any subdomain, whatever code tries to reach it.
2. URL scrub: every *.sanaei.dev host in Go/frontend source (except plain links
   in LINK_ALLOWLIST) is rewritten to an unresolvable .invalid host, so a new
   hard-coded feed or fallback points nowhere even outside the guard.
3. Component kill: every React component in a file whose path mentions
   sponsor/advert/promo renders nothing, including ones upstream adds later.
4. Known code: the sponsor API always returns an empty list, and the Sponsors
   page is removed from the menu, routes and command palette.
5. Updates (with --repo): the panel's Update button and version check, and the
   install.sh / update.sh / x-ui.sh scripts, download from OWNER/NAME's GitHub
   releases instead of upstream's, so updating can't bring the ads back.

Any change upstream makes that this script can't recognise fails the run
(ERROR) instead of silently shipping ads. Cosmetic misses only WARN.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

BLOCKED_DOMAIN = "sanaei.dev"
LINK_ALLOWLIST = {"docs.sanaei.dev", "donate.sanaei.dev"}  # href links only, never fetched
AD_PATH = re.compile(r"sponsor|advert|promo", re.I)
SKIP_FILE = re.compile(r"(_test\.go|\.test\.tsx?|\.spec\.tsx?|\.stories\.tsx?)$")

args = argparse.ArgumentParser(description="Remove sponsored content from a 3x-ui source tree.")
args.add_argument("root", nargs="?", default=".", help="3x-ui source directory")
args.add_argument("--repo", help="OWNER/NAME whose GitHub releases installs and updates come from")
args = args.parse_args()

here = Path(__file__).resolve().parent
root = Path(args.root).resolve()
errors, warnings = [], []


def log(kind, msg):
    {"ERROR": errors, "WARN": warnings}.get(kind, []).append(msg)
    print(f"{kind:<5} {msg}")


def rewrite(path, fn):
    """Apply fn(text) -> (text, problem). Returns problem or None."""
    old = path.read_text()
    new, problem = fn(old)
    if not problem and new != old:
        path.write_text(new)
    return problem


CODE_EXTS = {".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".sh"}
SKIP_DIRS = {".git", "node_modules", "docs", ".github", "nosponsor", "test", "tests"}


def source_files():
    """Code that ends up in the image (docs, CI and tests excluded)."""
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.suffix in CODE_EXTS and p.is_file() and not SKIP_DIRS & set(rel.parts) and not SKIP_FILE.search(p.name):
            yield p


# --- 1. DNS guard ----------------------------------------------------------
def install_guard():
    module = re.search(r"^module\s+(\S+)", (root / "go.mod").read_text(), re.M)
    hook_dir = root / "internal/config"  # imported by main.go; the most basic package
    if not module or not hook_dir.is_dir():
        return log("ERROR", "guard: go.mod module line or internal/config not found")
    shutil.copytree(here / "overlay", root, dirs_exist_ok=True)
    pkg = re.search(r"^package\s+(\w+)", (hook_dir / "config.go").read_text(), re.M).group(1)
    (hook_dir / "zz_nosponsor.go").write_text(
        f"package {pkg}\n\n// Blocks sponsor/ad domains process-wide. See internal/nosponsor.\n"
        f'import _ "{module.group(1)}/internal/nosponsor"\n'
    )
    log("ok", f"guard: internal/nosponsor installed, *.{BLOCKED_DOMAIN} unresolvable in the panel")


# --- 2. URL scrub ----------------------------------------------------------
HOST = re.compile(r"\b((?:[a-z0-9-]+\.)*" + re.escape(BLOCKED_DOMAIN) + r")\b", re.I)


def scrub_urls():
    count = 0
    for p in source_files():
        def sub(m):
            nonlocal count
            if m.group(1).lower() in LINK_ALLOWLIST:
                return m.group(0)
            count += 1
            return "nosponsor.invalid"
        rewrite(p, lambda s: (HOST.sub(sub, s), None))
    log("ok", f"scrub: {count} {BLOCKED_DOMAIN} host reference(s) rewritten to nosponsor.invalid")


# --- 3. Component kill -----------------------------------------------------
def null_component(s):
    props = "_props: SponsorSlotProps" if re.search(r"\b(interface|type) SponsorSlotProps\b", s) else "_props: Record<string, unknown>"
    stub = f"\n// nosponsor: renders nothing.\nexport default function NoSponsor({props}) {{\n  return null;\n}}\n"
    s2, n = re.subn(r"^export default function (\w+)\s*\(", r"export function Upstream\1(", s, flags=re.M)
    if n == 0:
        s2, n = re.subn(r"^export default (\w+);\s*$", r"export { \1 as Upstream\1 };", s, flags=re.M)
    if n != 1:
        return s, "no recognisable default-exported component"
    return s2 + stub, None


def kill_components():
    front = root / "frontend/src"
    for p in sorted(front.rglob("*.tsx")):
        rel = p.relative_to(root)
        if "node_modules" in p.parts or SKIP_FILE.search(p.name) or "/test/" in f"/{rel}":
            continue
        if not AD_PATH.search(str(p.relative_to(front))) or "export default" not in p.read_text():
            continue
        problem = rewrite(p, null_component)
        # A sponsor-named component we can't neutralise could be a new ad surface.
        log("ERROR" if problem else "ok", f"component: {rel}" + (f": {problem}" if problem else " renders nothing"))


# --- 4. Known code ---------------------------------------------------------
def known_backend():
    rel = "internal/web/service/panel/sponsor.go"
    p = root / rel
    if not p.exists():
        return log("WARN", f"{rel}: gone upstream; relying on the generic layers")

    def fn(s):
        s = re.sub(r'(\bsponsor\w*(?:URL|Base)\s*=\s*)"[^"]*"', r'\1""', s)
        sig = re.compile(r"(func \(\w+ \*PanelService\) GetSponsors\(\) \(\*SponsorList, error\) \{\n)")
        guard = "\treturn &SponsorList{Sponsors: []Sponsor{}}, nil // nosponsor\n"
        s, n = sig.subn(lambda m: m.group(1) + guard, s, count=1)
        return s, None if n else "GetSponsors() signature changed"

    # The original body stays after the early return: unreachable, but it compiles
    # and keeps upstream edits to it from conflicting with anything.
    problem = rewrite(p, fn)
    log("ERROR" if problem else "ok", f"{rel}: " + (problem or "GetSponsors always returns an empty list"))


def drop(rel, pattern, what):
    p = root / rel
    if not p.exists():
        return log("WARN", f"{rel}: not found ({what})")

    def fn(s):
        s, n = re.subn(pattern, "", s, flags=re.M)
        return s, None if n else f"{what} not found"

    problem = rewrite(p, fn)
    log("WARN" if problem else "ok", f"{rel}: " + (problem or f"{what} removed"))


def known_frontend():
    drop("frontend/src/routes.tsx", r"^.*\bSponsorsPage\b.*\n", "Sponsors route")
    drop("frontend/src/layouts/AppSidebar.tsx", r"^.*key: '/sponsors'.*\n", "Sponsors menu item")
    rel = "frontend/src/components/command-palette/CommandPalette.tsx"
    drop(rel, r"\n[ \t]*\{[^{}]*path: '/sponsors',[^{}]*\},", "Sponsors palette entry")
    p = root / rel
    if p.exists() and p.read_text().count("CrownOutlined") == 1:  # only the import left
        rewrite(p, lambda s: (re.sub(r"^[ \t]*CrownOutlined,\n", "", s, flags=re.M), None))


# --- 5. Updates come from this repo ----------------------------------------
UPDATE_SCRIPTS = ("install.sh", "update.sh", "x-ui.sh")
# Script/asset fetches from upstream. Plain links (repo page, wiki, docs) are left alone.
RAW = re.compile(r"https://raw\.githubusercontent\.com/mhsanaei/3x-ui/([^/\s\"'`]+)/([\w.${}-]+)", re.I)
RELEASES = re.compile(r"https://github\.com/mhsanaei/3x-ui/releases\b", re.I)
API = re.compile(r"https://api\.github\.com/repos/mhsanaei/3x-ui/", re.I)


def repoint(s, repo):
    def raw(m):
        ref, name = m.groups()
        if ref in ("main", "master"):  # "the current scripts" -> the latest release's copy
            return f"https://github.com/{repo}/releases/latest/download/{name}"
        return f"https://github.com/{repo}/releases/download/{ref}/{name}"  # pinned to a tag
    s, a = RAW.subn(raw, s)
    s, b = RELEASES.subn(f"https://github.com/{repo}/releases", s)
    s, c = API.subn(f"https://api.github.com/repos/{repo}/", s)
    return s, a + b + c


def repoint_updates(repo):
    if not repo:
        return log("WARN", "updates: no --repo given, installs and updates still come from upstream")
    total = 0
    for p in [root / f for f in UPDATE_SCRIPTS] + [p for p in source_files() if p.suffix == ".go"]:
        if not p.exists():
            log("ERROR", f"updates: {p.relative_to(root)} not found")
            continue
        n = 0

        def fn(s):
            nonlocal n
            s, n = repoint(s, repo)
            return s, None
        rewrite(p, fn)
        total += n
        # These must change: a miss means upstream moved its updater somewhere this script doesn't know.
        if n == 0 and (p.name in UPDATE_SCRIPTS or p.name == "panel.go"):
            log("ERROR", f"updates: no upstream download URLs found in {p.relative_to(root)}")
    log("ok", f"updates: {total} upstream download URL(s) now point at {repo} releases")


# --- checks ----------------------------------------------------------------
def final_checks():
    for p in source_files():
        s = p.read_text()
        for m in HOST.finditer(s):
            if m.group(1).lower() not in LINK_ALLOWLIST:
                log("ERROR", f"{p.relative_to(root)}: still references {m.group(1)}")
        if "net.DefaultResolver.Dial" in s or re.search(r"net\.DefaultResolver\s*=", s):
            log("ERROR", f"{p.relative_to(root)}: replaces the default resolver, the DNS guard may be bypassed")
        if args.repo:
            for rx in (RAW, RELEASES, API):
                for m in rx.finditer(s):
                    log("ERROR", f"{p.relative_to(root)}: still downloads from upstream: {m.group(0)}")


install_guard()
scrub_urls()
kill_components()
known_backend()
known_frontend()
repoint_updates(args.repo)
final_checks()

print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
sys.exit(1 if errors else 0)
