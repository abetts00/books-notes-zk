"""
find_duplicates.py
==================
Finds likely duplicate files across People, Books, and Concepts folders
using fuzzy name matching, then reports them for manual review.

Usage:
    python find_duplicates.py              # default threshold 85
    python find_duplicates.py --threshold 80   # looser matching

Output: duplicates.md in the noteconverter folder
"""

import re
import argparse
from pathlib import Path
from itertools import combinations

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("WARNING: rapidfuzz not installed. pip install rapidfuzz")
    exit(1)

VAULT    = Path(r"C:\Users\abett\OneDrive\Desktop\Obsidian\Vault\Zettlekasten")
OUT_FILE = Path(r"C:\Users\abett\OneDrive\Desktop\noteconverter\duplicates.md")
DIRS     = ["People", "Books", "Concepts"]


def normalize(name: str) -> str:
    """Lowercase, strip punctuation and filler words for comparison."""
    name = name.lower()
    name = re.sub(r"[-_]", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Strip common filler
    for word in ("the", "a", "an", "vs", "and", "of"):
        name = re.sub(rf"\b{word}\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def load_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.md"))


def find_pairs(files: list[Path], threshold: int) -> list[tuple]:
    """Return list of (score, file_a, file_b) above threshold."""
    pairs = []
    names = [(f, normalize(f.stem)) for f in files]
    for (fa, na), (fb, nb) in combinations(names, 2):
        score = fuzz.token_sort_ratio(na, nb)
        if score >= threshold:
            pairs.append((score, fa, fb))
    return sorted(pairs, reverse=True)


def get_backlink_count(path: Path, vault: Path) -> int:
    """Count how many vault files link to this file by name."""
    name = path.stem
    count = 0
    for md in vault.rglob("*.md"):
        if md == path:
            continue
        try:
            if f"[[{name}]]" in md.read_text(encoding="utf-8"):
                count += 1
        except Exception:
            pass
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=85)
    args = parser.parse_args()

    results = {}

    for d in DIRS:
        folder = vault_dir = VAULT / d
        files  = load_files(folder)
        pairs  = find_pairs(files, args.threshold)
        if pairs:
            results[d] = pairs

    # Write report
    lines = [
        "# Duplicate Candidates",
        f"> Fuzzy threshold: {args.threshold} | Folders checked: {', '.join(DIRS)}",
        "> Review each pair and decide: merge, delete, or keep both.",
        "",
    ]

    total = 0
    for folder_name, pairs in results.items():
        lines.append(f"## {folder_name}\n")
        for score, fa, fb in pairs:
            total += 1
            lines.append(f"### {fa.stem}  ↔  {fb.stem}")
            lines.append(f"- **Match score:** {score}%")
            lines.append(f"- **A:** `{fa.relative_to(VAULT)}`")
            lines.append(f"- **B:** `{fb.relative_to(VAULT)}`")
            lines.append(f"- **Action:** [ ] merge  [ ] delete A  [ ] delete B  [ ] keep both")
            lines.append("")

    if total == 0:
        lines.append("_No duplicates found above threshold._")
    else:
        lines.insert(1, f"> **{total} candidate pairs found**\n")

    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Found {total} pairs. Report written to: {OUT_FILE}")
    print(f"\nTop matches:")
    for folder_name, pairs in results.items():
        for score, fa, fb in pairs[:5]:
            print(f"  [{int(score):3d}%] {folder_name}/{fa.stem}  <->  {fb.stem}")


if __name__ == "__main__":
    main()
