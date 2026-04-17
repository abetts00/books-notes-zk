#!/usr/bin/env python3
"""
Fix two Obsidian graph issues:
1. Remove redundant type-tags (tags: - concept/person/book) from entity files
2. Delete Books/ stubs that have a corresponding Sources/ folder

Usage:
  python scripts/fix_graph_issues.py --vault "C:/path/to/vault" --dry-run
  python scripts/fix_graph_issues.py --vault "C:/path/to/vault"
"""

import argparse
import re
import sys
from pathlib import Path


def strip_type_tag(content: str, tag: str) -> tuple[str, bool]:
    """Remove `  - tag` line from frontmatter tags block. Returns (new_content, changed)."""
    pattern = re.compile(r'^(\s*- ' + re.escape(tag) + r'\s*\n)', re.MULTILINE)
    new_content, count = pattern.subn('', content)
    return new_content, count > 0


def fix_redundant_tags(vault: Path, dry_run: bool) -> dict:
    stats = {"concepts": 0, "people": 0, "books_tags": 0, "errors": 0}

    mapping = [
        (vault / "Concepts", "concept"),
        (vault / "People", "person"),
        (vault / "Books", "book"),
    ]

    for folder, tag in mapping:
        if not folder.exists():
            print(f"  Skipping {folder} (not found)")
            continue
        files = list(folder.glob("*.md"))
        changed = 0
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
                new_content, did_change = strip_type_tag(content, tag)
                if did_change:
                    if not dry_run:
                        f.write_text(new_content, encoding="utf-8")
                    changed += 1
            except Exception as e:
                print(f"  ERROR {f.name}: {e}")
                stats["errors"] += 1

        key = {"concept": "concepts", "person": "people", "book": "books_tags"}[tag]
        stats[key] = changed
        print(f"  {folder.name}/: {changed}/{len(files)} files {'would be' if dry_run else ''} updated")

    return stats


def delete_duplicate_book_stubs(vault: Path, dry_run: bool) -> dict:
    books_dir = vault / "Books"
    sources_dir = vault / "Sources"

    if not books_dir.exists() or not sources_dir.exists():
        print("  Books/ or Sources/ not found, skipping")
        return {"deleted": 0, "skipped": 0}

    source_folders = {f.name.lower() for f in sources_dir.iterdir() if f.is_dir()}
    book_stubs = list(books_dir.glob("*.md"))

    deleted = 0
    skipped = 0
    duplicates = []

    for stub in book_stubs:
        stem_lower = stub.stem.lower()
        if stem_lower in source_folders:
            duplicates.append(stub)
            if not dry_run:
                stub.unlink()
            deleted += 1
        else:
            skipped += 1

    print(f"  Found {len(duplicates)} duplicate Books/ stubs with matching Sources/ folder:")
    for d in sorted(duplicates, key=lambda x: x.name):
        action = "  [would delete]" if dry_run else "  [deleted]"
        print(f"    {action} Books/{d.name}")
    print(f"  Kept {skipped} Books/ stubs with no matching source")

    return {"deleted": deleted, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="Fix Obsidian vault graph issues")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.exists():
        print(f"ERROR: Vault not found: {vault}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n{'='*55}")
    print(f"  fix_graph_issues [{mode}]")
    print(f"  Vault: {vault}")
    print(f"{'='*55}\n")

    print("Issue 1: Stripping redundant type-tags...")
    tag_stats = fix_redundant_tags(vault, args.dry_run)

    print("\nIssue 2: Deleting duplicate Books/ stubs...")
    dup_stats = delete_duplicate_book_stubs(vault, args.dry_run)

    total_tag = sum(tag_stats[k] for k in ("concepts", "people", "books_tags"))
    print(f"\n{'='*55}")
    print(f"  Summary{' (DRY RUN)' if args.dry_run else ''}:")
    print(f"  - Type-tags stripped: {total_tag} files")
    print(f"  - Duplicate stubs deleted: {dup_stats['deleted']}")
    print(f"  - Books/ stubs kept: {dup_stats['skipped']}")
    if tag_stats["errors"]:
        print(f"  - Errors: {tag_stats['errors']}")
    print(f"{'='*55}\n")

    if args.dry_run:
        print("Re-run without --dry-run to apply changes.\n")


if __name__ == "__main__":
    main()
