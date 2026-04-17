#!/usr/bin/env python3
"""
Restructures all concept files in the vault to the new template.

Changes:
  - Adds maturity + source_count to frontmatter
  - Replaces '## Definition' with '## Definitions from Sources'
  - Replaces '## Why It Matters' with '## Cross-Source Synthesis' + '## My Synthesis'
  - Leaves all other sections (Related Concepts, Sources) intact

Usage:
  python update_concept_template.py --vault "C:/path/to/vault" [--dry-run]
"""

import os
import re
import argparse

def count_sources(text):
    if "## Sources" not in text:
        return 0
    sources_section = text.split("## Sources")[-1]
    return len(re.findall(r'\[\[', sources_section))


def maturity_from_count(n):
    if n >= 15:
        return "evergreen"
    if n >= 5:
        return "developing"
    return "stub"


def update_file(path, dry_run=False):
    text = open(path, encoding="utf-8").read()

    # Already updated if it has the new sections
    if "## Definitions from Sources" in text:
        return False

    source_count = count_sources(text)
    maturity = maturity_from_count(source_count)

    # Update frontmatter: insert maturity + source_count after 'type: concept'
    new_text = re.sub(
        r'(type: concept\n)',
        f'type: concept\nmaturity: {maturity}\nsource_count: {source_count}\n',
        text,
        count=1
    )

    # Replace ## Definition with ## Definitions from Sources
    new_text = new_text.replace("## Definition\n", "## Definitions from Sources\n")

    # Replace ## Why It Matters with ## Cross-Source Synthesis + ## My Synthesis
    new_text = new_text.replace(
        "## Why It Matters\n",
        "## Cross-Source Synthesis\n\n## My Synthesis\n"
    )

    if not dry_run:
        open(path, "w", encoding="utf-8").write(new_text)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="C:/Users/abett/OneDrive/Desktop/Obsidian/Vault/Zettlekasten")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    concepts_dir = os.path.join(args.vault, "Concepts")
    updated = 0
    skipped = 0

    for fname in sorted(os.listdir(concepts_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(concepts_dir, fname)
        if update_file(path, dry_run=args.dry_run):
            updated += 1
        else:
            skipped += 1

    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {updated} concept files. Skipped {skipped} (already updated).")


if __name__ == "__main__":
    main()
