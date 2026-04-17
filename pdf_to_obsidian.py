#!/usr/bin/env python3
"""
pdf_to_obsidian.py
------------------
Converts book summary PDFs into interconnected Obsidian vault notes.

Pipeline: Extract → Analyze → Generate → Link

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  pip install pymupdf anthropic rapidfuzz

  python pdf_to_obsidian.py book.pdf --vault ~/Notes
  python pdf_to_obsidian.py ~/PDFs/*.pdf --vault ~/Notes --profile philosophers_notes
  python pdf_to_obsidian.py book.pdf --vault ~/Notes --debug --no-atomic
  python pdf_to_obsidian.py ~/PDFs/*.pdf --vault ~/Notes --resume
"""

import json
import os
import re
import sys
import time
import argparse
import textwrap
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz          # pip install pymupdf
import anthropic     # pip install anthropic

try:
    from rapidfuzz import fuzz, process as rfprocess
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("WARNING: rapidfuzz not installed — concept fuzzy-matching disabled.")
    print("         pip install rapidfuzz")


# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    vault: Path              = field(default_factory=lambda: Path("./vault"))
    # Karpathy-style directory structure
    source_notes_dir: str    = "wiki/sources"
    atomic_dir: str          = "wiki/atomic"
    people_dir: str          = "wiki/entities/people"
    books_dir: str           = "wiki/entities/books"
    concepts_dir: str        = "wiki/entities/concepts"
    themes_dir: str          = "wiki/themes"
    claude_model: str        = "claude-sonnet-4-20250514"
    profile: str             = "auto"
    col_split: float         = 0.28
    h1_size_ratio: float     = 1.35
    h2_size_ratio: float     = 1.10
    h2_bold_ratio: float     = 0.95
    atomic_min_words: int    = 50
    atomic_notes: bool       = True
    overwrite_stubs: bool    = False
    debug: bool              = False
    resume: bool             = False
    api_delay: float         = 1.0  # seconds between API calls


# ══════════════════════════════════════════════════════════════════════════════
# Layout Profiles
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LayoutProfile:
    id: str
    name: str
    col_split: float
    extract_sidebar: bool
    h1_size_ratio: float
    h2_size_ratio: float
    h2_bold_ratio: float
    junk_patterns: list = field(default_factory=list)
    detection_signatures: list = field(default_factory=list)
    page_skip: list = field(default_factory=list)
    special_blocks: dict = field(default_factory=dict)


PROFILES = {
    "philosophers_notes": LayoutProfile(
        id="philosophers_notes",
        name="Philosopher's Notes (Brian Johnson / Heroic)",
        col_split=0.28,
        extract_sidebar=True,
        h1_size_ratio=1.35,
        h2_size_ratio=1.10,
        h2_bold_ratio=0.95,
        junk_patterns=[
            r"Philosopher.?s\s+w?Notes\s*\|",
            r"^\d+\s+Philosopher.?s\s+w?Notes",
            r"^philosophersnotes\.com",
            r"^heroic\.us",
            r"^optimize\.me",
            r"^If you liked this Note",
            r"^you.ll probably like",
            r"^FROM THE BOOK",
            r"^About the Author of This Note",
        ],
        detection_signatures=[
            "Philosopher's Notes",
            "PhilosophersNotes",
            "philosophersnotes.com",
        ],
    ),
    "shortform": LayoutProfile(
        id="shortform",
        name="Shortform Book Guides",
        col_split=0.0,
        extract_sidebar=False,
        h1_size_ratio=1.40,
        h2_size_ratio=1.15,
        h2_bold_ratio=1.0,
        junk_patterns=[
            r"^Shortform\s",
            r"^www\.shortform\.com",
            r"^Page\s+\d+\s+of\s+\d+",
        ],
        detection_signatures=["Shortform", "shortform.com"],
        page_skip=[0],
    ),
    "readingraphics": LayoutProfile(
        id="readingraphics",
        name="ReadingGraphics Book Summaries",
        col_split=0.0,
        extract_sidebar=False,
        h1_size_ratio=1.50,
        h2_size_ratio=1.20,
        h2_bold_ratio=1.0,
        junk_patterns=[
            r"^readingraphics\.com",
            r"^ReadinGraphics",
            r"^©\s*ReadinGraphics",
        ],
        detection_signatures=["ReadinGraphics", "readingraphics"],
    ),
    "getabstract": LayoutProfile(
        id="getabstract",
        name="getAbstract Book Summaries",
        col_split=0.0,
        extract_sidebar=False,
        h1_size_ratio=1.40,
        h2_size_ratio=1.15,
        h2_bold_ratio=1.0,
        junk_patterns=[
            r"^getAbstract",
            r"^©\s*\d{4}\s+getAbstract",
        ],
        detection_signatures=["getAbstract", "Take-Aways"],
    ),
    "generic": LayoutProfile(
        id="generic",
        name="Generic Full-Width PDF",
        col_split=0.0,
        extract_sidebar=False,
        h1_size_ratio=1.35,
        h2_size_ratio=1.10,
        h2_bold_ratio=0.95,
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Block:
    text: str
    kind: str          # heading | subheading | body | pull_quote | attribution | sidebar_label
    level: int = 0     # 1 or 2 for headings
    font_size: float = 0.0
    is_sidebar: bool = False
    page: int = 0


@dataclass
class PullQuote:
    text: str
    attribution: str
    page: int = 0


@dataclass
class DocumentStructure:
    source_file: str
    page_count: int
    profile_id: str
    blocks: list = field(default_factory=list)
    pull_quotes: list = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Serialize to labeled plain text for Claude analysis."""
        lines = []
        for b in self.blocks:
            if b.kind == "heading":
                lines.append(f"\n[H1] {b.text}")
            elif b.kind == "subheading":
                lines.append(f"\n[H2] {b.text}")
            elif b.kind == "body":
                lines.append(b.text)
        lines.append("\n\n[PULL QUOTES FROM SIDEBAR]")
        for pq in self.pull_quotes:
            lines.append(f'[QUOTE] "{pq.text}"')
            if pq.attribution:
                lines.append(f"[ATTR]  {pq.attribution}")
        result = "\n".join(lines).strip()
        return clean_text(result)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1: Layout-Aware Extraction
# ══════════════════════════════════════════════════════════════════════════════

def detect_profile(doc: fitz.Document) -> LayoutProfile:
    """Auto-detect the PDF format from page 1 content."""
    if doc.page_count == 0:
        return PROFILES["generic"]

    page1_text = doc[0].get_text("text").lower()
    # Normalize curly quotes/apostrophes to ASCII for matching
    page1_text = page1_text.replace("\u2018", "'").replace("\u2019", "'")
    page1_text = page1_text.replace("\u201c", '"').replace("\u201d", '"')

    for profile_id, profile in PROFILES.items():
        if profile_id == "generic":
            continue
        for sig in profile.detection_signatures:
            if sig.lower() in page1_text:
                return profile

    return PROFILES["generic"]


def _is_junk(text: str, profile: LayoutProfile) -> bool:
    """Check if a text line is header/footer/noise."""
    t = text.strip()
    if not t:
        return True
    if re.fullmatch(r"\d+", t):  # lone page number
        return True
    # Normalize curly quotes for pattern matching
    t_normalized = t.replace("\u2018", "'").replace("\u2019", "'")
    for pattern in profile.junk_patterns:
        if re.search(pattern, t_normalized, re.IGNORECASE):
            return True
    return False


def _page_median_font_size(page_dict: dict) -> float:
    """Compute median font size across all text spans on the page."""
    sizes = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # text blocks only
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(span["size"])
    return statistics.median(sizes) if sizes else 12.0


def extract(pdf_path: Path, profile: LayoutProfile, cfg: Config) -> DocumentStructure:
    """
    Stage 1: Layout-aware extraction using PyMuPDF font metadata.

    Uses get_text("dict") for font size and coordinate data.
    Classifies each span as heading/body/sidebar based on profile rules.
    """
    doc = fitz.open(str(pdf_path))
    structure = DocumentStructure(
        source_file=pdf_path.name,
        page_count=doc.page_count,
        profile_id=profile.id,
    )

    for page_idx in range(doc.page_count):
        if page_idx in profile.page_skip:
            continue

        page = doc[page_idx]
        page_dict = page.get_text("dict")
        page_width = page.rect.width
        median_size = _page_median_font_size(page_dict)
        col_boundary = page_width * profile.col_split

        sidebar_texts = []
        current_quote = None

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            block_x0 = block["bbox"][0]
            is_sidebar = profile.extract_sidebar and block_x0 < col_boundary

            for line in block.get("lines", []):
                line_text_parts = []
                line_sizes = []
                line_spans_bold = []

                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    if _is_junk(text, profile):
                        continue
                    line_text_parts.append(text)
                    line_sizes.append(span["size"])
                    line_spans_bold.append("bold" in span.get("font", "").lower())

                if not line_text_parts:
                    continue

                line_text = " ".join(line_text_parts)
                avg_size = statistics.mean(line_sizes) if line_sizes else median_size
                # Calculate what fraction of spans are bold
                bold_ratio = sum(1 for s in line_spans_bold if s) / len(line_spans_bold) if line_spans_bold else 0

                if is_sidebar:
                    # Sidebar content → potential pull quote
                    sidebar_texts.append({
                        "text": line_text,
                        "size": avg_size,
                        "bold": bold_ratio > 0.5,
                        "page": page_idx + 1,
                    })
                else:
                    # Main column → classify by font size
                    if avg_size >= median_size * profile.h1_size_ratio:
                        structure.blocks.append(Block(
                            text=line_text, kind="heading", level=1,
                            font_size=avg_size, page=page_idx + 1,
                        ))
                    elif avg_size >= median_size * profile.h2_size_ratio:
                        # Size-based subheading: only if line is short enough
                        # to be a real heading (not body text with one large span)
                        if len(line_text) < 80:
                            structure.blocks.append(Block(
                                text=line_text, kind="subheading", level=2,
                                font_size=avg_size, page=page_idx + 1,
                            ))
                        else:
                            structure.blocks.append(Block(
                                text=line_text, kind="body",
                                font_size=avg_size, page=page_idx + 1,
                            ))
                    elif bold_ratio > 0.5 and avg_size >= median_size * profile.h2_bold_ratio and len(line_text) < 60:
                        # Bold-based subheading: must be majority bold AND short
                        structure.blocks.append(Block(
                            text=line_text, kind="subheading", level=2,
                            font_size=avg_size, page=page_idx + 1,
                        ))
                    else:
                        structure.blocks.append(Block(
                            text=line_text, kind="body",
                            font_size=avg_size, page=page_idx + 1,
                        ))

        # Process sidebar texts into pull quotes
        if sidebar_texts:
            _extract_pull_quotes(sidebar_texts, structure, median_size)

    doc.close()

    # Post-process: merge consecutive body blocks into paragraphs
    structure.blocks = _merge_body_blocks(structure.blocks)

    return structure


def _merge_body_blocks(blocks: list) -> list:
    """Merge consecutive body blocks on the same page into single paragraph blocks."""
    if not blocks:
        return blocks

    merged = [blocks[0]]
    for block in blocks[1:]:
        prev = merged[-1]
        if (block.kind == "body" and prev.kind == "body"
                and block.page == prev.page
                and abs(block.font_size - prev.font_size) < 1.0):
            # Merge: concatenate text with space
            prev.text = prev.text.rstrip() + " " + block.text.lstrip()
        else:
            merged.append(block)

    return merged


def _extract_pull_quotes(sidebar_texts: list, structure: DocumentStructure,
                         median_size: float):
    """
    Parse sidebar text blocks into PullQuote objects.

    Strategy: merge consecutive lines at the same font size into one quote,
    then check if the next line is an attribution (smaller size or starts
    with a dash character).
    """
    if not sidebar_texts:
        return

    # Group consecutive lines by font size to merge multi-line quotes
    groups = []
    current_group = [sidebar_texts[0]]
    for item in sidebar_texts[1:]:
        prev = current_group[-1]
        # Same size and same page → continuation of same block
        if (abs(item["size"] - prev["size"]) < 0.5
                and item["page"] == prev["page"]):
            current_group.append(item)
        else:
            groups.append(current_group)
            current_group = [item]
    groups.append(current_group)

    i = 0
    while i < len(groups):
        group = groups[i]
        merged_text = " ".join(item["text"] for item in group).strip()
        avg_size = statistics.mean(item["size"] for item in group)
        page = group[0]["page"]

        # Quote detection: merged text is substantial and not tiny
        if len(merged_text) > 15 and avg_size >= median_size * 0.85:
            attribution = ""
            # Check if next group is an attribution
            if i + 1 < len(groups):
                next_group = groups[i + 1]
                next_text = " ".join(item["text"] for item in next_group).strip()
                next_size = statistics.mean(item["size"] for item in next_group)
                is_attr = (
                    next_size < avg_size - 0.5
                    or next_text.startswith(("—", "-", "–", "~", "·"))
                )
                if is_attr and len(next_text) < len(merged_text):
                    attribution = next_text.lstrip("—-–~· ").strip()
                    i += 1

            # Clean quote marks
            cleaned = merged_text.strip('"""\u201c\u201d\'')
            structure.pull_quotes.append(PullQuote(
                text=cleaned,
                attribution=attribution,
                page=page,
            ))
        i += 1


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2: Claude API Analysis
# ══════════════════════════════════════════════════════════════════════════════

ANALYSIS_SYSTEM_PROMPT = """You are a knowledge extraction engine for an Obsidian Zettelkasten vault. You receive structured text extracted from a book summary PDF. Your job is to analyze it and return a single JSON object — no markdown fences, no preamble, no explanation.

The input text uses these markers:
- [H1] = major section heading
- [H2] = subsection heading
- Body text follows headings directly
- [PULL QUOTES FROM SIDEBAR] section contains sidebar quotes
- [QUOTE] = a pull quote
- [ATTR] = attribution for the preceding quote

Return this exact JSON structure:
{
  "title": "Book title",
  "author": "Book author (first last)",
  "summarizer": "Person who wrote these notes (if identifiable, else null)",
  "series": "Series name if identifiable, else null",
  "theme": "One-sentence theme",
  "sections": [
    {"heading": "Section title", "summary": "2-3 sentence summary", "body": "Full cleaned text", "level": 1}
  ],
  "pull_quotes": [
    {"text": "Quote text", "attribution": "First Last", "source_work": "Book title or null"}
  ],
  "people": [
    {"name": "First Last", "aliases": [], "role": "philosopher", "context": "Why mentioned"}
  ],
  "books": [
    {"title": "Book Title", "author": "First Last or null", "context": "Why referenced"}
  ],
  "concepts": [
    {"name": "Concept Name", "category": "philosophy", "definition": "1-2 sentences", "aliases": []}
  ],
  "tags": ["lowercase", "tags"],
  "big_ideas": ["First big idea", "Second big idea"]
}

Rules:
- Distinguish book author from note summarizer.
- Only include people/books/concepts explicitly named in the text.
- Clean OCR artifacts. Merge sections under 20 words with neighbors.
- Return ONLY the JSON object."""


def analyze(structure: DocumentStructure, cfg: Config) -> dict:
    """Stage 2: Send extracted text to Claude for semantic analysis."""
    client = anthropic.Anthropic()

    prompt_text = structure.to_prompt_text()
    user_msg = f"Analyze this book summary extracted from a PDF.\nProfile: {structure.profile_id}\n\n---BEGIN EXTRACTED TEXT---\n{prompt_text}\n---END EXTRACTED TEXT---"

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=cfg.claude_model,
                max_tokens=4096,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)

        except json.JSONDecodeError:
            if attempt < 2:
                user_msg += "\n\nYour previous response was not valid JSON. Return ONLY a JSON object."
                time.sleep(2 ** (attempt + 1))
            else:
                raise

        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 1))

    return {}


# ══════════════════════════════════════════════════════════════════════════════
# Text Cleaning (consolidated from cleaning.py)
# ══════════════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Normalize Unicode, fix OCR artifacts, collapse whitespace."""
    # Normalize curly quotes to straight
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Normalize dashes
    text = text.replace("\u2013", "–").replace("\u2014", "—")
    # Fix hyphenation breaks (word split across lines)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip fill-in blanks
    text = re.sub(r"__{3,}", "", text)
    return text.strip()


# ══════════════════════════════════════════════════════════════════════════════
# Inline Concept Linking
# ══════════════════════════════════════════════════════════════════════════════

def _build_entity_lookup(analysis: dict, existing_dict: dict = None) -> dict:
    """
    Build a lookup table: lowercased term → canonical wiki-link name.
    Combines entities from the current analysis AND the existing concept dictionary.
    """
    lookup = {}

    # From current analysis: people, books, concepts
    for person in analysis.get("people", []):
        name = person["name"]
        lookup[name.lower()] = name
        for alias in person.get("aliases", []):
            lookup[alias.lower()] = name

    for book in analysis.get("books", []):
        title = book["title"]
        lookup[title.lower()] = title

    for concept in analysis.get("concepts", []):
        name = concept["name"]
        lookup[name.lower()] = name
        for alias in concept.get("aliases", []):
            lookup[alias.lower()] = name

    # From existing concept dictionary (accumulated from prior PDFs)
    if existing_dict:
        for key, entry in existing_dict.items():
            canonical = entry["canonical"]
            lookup[canonical.lower()] = canonical
            for alias in entry.get("aliases", []):
                lookup[alias.lower()] = canonical

    return lookup


def _apply_inline_links(text: str, lookup: dict) -> str:
    """
    Scan text for entity/concept names and wrap first occurrence in [[wiki-links]].
    Skips terms already inside [[ ]] brackets.
    """
    if not lookup:
        return text

    # Sort by length descending so longer matches take priority
    # ("Man's Search for Meaning" before "Man")
    sorted_terms = sorted(lookup.keys(), key=len, reverse=True)

    linked_canonicals = set()

    for term in sorted_terms:
        canonical = lookup[term]
        if canonical in linked_canonicals:
            continue
        if f"[[{canonical}]]" in text or f"[[{canonical}|" in text:
            linked_canonicals.add(canonical)
            continue

        pattern = re.compile(
            r"(?<!\[\[)(?<!\|)\b" + re.escape(term) + r"\b(?!\]\])(?!\|)",
            re.IGNORECASE
        )
        match = pattern.search(text)
        if match:
            original = match.group()
            if original.lower() == canonical.lower():
                replacement = f"[[{canonical}]]"
            else:
                replacement = f"[[{canonical}|{original}]]"
            text = text[:match.start()] + replacement + text[match.end():]
            linked_canonicals.add(canonical)

    return text


# ══════════════════════════════════════════════════════════════════════════════
# Stage 3: Note Generation
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_filename(name: str) -> str:
    """Remove characters not allowed in filenames."""
    return re.sub(r'[/\\:*?"<>|]', '', name).strip()


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def generate(analysis: dict, structure: DocumentStructure, cfg: Config) -> dict:
    """
    Stage 3: Write markdown files to the vault.
    Applies inline wiki-linking during generation using entity lookup.
    Returns a manifest of created files for the linking stage.
    """
    title = analysis.get("title", "Untitled")
    safe_title = _sanitize_filename(title)
    manifest = {"source_note": None, "atomic_notes": [], "entity_stubs": []}

    # Build entity lookup from analysis + existing concept dictionary
    dict_path = cfg.vault / "concepts_dictionary.json"
    existing_dict = {}
    if dict_path.exists():
        try:
            existing_dict = json.loads(dict_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    lookup = _build_entity_lookup(analysis, existing_dict)

    # --- Source Note ---
    source_dir = cfg.vault / cfg.source_notes_dir
    _ensure_dir(source_dir)
    source_path = source_dir / f"{safe_title}.md"

    frontmatter = {
        "title": title,
        "author": analysis.get("author", "Unknown"),
        "summarizer": analysis.get("summarizer"),
        "series": analysis.get("series"),
        "source_pdf": structure.source_file,
        "profile": structure.profile_id,
        "type": "source-note",
        "permanent_note": False,
        "date_processed": datetime.now().strftime("%Y-%m-%d"),
        "tags": analysis.get("tags", []),
    }
    # Remove None values
    frontmatter = {k: v for k, v in frontmatter.items() if v is not None}

    lines = ["---"]
    for key, val in frontmatter.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {item}")
        else:
            lines.append(f'{key}: "{val}"' if isinstance(val, str) else f"{key}: {val}")
    lines.append("---\n")

    lines.append(f"# {title}\n")
    author = analysis.get("author", "Unknown")
    lines.append(f"**Author:** [[{author}]]")
    if analysis.get("summarizer"):
        lines.append(f"**Notes by:** {analysis['summarizer']}")
    if analysis.get("theme"):
        lines.append(f"**Theme:** {analysis['theme']}")
    lines.append("")

    # Big Ideas — apply inline entity linking
    big_ideas = analysis.get("big_ideas", [])
    if big_ideas:
        lines.append("## The Big Ideas")
        for idea in big_ideas:
            lines.append(f"- {_apply_inline_links(clean_text(idea), lookup)}")
        lines.append("")

    # Sections TOC (if atomic)
    sections = analysis.get("sections", [])
    if cfg.atomic_notes and sections:
        lines.append("## Sections")
        for sec in sections:
            sec_title = f"{safe_title} - {_sanitize_filename(sec['heading'])}"
            lines.append(f"- [[{sec_title}]]")
        lines.append("")

    # Section bodies — clean text and apply inline entity linking
    for sec in sections:
        heading = sec.get("heading", "Untitled Section")
        body = clean_text(sec.get("body", ""))
        body = _apply_inline_links(body, lookup)
        level = sec.get("level", 1)
        prefix = "#" * (level + 1)
        lines.append(f"{prefix} {heading}")
        lines.append(body)
        lines.append("")

    # Pull quotes
    quotes = analysis.get("pull_quotes", [])
    if quotes:
        lines.append("## Key Quotes")
        for q in quotes:
            lines.append(f'> "{q["text"]}"')
            if q.get("attribution"):
                lines.append(f"> — [[{q['attribution']}]]")
            lines.append("")

    # Mentioned entities
    people = analysis.get("people", [])
    books = analysis.get("books", [])
    concepts = analysis.get("concepts", [])

    if people or books or concepts:
        lines.append("## Mentioned")

    if people:
        lines.append("### People")
        for p in people:
            lines.append(f"- [[{p['name']}]] — {p.get('context', '')}")
        lines.append("")

    if books:
        lines.append("### Works")
        for b in books:
            lines.append(f"- [[{b['title']}]] — {b.get('context', '')}")
        lines.append("")

    if concepts:
        lines.append("### Concepts")
        for c in concepts:
            lines.append(f"- [[{c['name']}]] — {c.get('definition', '')}")
        lines.append("")

    # Zettelkasten: My Notes section for permanent note development
    lines.append("## My Notes")
    lines.append("")
    lines.append("<!-- Your own thinking goes here. This is where literature notes")
    lines.append("     become permanent notes. What connections do you see? What do")
    lines.append("     you disagree with? How does this apply to your work? -->")
    lines.append("")

    source_path.write_text("\n".join(lines), encoding="utf-8")
    manifest["source_note"] = str(source_path)
    print(f"  ✓ Source note: {source_path.name}")

    # --- Atomic Notes ---
    if cfg.atomic_notes:
        atomic_dir = cfg.vault / cfg.atomic_dir
        _ensure_dir(atomic_dir)
        for i, sec in enumerate(sections):
            body = sec.get("body", "")
            if len(body.split()) < cfg.atomic_min_words:
                continue
            sec_heading = sec.get("heading", f"Section {i+1}")
            sec_title = f"{safe_title} - {_sanitize_filename(sec_heading)}"
            sec_path = atomic_dir / f"{sec_title}.md"

            sec_lines = [
                "---",
                f'title: "{sec_title}"',
                f'parent: "[[{title}]]"',
                "type: atomic-note",
                f"section_index: {i + 1}",
                "---\n",
                f"# {sec_heading}\n",
                f"> Part of [[{title}]]\n",
                body,
            ]
            sec_path.write_text("\n".join(sec_lines), encoding="utf-8")
            manifest["atomic_notes"].append(str(sec_path))

        if manifest["atomic_notes"]:
            print(f"  ✓ Atomic notes: {len(manifest['atomic_notes'])}")

    # --- Entity Stubs ---
    for person in people:
        path = _write_entity_stub(
            cfg, cfg.people_dir, person["name"], "person",
            aliases=person.get("aliases", []),
            extra_fields={"role": person.get("role", "")},
            context=person.get("context", ""),
            source_title=title,
        )
        if path:
            manifest["entity_stubs"].append(str(path))

    for book in books:
        extra = {}
        if book.get("author"):
            extra["author"] = f"[[{book['author']}]]"
        path = _write_entity_stub(
            cfg, cfg.books_dir, book["title"], "book",
            extra_fields=extra,
            context=book.get("context", ""),
            source_title=title,
        )
        if path:
            manifest["entity_stubs"].append(str(path))

    for concept in concepts:
        path = _write_entity_stub(
            cfg, cfg.concepts_dir, concept["name"], "concept",
            aliases=concept.get("aliases", []),
            extra_fields={"category": concept.get("category", "")},
            description=concept.get("definition", ""),
            context=concept.get("definition", ""),
            source_title=title,
        )
        if path:
            manifest["entity_stubs"].append(str(path))

    if manifest["entity_stubs"]:
        print(f"  ✓ Entity stubs: {len(manifest['entity_stubs'])}")

    return manifest


def _write_entity_stub(cfg: Config, subdir: str, name: str, entity_type: str,
                       aliases: list = None, extra_fields: dict = None,
                       description: str = "", context: str = "",
                       source_title: str = "") -> Optional[Path]:
    """Write an entity stub note, or update its Mentioned In section."""
    entity_dir = cfg.vault / subdir
    _ensure_dir(entity_dir)
    safe_name = _sanitize_filename(name)
    path = entity_dir / f"{safe_name}.md"

    if path.exists():
        # Append to Mentioned In if not already present
        _append_mention(path, source_title, context)
        return None  # didn't create new file

    fm_lines = [
        "---",
        f'title: "{name}"',
        f"type: {entity_type}",
    ]
    if aliases:
        fm_lines.append("aliases:")
        for a in aliases:
            fm_lines.append(f'  - "{a}"')
    if extra_fields:
        for k, v in extra_fields.items():
            if v:
                fm_lines.append(f'{k}: "{v}"')
    fm_lines.append("---\n")
    fm_lines.append(f"# {name}\n")
    if description:
        fm_lines.append(f"{description}\n")
    fm_lines.append("## Mentioned In")
    fm_lines.append(f"- [[{source_title}]] — {context}")

    path.write_text("\n".join(fm_lines), encoding="utf-8")
    return path


def _append_mention(path: Path, source_title: str, context: str):
    """Idempotently append a Mentioned In entry to an existing stub."""
    content = path.read_text(encoding="utf-8")
    mention_line = f"- [[{source_title}]]"
    if mention_line in content:
        return  # already mentioned

    if "## Mentioned In" not in content:
        content += f"\n\n## Mentioned In\n{mention_line} — {context}"
    else:
        content = content.replace(
            "## Mentioned In",
            f"## Mentioned In\n{mention_line} — {context}",
            1,
        )
    path.write_text(content, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4: Concept Linking
# ══════════════════════════════════════════════════════════════════════════════

def link(cfg: Config, analysis: dict):
    """
    Stage 4: Update concept dictionary and apply fuzzy auto-linking.
    """
    dict_path = cfg.vault / "concepts_dictionary.json"

    # Load or initialize concept dictionary
    if dict_path.exists():
        concept_dict = json.loads(dict_path.read_text(encoding="utf-8"))
    else:
        concept_dict = {}

    # Add new concepts from this analysis
    for concept in analysis.get("concepts", []):
        key = concept["name"].lower()
        if key not in concept_dict:
            concept_dict[key] = {
                "canonical": concept["name"],
                "aliases": concept.get("aliases", []),
                "category": concept.get("category", ""),
                "definition": concept.get("definition", ""),
                "source_count": 1,
            }
        else:
            concept_dict[key]["source_count"] = concept_dict[key].get("source_count", 0) + 1
            # Merge new aliases
            existing_aliases = set(concept_dict[key].get("aliases", []))
            for alias in concept.get("aliases", []):
                existing_aliases.add(alias)
            concept_dict[key]["aliases"] = list(existing_aliases)

    # Save updated dictionary
    dict_path.write_text(
        json.dumps(concept_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Fuzzy auto-linking in source and atomic notes
    if HAS_RAPIDFUZZ and concept_dict:
        _apply_concept_links(cfg, concept_dict)


def _apply_concept_links(cfg: Config, concept_dict: dict):
    """Scan note bodies for concept mentions and insert wiki-links."""
    # Build lookup: all names and aliases → canonical name
    lookup = {}
    for key, entry in concept_dict.items():
        canonical = entry["canonical"]
        lookup[canonical.lower()] = canonical
        for alias in entry.get("aliases", []):
            lookup[alias.lower()] = canonical

    all_terms = list(lookup.keys())

    # Process source notes and atomic notes
    for subdir in [cfg.source_notes_dir, cfg.atomic_dir]:
        notes_dir = cfg.vault / subdir
        if not notes_dir.exists():
            continue
        for note_path in notes_dir.glob("*.md"):
            content = note_path.read_text(encoding="utf-8")
            # Split into frontmatter and body
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            body = parts[2]

            # Find words/phrases in body that fuzzy-match concepts
            modified = False
            for term in all_terms:
                canonical = lookup[term]
                # Skip if already linked
                if f"[[{canonical}]]" in body or f"[[{canonical}|" in body:
                    continue

                # Simple substring check first (case-insensitive)
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                match = pattern.search(body)
                if match:
                    original = match.group()
                    if original.lower() == canonical.lower():
                        replacement = f"[[{canonical}]]"
                    else:
                        replacement = f"[[{canonical}|{original}]]"
                    # Only replace first occurrence
                    body = body[:match.start()] + replacement + body[match.end():]
                    modified = True

            if modified:
                note_path.write_text(parts[0] + "---" + parts[1] + "---" + body, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Processing Log
# ══════════════════════════════════════════════════════════════════════════════

def _load_log(cfg: Config) -> dict:
    log_path = cfg.vault / "processing_log.json"
    if log_path.exists():
        return json.loads(log_path.read_text(encoding="utf-8"))
    return {"processed": {}, "stats": {"total_processed": 0, "total_failed": 0}}


def _save_log(cfg: Config, log: dict):
    log_path = cfg.vault / "processing_log.json"
    log["last_run"] = datetime.now().isoformat()
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def process_pdf(pdf_path: Path, cfg: Config, log: dict) -> bool:
    """Run the full pipeline on a single PDF. Returns True on success."""
    filename = pdf_path.name
    print(f"\n{'='*60}")
    print(f"Processing: {filename}")
    print(f"{'='*60}")

    try:
        # Stage 1: Extract
        doc = fitz.open(str(pdf_path))
        if cfg.profile == "auto":
            profile = detect_profile(doc)
        else:
            profile = PROFILES.get(cfg.profile, PROFILES["generic"])
        doc.close()

        print(f"  Profile: {profile.name}")
        structure = extract(pdf_path, profile, cfg)
        print(f"  Extracted: {len(structure.blocks)} blocks, {len(structure.pull_quotes)} quotes")

        if cfg.debug:
            debug_path = cfg.vault / f"{pdf_path.stem}_debug.json"
            debug_data = {
                "blocks": [{"text": b.text, "kind": b.kind, "level": b.level,
                           "font_size": b.font_size, "page": b.page} for b in structure.blocks],
                "pull_quotes": [{"text": q.text, "attribution": q.attribution,
                                "page": q.page} for q in structure.pull_quotes],
            }
            debug_path.write_text(json.dumps(debug_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Debug JSON: {debug_path}")

        # Stage 2: Analyze
        print("  Analyzing with Claude...")
        analysis = analyze(structure, cfg)
        print(f"  Title: {analysis.get('title', '?')}")
        print(f"  Entities: {len(analysis.get('people', []))} people, "
              f"{len(analysis.get('books', []))} books, "
              f"{len(analysis.get('concepts', []))} concepts")

        # Stage 3: Generate
        manifest = generate(analysis, structure, cfg)

        # Stage 4: Link
        link(cfg, analysis)
        print("  ✓ Concept dictionary updated")

        # Log success
        log["processed"][filename] = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "profile": profile.id,
            "source_note": manifest["source_note"],
            "entities_created": len(manifest["entity_stubs"]),
            "atomic_notes_created": len(manifest["atomic_notes"]),
        }
        log["stats"]["total_processed"] = log["stats"].get("total_processed", 0) + 1
        return True

    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        log["processed"][filename] = {
            "status": "failed",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
        }
        log["stats"]["total_failed"] = log["stats"].get("total_failed", 0) + 1
        return False


def main():
    parser = argparse.ArgumentParser(description="Convert book summary PDFs to Obsidian notes")
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF file(s) to process")
    parser.add_argument("--vault", type=Path, default=Path("./vault"), help="Obsidian vault root")
    parser.add_argument("--profile", default="auto",
                        choices=list(PROFILES.keys()) + ["auto"],
                        help="Layout profile (default: auto-detect)")
    parser.add_argument("--col-split", type=float, default=None,
                        help="Override column split fraction")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model for analysis")
    parser.add_argument("--no-atomic", action="store_true", help="Disable atomic note splitting")
    parser.add_argument("--overwrite-stubs", action="store_true",
                        help="Overwrite existing entity stubs")
    parser.add_argument("--debug", action="store_true", help="Save extraction debug JSON")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed files")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between API calls (rate limiting)")

    args = parser.parse_args()

    cfg = Config(
        vault=args.vault,
        profile=args.profile,
        claude_model=args.model,
        atomic_notes=not args.no_atomic,
        overwrite_stubs=args.overwrite_stubs,
        debug=args.debug,
        resume=args.resume,
        api_delay=args.delay,
    )

    if args.col_split is not None:
        cfg.col_split = args.col_split

    # Ensure vault structure (Karpathy-style)
    for subdir in [
        cfg.source_notes_dir, cfg.atomic_dir,
        cfg.people_dir, cfg.books_dir, cfg.concepts_dir,
        cfg.themes_dir,
        "wiki/queries",
        "raw/pdfs", "raw/clippings", "raw/personal-notes",
        "permanent/insights", "permanent/projects",
    ]:
        _ensure_dir(cfg.vault / subdir)

    # Copy CLAUDE.md to vault root if not present
    claude_md_src = Path(__file__).parent.parent / "references" / "CLAUDE.md"
    claude_md_dst = cfg.vault / "CLAUDE.md"
    if claude_md_src.exists() and not claude_md_dst.exists():
        import shutil
        shutil.copy2(claude_md_src, claude_md_dst)
        print(f"  ✓ Created CLAUDE.md at vault root")

    log = _load_log(cfg)

    # Expand globs and filter (handles Windows where shell doesn't expand *.pdf)
    import glob as _glob
    pdf_files = []
    expanded = []
    for p in args.pdfs:
        if '*' in str(p) or '?' in str(p):
            matches = [Path(m) for m in _glob.glob(str(p))]
            expanded.extend(matches)
        else:
            expanded.append(p)
    for p in expanded:
        if p.is_file() and p.suffix.lower() == ".pdf":
            if cfg.resume and p.name in log.get("processed", {}):
                status = log["processed"][p.name].get("status")
                if status == "success":
                    print(f"Skipping (already processed): {p.name}")
                    continue
            pdf_files.append(p)

    print(f"\nPipeline starting: {len(pdf_files)} PDFs to process")
    print(f"Vault: {cfg.vault.resolve()}")
    print(f"Model: {cfg.claude_model}")

    success = 0
    failed = 0
    for i, pdf_path in enumerate(pdf_files):
        if process_pdf(pdf_path, cfg, log):
            success += 1
        else:
            failed += 1

        _save_log(cfg, log)

        # Rate limit between API calls
        if i < len(pdf_files) - 1:
            time.sleep(cfg.api_delay)

    print(f"\n{'='*60}")
    print(f"COMPLETE: {success} succeeded, {failed} failed out of {len(pdf_files)}")
    print(f"{'='*60}")

    # Generate/update wiki index
    if success > 0:
        _update_wiki_index(cfg, log)


def _update_wiki_index(cfg: Config, log: dict):
    """Generate wiki/_index.md from processing log and vault contents."""
    index_path = cfg.vault / "wiki" / "_index.md"
    sources_dir = cfg.vault / cfg.source_notes_dir

    lines = [
        "# Knowledge Base Index",
        "",
        f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Total sources processed:** {log['stats'].get('total_processed', 0)}",
        f"**Total failed:** {log['stats'].get('total_failed', 0)}",
        "",
        "## Source Notes",
        "",
    ]

    # List all source notes
    if sources_dir.exists():
        for note_path in sorted(sources_dir.glob("*.md")):
            lines.append(f"- [[{note_path.stem}]]")

    # Concept dictionary stats
    dict_path = cfg.vault / "concepts_dictionary.json"
    if dict_path.exists():
        try:
            concept_dict = json.loads(dict_path.read_text(encoding="utf-8"))
            lines.append("")
            lines.append("## Concepts")
            lines.append("")
            lines.append(f"**Total concepts:** {len(concept_dict)}")
            lines.append("")

            # Sort by source_count descending — most referenced first
            sorted_concepts = sorted(
                concept_dict.items(),
                key=lambda x: x[1].get("source_count", 0),
                reverse=True
            )
            for key, entry in sorted_concepts[:50]:  # top 50
                count = entry.get("source_count", 0)
                maturity = "evergreen" if count >= 15 else "developing" if count >= 5 else "stub"
                lines.append(f"- [[{entry['canonical']}]] ({count} sources, {maturity})")
        except json.JSONDecodeError:
            pass

    # Entity counts
    for entity_type, entity_dir in [
        ("People", cfg.people_dir),
        ("Books", cfg.books_dir),
    ]:
        entity_path = cfg.vault / entity_dir
        if entity_path.exists():
            count = len(list(entity_path.glob("*.md")))
            if count > 0:
                lines.append("")
                lines.append(f"## {entity_type} ({count})")
                lines.append("")
                for note in sorted(entity_path.glob("*.md")):
                    lines.append(f"- [[{note.stem}]]")

    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ Wiki index updated: {index_path}")


if __name__ == "__main__":
    main()
