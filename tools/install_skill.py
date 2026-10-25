"""Install the eat-embedded-tool skill into agent skill directories.

Usage:  python tools/install_skill.py [--force]
Copies skills/eat-embedded-tool to (existing) skill roots:
  ~/.claude/skills, ~/.codex/skills, <project>/.zcode/skills, <project>/.cursor/skills
"""
import argparse
import shutil
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "skills" / "eat-embedded-tool"
PROJECT = Path(__file__).resolve().parent.parent

TARGETS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".codex" / "skills",
    PROJECT / ".zcode" / "skills",
    PROJECT / ".cursor" / "skills",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for root in TARGETS:
        dst = root / SRC.name
        marker = root.parent  # show which root
        try:
            if dst.exists():
                if not args.force:
                    print(f"skip (exists): {dst}")
                    continue
                shutil.rmtree(dst)
            root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SRC, dst)
            print(f"installed: {dst}")
        except Exception as e:
            print(f"failed: {marker} -> {e}")


if __name__ == "__main__":
    main()
