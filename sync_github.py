"""
Save everything to GitHub in one step (Akshit's computer):

    python sync_github.py

1. Unpacks any teammate zips (reports_B_....zip, reports_C_....zip) found in
   this folder or in Downloads into teammate_reports/B and teammate_reports/C,
   then moves each zip to imported_zips/ so it is not unpacked twice.
   (Not into run_reports/: the teammates' own laptops write run_reports/B and
   run_reports/C, and their `git pull` would clash with copies from GitHub.)
2. Moves loose console outputs (run*.txt, screen*.txt) into console_logs/.
3. Commits every change (the .env file with your keys is never included),
   pulls any newer code from GitHub, and pushes.

Run it from the VS Code terminal: VS Code then signs in to GitHub for you.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        # a push that waits for a login nobody types (e.g. at 1:31 AM) gives up after 2 minutes
        res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"\n[FAIL] git {' '.join(args)} timed out (probably waiting for a GitHub login).\n"
              "Your records are committed on this computer. Next time, run  python sync_github.py  "
              "while you are at the PC.")
        sys.exit(1)
    if check and res.returncode != 0:
        print(f"\n[FAIL] git {' '.join(args)}\n{res.stdout}{res.stderr}")
        print("Nothing was lost. Screenshot this and send it to Claude.")
        sys.exit(1)
    return res


def import_teammate_zips() -> list[str]:
    done = []
    places = [ROOT, Path.home() / "Downloads"]
    for place in places:
        if not place.is_dir():
            continue
        for z in sorted(place.glob("reports_*.zip")):
            try:
                with zipfile.ZipFile(z) as f:
                    names = [n for n in f.namelist()
                             if n.startswith("run_reports/") and ".." not in n and not n.endswith("/")]
                    for n in names:
                        rel = "".join("." if c in BAD_CHARS else c for c in n[len("run_reports/"):])
                        dest = ROOT / "teammate_reports" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(f.read(n))
            except zipfile.BadZipFile:
                print(f"[WARN] {z.name} is not a valid zip, skipped")
                continue
            (ROOT / "imported_zips").mkdir(exist_ok=True)
            shutil.move(str(z), ROOT / "imported_zips" / z.name)
            done.append(f"{z.name} ({len(names)} files)")
    return done


BAD_CHARS = ':*?"<>|'   # not allowed in Windows file names


def windows_safe_names() -> list[str]:
    """Rename record files whose names Windows cannot create (e.g. the old
    HH:MM format), so teammates can always clone and pull the project."""
    fixed = []
    for folder in ("run_reports", "teammate_reports", "console_logs"):
        base = ROOT / folder
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and any(c in p.name for c in BAD_CHARS):
                new = p.with_name("".join("." if c in BAD_CHARS else c for c in p.name))
                if new.exists():
                    new = new.with_name(new.stem + "_2" + new.suffix)
                p.rename(new)
                fixed.append(f"{p.name} -> {new.name}")
    return fixed


def tidy_console_logs() -> list[str]:
    moved = []
    (ROOT / "console_logs").mkdir(exist_ok=True)
    for pat in ("run*.txt", "screen*.txt"):
        for p in ROOT.glob(pat):
            target = ROOT / "console_logs" / p.name
            if target.exists():
                target = target.with_name(f"{p.stem}_{datetime.now():%H%M%S}{p.suffix}")
            shutil.move(str(p), target)
            moved.append(p.name)
    return moved


def main() -> int:
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        print("[FAIL] This folder is not a git clone.")
        return 1
    if not git("config", "user.email", check=False).stdout.strip():
        print("[FAIL] Git does not know your name and email yet (needed once per computer).\n"
              "Run these two lines, then run  python sync_github.py  again:\n\n"
              '  git config user.name "Your Name"\n'
              '  git config user.email "the-email-of-your-github-account"')
        return 1
    imported = import_teammate_zips()
    if imported:
        print("Imported teammate records:", ", ".join(imported))
    renamed = windows_safe_names()
    if renamed:
        print(f"Renamed {len(renamed)} file(s) so Windows can open them (':' -> '.')")
    moved = tidy_console_logs()
    if moved:
        print("Moved into console_logs/:", ", ".join(moved))

    git("add", "-A")
    # last safety net: never commit the keys file, whatever .gitignore says
    staged = git("diff", "--cached", "--name-only").stdout.split()
    if any(Path(s).name == ".env" for s in staged):
        git("reset", "-q", "HEAD", "--", ".env")
        print("[WARN] .env was about to be committed; removed it from the commit.")
        staged = [s for s in staged if Path(s).name != ".env"]
    if staged:
        msg = f"Run records and updates, {datetime.now():%d %b %Y %H:%M}"
        git("commit", "-q", "-m", msg)
        print(f"Committed {len(staged)} changed file(s): {msg}")
    else:
        print("No local changes to commit.")

    git("pull", "--rebase", "--autostash", "-q", "origin", "main")
    git("push", "-q", "origin", "HEAD:main")
    head = git("log", "-1", "--format=%h %s").stdout.strip()
    print(f"[ OK ] GitHub is up to date: {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
