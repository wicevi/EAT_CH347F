"""Install skills from the project skills/ directory into agent skill roots.

Usage:  python tools/install_skill.py [name ...] [--force]
Without names, installs every skill under skills/. Copies each to:
  ~/.claude/skills, ~/.codex/skills, <project>/.zcode/skills, <project>/.cursor/skills
"""
import argparse
import shutil
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
PROJECT = Path(__file__).resolve().parent.parent

TARGETS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".codex" / "skills",
    PROJECT / ".zcode" / "skills",
    PROJECT / ".cursor" / "skills",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*",
                    help="skill names to install (default: all under skills/)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    sources = [SKILLS_DIR / n for n in args.names] if args.names else \
        sorted(p for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").exists())

    if args.list:
        for s in sources:
            print(s.name)
        return

    for src in sources:
        if not (src / "SKILL.md").exists():
            print(f"skip (no SKILL.md): {src}")
            continue
        for root in TARGETS:
            dst = root / src.name
            try:
                if dst.exists():
                    if not args.force:
                        print(f"skip (exists): {dst}")
                        continue
                    shutil.rmtree(dst)
                root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst)
                print(f"installed: {dst}")
            except Exception as e:
                print(f"failed: {root.parent} -> {e}")


if __name__ == "__main__":
    main()
