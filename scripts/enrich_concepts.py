#!/usr/bin/env python3
"""
Enriches concept files by extracting what each source note says about the concept.
Uses Claude API (Sonnet) to intelligently pull definitions and key passages.

Usage:
  python enrich_concepts.py --vault "C:/path/to/vault" [--min-sources 3] [--limit 20] [--dry-run]

By default processes concepts with 3+ sources, up to 20 at a time.
Safe to re-run — skips concepts that already have content in Definitions from Sources.
"""

import os
import re
import json
import time
import argparse

import anthropic

VAULT = "C:/Users/abett/OneDrive/Desktop/Obsidian/Vault/Zettlekasten"


def get_source_note(vault, book_name):
    """Find and read a source note for a book. Returns content or None."""
    sources_dir = os.path.join(vault, "Sources")
    # Try exact folder name match
    book_dir = os.path.join(sources_dir, book_name)
    if os.path.isdir(book_dir):
        note_path = os.path.join(book_dir, f"{book_name}.md")
        if os.path.exists(note_path):
            return open(note_path, encoding="utf-8").read()
    # Fuzzy: find first folder that starts with the book name
    if os.path.isdir(sources_dir):
        for folder in os.listdir(sources_dir):
            if folder.lower() == book_name.lower():
                note_path = os.path.join(sources_dir, folder, f"{folder}.md")
                if os.path.exists(note_path):
                    return open(note_path, encoding="utf-8").read()
    return None


def extract_sources_list(concept_text):
    """Pull source names from ## Sources section."""
    if "## Sources" not in concept_text:
        return []
    sources_section = concept_text.split("## Sources")[-1]
    return re.findall(r'\[\[([^\]]+)\]\]', sources_section)


def already_enriched(concept_text):
    """Check if Definitions from Sources already has content."""
    match = re.search(r'## Definitions from Sources\n(.*?)(?=\n##|\Z)', concept_text, re.DOTALL)
    if match:
        return bool(match.group(1).strip())
    return False


def enrich_concept(client, concept_name, concept_text, source_notes):
    """Ask Claude to extract what each source says about the concept."""
    if not source_notes:
        return None

    sources_block = ""
    for book, content in source_notes.items():
        # Trim to relevant sections to keep prompt size reasonable
        relevant = extract_relevant_sections(content, concept_name)
        if relevant:
            sources_block += f"\n\n=== SOURCE: {book} ===\n{relevant}"

    if not sources_block.strip():
        return None

    prompt = f"""You are building a Zettelkasten concept note for: **{concept_name}**

Below are excerpts from book summary notes that mention this concept. For each source that has something meaningful to say about "{concept_name}", write a 1-2 sentence entry showing what that specific source contributes to understanding this concept. Use the source's own language where possible.

Format your response ONLY as a markdown list, one entry per source that has real content:

**[[Book Title]]:** What this source says about the concept in 1-2 sentences.

If a source barely mentions the concept or has nothing substantive, skip it entirely.
Do not include any preamble or explanation — just the list.

SOURCE NOTES:
{sources_block}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def extract_relevant_sections(source_text, concept_name):
    """Extract sections from a source note most likely to contain info about the concept."""
    concept_lower = concept_name.lower()
    sections = []

    # Always include Big Ideas if concept name appears there
    big_ideas_match = re.search(r'## Big Ideas\n(.*?)(?=\n##)', source_text, re.DOTALL)
    if big_ideas_match:
        section = big_ideas_match.group(1)
        if concept_lower in section.lower():
            sections.append("## Big Ideas\n" + section[:2000])

    # Include any quote where concept is mentioned
    quote_section = re.search(r'## Quote Index\n(.*?)(?=\n##|\Z)', source_text, re.DOTALL)
    if quote_section:
        quotes = quote_section.group(1)
        relevant_quotes = []
        for block in quotes.split('\n>'):
            if concept_lower in block.lower():
                relevant_quotes.append('>' + block)
        if relevant_quotes:
            sections.append("## Relevant Quotes\n" + '\n'.join(relevant_quotes[:3]))

    # Fallback: include first 800 chars of Big Ideas regardless
    if not sections and big_ideas_match:
        sections.append("## Big Ideas\n" + big_ideas_match.group(1)[:800])

    return '\n\n'.join(sections)[:3000]


def write_definitions(concept_path, definitions_text):
    """Write the enriched definitions into the concept file."""
    text = open(concept_path, encoding="utf-8").read()
    new_text = re.sub(
        r'(## Definitions from Sources\n)',
        f'## Definitions from Sources\n{definitions_text}\n',
        text,
        count=1
    )
    open(concept_path, "w", encoding="utf-8").write(new_text)


def get_concepts_to_enrich(vault, min_sources):
    """Return list of (source_count, concept_name, path) sorted by source_count desc."""
    concepts_dir = os.path.join(vault, "Concepts")
    candidates = []
    for fname in os.listdir(concepts_dir):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(concepts_dir, fname)
        text = open(path, encoding="utf-8").read()
        if already_enriched(text):
            continue
        sources = extract_sources_list(text)
        if len(sources) >= min_sources:
            candidates.append((len(sources), fname[:-3], path))
    return sorted(candidates, reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=VAULT)
    parser.add_argument("--min-sources", type=int, default=3,
                        help="Only enrich concepts with this many sources or more")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max concepts to process in one run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without calling API")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds between API calls")
    args = parser.parse_args()

    candidates = get_concepts_to_enrich(args.vault, args.min_sources)
    batch = candidates[:args.limit]

    print(f"Concepts eligible (>= {args.min_sources} sources, not yet enriched): {len(candidates)}")
    print(f"Processing: {len(batch)}")
    print()

    if args.dry_run:
        for count, name, _ in batch:
            print(f"  [{count} sources] {name}")
        return

    client = anthropic.Anthropic()
    enriched = 0
    skipped = 0

    for count, concept_name, concept_path in batch:
        print(f"[{count} sources] {concept_name}...", end=" ", flush=True)

        concept_text = open(concept_path, encoding="utf-8").read()
        sources = extract_sources_list(concept_text)

        # Load source notes
        source_notes = {}
        for source in sources:
            note = get_source_note(args.vault, source)
            if note:
                source_notes[source] = note

        if not source_notes:
            print(f"no source notes found, skipping")
            skipped += 1
            continue

        definitions = enrich_concept(client, concept_name, concept_text, source_notes)

        if definitions:
            write_definitions(concept_path, definitions)
            print(f"done ({len(source_notes)} source notes found)")
            enriched += 1
        else:
            print(f"no content extracted")
            skipped += 1

        time.sleep(args.delay)

    print(f"\nEnriched: {enriched}  Skipped: {skipped}")


if __name__ == "__main__":
    main()
