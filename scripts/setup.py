#!/usr/bin/env python3
"""
First-run setup for book-notes-zk.

Creates the full vault directory structure, drops CLAUDE.md at the vault root,
initializes empty tracking files, and verifies dependencies.

Usage:
  python scripts/setup.py --vault "C:/path/to/your/obsidian/vault"
  python scripts/setup.py --vault ~/Notes/BookNotes
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.parent  # repo root

VAULT_DIRS = [
    "raw/pdfs/philosophers-notes",
    "raw/pdfs/shortform",
    "raw/pdfs/readingraphics",
    "raw/pdfs/getabstract",
    "raw/pdfs/other",
    "raw/clippings",
    "raw/personal-notes",
    "Sources",
    "Concepts",
    "People",
    "Books",
    "permanent/insights",
    "permanent/projects",
    "scripts",
    ".claude/skills/book-notes-zk/references",
]

REQUIRED_PACKAGES = ["anthropic", "pymupdf", "rapidfuzz", "mcp"]


def check_python():
    if sys.version_info < (3, 9):
        print(f"  ERROR: Python 3.9+ required (you have {sys.version})")
        return False
    print(f"  Python {sys.version.split()[0]}")
    return True


def check_packages():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg if pkg != "pymupdf" else "fitz")
            print(f"  {pkg}")
        except ImportError:
            print(f"  MISSING: {pkg}")
            missing.append(pkg)
    return missing


def check_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.startswith("sk-ant-"):
        print(f"  ANTHROPIC_API_KEY set")
        return True
    print("  WARNING: ANTHROPIC_API_KEY not set")
    print("  Set it before running the pipeline:")
    print("    Windows: set ANTHROPIC_API_KEY=sk-ant-...")
    print("    Mac/Linux: export ANTHROPIC_API_KEY=sk-ant-...")
    return False


def create_vault(vault_path: Path):
    for d in VAULT_DIRS:
        (vault_path / d).mkdir(parents=True, exist_ok=True)
    print(f"  Created {len(VAULT_DIRS)} directories")


def copy_claude_md(vault_path: Path):
    src = HERE / "CLAUDE.md"
    dst = vault_path / "CLAUDE.md"
    if dst.exists():
        print(f"  CLAUDE.md already exists, skipping")
        return
    if src.exists():
        shutil.copy(src, dst)
        print(f"  Copied CLAUDE.md to vault root")
    else:
        print(f"  WARNING: CLAUDE.md not found in repo root")


def init_tracking_files(vault_path: Path):
    log_path = vault_path / "processing_log.json"
    if not log_path.exists():
        log_path.write_text(json.dumps({
            "processed": {},
            "stats": {"total_processed": 0, "total_failed": 0},
            "last_run": None
        }, indent=2))
        print("  Created processing_log.json")
    else:
        print("  processing_log.json already exists, skipping")

    dict_path = vault_path / "concepts_dictionary.json"
    if not dict_path.exists():
        dict_path.write_text(json.dumps({}, indent=2))
        print("  Created concepts_dictionary.json")
    else:
        print("  concepts_dictionary.json already exists, skipping")


def install_skill(vault_path: Path):
    skill_src = HERE / "SKILL.md"
    refs_src = HERE / "references"
    scripts_src = HERE / "scripts"
    skill_dst = vault_path / ".claude/skills/book-notes-zk"

    if skill_src.exists():
        shutil.copy(skill_src, skill_dst / "SKILL.md")
    if refs_src.exists():
        shutil.copytree(refs_src, skill_dst / "references", dirs_exist_ok=True)
    if scripts_src.exists():
        shutil.copytree(scripts_src, skill_dst / "scripts", dirs_exist_ok=True)
    print(f"  Installed Claude Code skill to .claude/skills/book-notes-zk/")


def print_next_steps(vault_path: Path):
    print("""
Next steps:
  1. Drop your PDF book summaries into:
       raw/pdfs/philosophers-notes/   ← Philosopher's Notes (Brian Johnson)
       raw/pdfs/shortform/            ← Shortform
       raw/pdfs/readingraphics/       ← ReadingGraphics
       raw/pdfs/getabstract/          ← getAbstract
       raw/pdfs/other/                ← anything else

  2. Run the pipeline (auto-detects format):
       python scripts/pdf_to_obsidian.py raw/pdfs/philosophers-notes/*.pdf --vault . --resume

  3. Enrich concept notes with Claude:
       python scripts/enrich_concepts.py --vault . --min-sources 3

  4. Open the vault in Obsidian and explore your knowledge graph.

  Optional — MCP server for Claude Desktop / Cursor:
    See mcp_server/server.py and add to your claude_desktop_config.json
""")


def main():
    parser = argparse.ArgumentParser(description="Set up a book-notes-zk vault")
    parser.add_argument("--vault", required=True, help="Path to your Obsidian vault")
    parser.add_argument("--skip-install", action="store_true",
                        help="Skip installing missing packages")
    args = parser.parse_args()

    vault_path = Path(args.vault).expanduser().resolve()

    print(f"\n{'='*55}")
    print(f"  book-notes-zk setup")
    print(f"  Vault: {vault_path}")
    print(f"{'='*55}\n")

    # 1. Python version
    print("Checking Python...")
    if not check_python():
        sys.exit(1)

    # 2. Dependencies
    print("\nChecking dependencies...")
    missing = check_packages()
    if missing and not args.skip_install:
        print(f"\n  Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        print("  Done.")
    elif missing:
        print(f"\n  Run: pip install {' '.join(missing)}")

    # 3. API key
    print("\nChecking API key...")
    check_api_key()

    # 4. Create vault structure
    print(f"\nCreating vault structure at {vault_path}...")
    create_vault(vault_path)
    copy_claude_md(vault_path)
    init_tracking_files(vault_path)
    install_skill(vault_path)

    print(f"\n{'='*55}")
    print(f"  Setup complete.")
    print(f"{'='*55}")
    print_next_steps(vault_path)


if __name__ == "__main__":
    main()
