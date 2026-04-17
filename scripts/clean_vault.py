"""
clean_vault.py
==============
Run this after any PDF processing session:
    python clean_vault.py

Does three things:
  1. Strips colon subtitles from all wikilinks: [[X: Y]] → [[X]]
  2. Strips colons from frontmatter titles and H1 headings
  3. Deletes any Books stub that has a full Source folder — keeps Books
     as a holding area for unprocessed books only
"""

import re
from pathlib import Path

VAULT = Path(r"C:\Users\abett\OneDrive\Desktop\Obsidian\Vault\Zettlekasten")

# Matches [[Anything: rest of subtitle]] but not timestamp-style links
COLON_LINK = re.compile(r'\[\[([^\]]+?):([^\]]+?)\]\]')


def short_title(name: str) -> str:
    return name.split(":")[0].strip()


def fix_wikilinks(text: str) -> tuple[str, int]:
    """Replace [[X: Y]] with [[X]] throughout text. Returns (new_text, count)."""
    count = 0

    def replacer(m):
        nonlocal count
        replacement = f"[[{m.group(1).strip()}]]"
        if replacement != m.group(0):
            count += 1
        return replacement

    return COLON_LINK.sub(replacer, text), count


def fix_file(path: Path) -> bool:
    """Fix wikilinks, frontmatter title, and H1 heading in a single file."""
    original = path.read_text(encoding="utf-8")
    text = original

    # Fix [[X: Y]] wikilinks
    text, link_count = fix_wikilinks(text)

    # Fix frontmatter title: if it contains a colon, strip the subtitle
    text = re.sub(
        r'^(title:\s*["\']?)([^"\'\n]+:[^\n]+?)(["\']?\s*)$',
        lambda m: m.group(1) + short_title(m.group(2)) + m.group(3),
        text,
        flags=re.MULTILINE,
    )

    # Fix H1 heading: # Title: Subtitle → # Title
    text = re.sub(
        r'^(# )(.+?): .+$',
        lambda m: m.group(1) + m.group(2),
        text,
        flags=re.MULTILINE,
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def fold_books_into_sources():
    """Delete any Books stub whose book already has a full Source folder."""
    sources_dir = VAULT / "Sources"
    books_dir   = VAULT / "Books"

    # A source folder is "complete" if it contains a MOC file with the same name
    processed = {
        f.parent.name.lower()
        for f in sources_dir.rglob("*.md")
        if f.stem.lower() == f.parent.name.lower()
    }

    deleted = []
    for stub in sorted(books_dir.glob("*.md")):
        if stub.stem.lower() in processed:
            stub.unlink()
            deleted.append(stub.name)

    if deleted:
        print(f"Folded {len(deleted)} Books stubs into Sources:")
        for f in deleted:
            print(f"  {f}")
    else:
        print("Books is clean — no stubs to fold.")


def main():
    # 1. Fix colon wikilinks, titles, headings
    fixed_files = []
    for md_file in VAULT.rglob("*.md"):
        if fix_file(md_file):
            fixed_files.append(md_file.relative_to(VAULT))

    if fixed_files:
        print(f"Fixed {len(fixed_files)} files with colon issues:")
        for f in sorted(fixed_files):
            print(f"  {f}")
    else:
        print("Vault is clean — no colon wikilinks found.")

    print()

    # 2. Remove Books stubs superseded by Source folders
    fold_books_into_sources()


if __name__ == "__main__":
    main()
