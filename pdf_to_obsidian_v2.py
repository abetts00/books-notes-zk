"""
pdf_to_obsidian.py  v2
======================
Converts PDFs into an interconnected Obsidian Zettelkasten with:

  1. Font-aware heading detection  (get_text("dict") → H1/H2/body/pull_quote)
  2. Pull-quote extraction with attribution  (geometric + Claude cleanup)
  3. Concept dictionary with fuzzy autolinking  (concepts_dictionary.json)
  4. Bidirectional "Mentioned In" stub updates  (append_mention, idempotent)
  5. Atomic note splitting  (MOC parent + per-section child notes)

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  pip install pymupdf anthropic rapidfuzz

  python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes
  python pdf_to_obsidian_v2.py *.pdf   --vault ~/Notes --debug
  python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes --no-atomic
  python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes --col-split 0.0  # full-width PDF
"""

import json
import re
import sys
import time
import argparse
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz          # pip install pymupdf
import anthropic     # pip install anthropic

try:
    from rapidfuzz import fuzz, process as rfprocess
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("WARNING: rapidfuzz not installed — concept fuzzy-matching disabled. pip install rapidfuzz")


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    vault: Path              = Path(r"C:\Users\abett\OneDrive\Desktop\Obsidian\Vault\Zettlekasten")
    source_notes_dir: str    = "Sources"
    people_dir: str          = "People"
    books_dir: str           = "Books"
    concepts_dir: str        = "Concepts"
    claude_model: str        = "claude-opus-4-6"

    # Layout — fraction of page width where the main column starts.
    # 0.0 = full-width PDF (no sidebar). 0.35 = Philosopher's Notes style.
    col_split: float         = 0.35

    # Heading detection thresholds (multiples of page's median font size)
    h1_size_ratio: float     = 1.35   # size >= median * this → H1
    h2_size_ratio: float     = 1.10   # size >= median * this → H2
    h2_bold_ratio: float     = 0.95   # bold AND size >= median * this → H2

    # Atomic splitting: minimum word count for a section to get its own note
    atomic_min_words: int    = 80

    overwrite_stubs: bool    = False
    atomic_notes: bool       = True


# ══════════════════════════════════════════════════════════════════════════════
# Data classes
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
    attribution: str   # raw, will be cleaned by Claude
    page: int = 0


@dataclass
class DocumentStructure:
    source_file: str
    page_count: int
    blocks: list = field(default_factory=list)   # list[Block]
    pull_quotes: list = field(default_factory=list)  # list[PullQuote]

    def to_prompt_text(self) -> str:
        """
        Serialize to a labeled plain-text format that Claude can parse cleanly.
        H1/H2 markers tell Claude exactly where section boundaries are.
        """
        lines = []
        for b in self.blocks:
            if b.kind == "heading":
                lines.append(f"\n[H1] {b.text}")
            elif b.kind == "subheading":
                lines.append(f"\n[H2] {b.text}")
            elif b.kind == "body":
                lines.append(b.text)
            # pull_quote/attribution blocks are captured separately; skip here
        lines.append("\n\n[PULL QUOTES FROM SIDEBAR]")
        for pq in self.pull_quotes:
            lines.append(f'[QUOTE] "{pq.text}"')
            if pq.attribution:
                lines.append(f"[ATTR]  {pq.attribution}")
        return "\n".join(lines).strip()


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Font-aware structured extraction
# ══════════════════════════════════════════════════════════════════════════════

_HEADER_FOOTER_RE = re.compile(
    r"(Philosopher'?s\s+Notes\s*\|)|(^\d+\s+Philosopher'?s\s+Notes)",
    re.IGNORECASE
)


def _is_junk(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if _HEADER_FOOTER_RE.search(t):
        return True
    if re.fullmatch(r"\d+", t):   # lone page number
        return True
    return False


def _page_font_baseline(page_dict: dict) -> float:
    """Compute median font size across all text spans on the page."""
    sizes = [
        span["size"]
        for block in page_dict.get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["text"].strip()
    ]
    if not sizes:
        return 10.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def _merge_block_spans(block: dict) -> tuple[str, float, bool, bool]:
    """
    Return (text, avg_font_size, is_bold, is_italic) for a block dict.
    Bold = majority of chars are in bold spans.
    Italic = majority of chars are in italic spans.
    """
    spans = [
        span
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["text"].strip()
    ]
    if not spans:
        return "", 0.0, False, False

    total_chars = sum(len(s["text"]) for s in spans)
    bold_chars = sum(len(s["text"]) for s in spans if s["flags"] & 16)
    italic_chars = sum(len(s["text"]) for s in spans if s["flags"] & 2)
    avg_size = sum(s["size"] * len(s["text"]) for s in spans) / max(total_chars, 1)
    text = " ".join(
        " ".join(sp["text"] for sp in line.get("spans", []))
        for line in block.get("lines", [])
    ).strip()
    # Fix hyphenated line-break artifacts
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    is_bold = bold_chars > total_chars * 0.5
    is_italic = italic_chars > total_chars * 0.6
    return text, avg_size, is_bold, is_italic


def _looks_like_quote(text: str) -> bool:
    """Block starts with an opening quotation mark — it's a pull quote body."""
    return text.startswith(('"', '\u201c', '\u2018'))


def _looks_like_attribution(text: str) -> bool:
    """Block is an attribution line starting with ~ or — ."""
    return bool(re.match(r"^[~\u2014\u2013]\s*\S", text))


def extract_structured_pdf(pdf_path: Path, cfg: Config) -> DocumentStructure:
    """
    Font-aware extraction using get_text("dict").
    Classifies every block as heading/subheading/body/pull_quote/attribution.
    Sidebar pull quotes are extracted as PullQuote objects.
    """
    doc = fitz.open(pdf_path)
    doc_struct = DocumentStructure(
        source_file=pdf_path.name,
        page_count=len(doc),
    )

    for page_num, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict")
        baseline  = _page_font_baseline(page_dict)
        pw        = page.rect.width
        split_x   = pw * cfg.col_split

        # Collect blocks with their top-left y for sorting
        raw_blocks = []
        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:    # 0 = text block; skip image blocks
                continue
            x0, y0, x1, _ = b["bbox"]
            cx = (x0 + x1) / 2
            raw_blocks.append((y0, cx < split_x, b))

        raw_blocks.sort(key=lambda t: t[0])   # top-to-bottom

        # Collect sidebar blocks for this page sorted top-to-bottom
        sidebar_raw = []
        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:
                continue
            x0, y0, x1, _ = b["bbox"]
            cx = (x0 + x1) / 2
            if cx >= split_x:
                continue
            text = " ".join(
                sp["text"]
                for line in b.get("lines", [])
                for sp in line.get("spans", [])
            ).strip()
            # Normalize internal whitespace from multi-span assembly
            text = re.sub(r"  +", " ", text)
            if text and not _is_junk(text):
                sidebar_raw.append((y0, text))

        sidebar_raw.sort(key=lambda t: t[0])

        # Stateful pairing: quote block followed by attribution block
        pending_quote_text: Optional[str] = None
        for _, text in sidebar_raw:
            if _looks_like_attribution(text):
                attr = re.sub(r"^[~\u2014\u2013]\s*", "", text).strip()
                if pending_quote_text:
                    clean_q = pending_quote_text.strip("\u201c\u201d\"'")
                    doc_struct.pull_quotes.append(
                        PullQuote(text=clean_q, attribution=attr, page=page_num)
                    )
                    pending_quote_text = None
                # Orphan attribution — skip
                continue

            if pending_quote_text:
                # Previous quote had no attribution; emit it as-is
                clean_q = pending_quote_text.strip("\u201c\u201d\"'")
                doc_struct.pull_quotes.append(
                    PullQuote(text=clean_q, attribution="", page=page_num)
                )
                pending_quote_text = None

            if _looks_like_quote(text):
                pending_quote_text = text
            # Otherwise it's a sidebar label (Big Ideas list etc.) — skip

        # Flush any trailing quote without attribution
        if pending_quote_text:
            clean_q = pending_quote_text.strip("\u201c\u201d\"'")
            doc_struct.pull_quotes.append(
                PullQuote(text=clean_q, attribution="", page=page_num)
            )

        # ── Main column blocks ─────────────────────────────────────────────
        for _y0, is_sidebar, b in raw_blocks:
            if is_sidebar:
                continue   # already handled above

            text, avg_size, is_bold, _is_italic = _merge_block_spans(b)
            if _is_junk(text):
                continue

            if avg_size >= baseline * cfg.h1_size_ratio:
                kind, level = "heading", 1
            elif avg_size >= baseline * cfg.h2_size_ratio or (
                is_bold and avg_size >= baseline * cfg.h2_bold_ratio
            ):
                kind, level = "subheading", 2
            else:
                kind, level = "body", 0

            doc_struct.blocks.append(Block(
                text=text,
                kind=kind,
                level=level,
                font_size=avg_size,
                is_sidebar=False,
                page=page_num,
            ))

    return doc_struct


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 — Concept Dictionary
# ══════════════════════════════════════════════════════════════════════════════

class ConceptDictionary:
    """
    Persistent cross-PDF concept registry stored as concepts_dictionary.json
    in the vault root. Grows automatically as PDFs are processed.
    """

    def __init__(self, vault_path: Path):
        self.path = vault_path / "concepts_dictionary.json"
        self.data: dict = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, canonical: str, aliases: list[str] = None, note_path: str = ""):
        key = canonical.lower().strip()
        if not key or len(key) < 3:
            return
        if key in self.data:
            existing_aliases = set(self.data[key].get("aliases", []))
            existing_aliases.update(
                a.lower().strip() for a in (aliases or [])
                if a.lower().strip() != key
            )
            self.data[key]["aliases"] = sorted(existing_aliases)
            if note_path:
                self.data[key]["note_path"] = note_path
        else:
            self.data[key] = {
                "canonical": canonical,
                "aliases": sorted(
                    a.lower().strip() for a in (aliases or [])
                    if a.lower().strip() != key
                ),
                "note_path": note_path,
            }

    def fuzzy_lookup(self, term: str, threshold: int = 85) -> Optional[str]:
        """Return canonical name if fuzzy match found above threshold, else None."""
        key = term.lower().strip()
        if key in self.data:
            return self.data[key]["canonical"]
        if not HAS_RAPIDFUZZ:
            return None
        all_terms = {}
        for k, entry in self.data.items():
            all_terms[k] = entry["canonical"]
            for alias in entry.get("aliases", []):
                all_terms[alias] = entry["canonical"]
        result = rfprocess.extractOne(
            key, list(all_terms.keys()),
            scorer=fuzz.ratio, score_cutoff=threshold,
        )
        if result:
            matched_term, _score, _idx = result
            return all_terms[matched_term]
        return None

    def _build_term_map(self) -> list[tuple[str, str]]:
        """Return [(term, canonical), ...] sorted longest-first."""
        term_map = {}
        for key, entry in self.data.items():
            canonical = entry["canonical"]
            term_map[key] = canonical
            for alias in entry.get("aliases", []):
                term_map[alias] = canonical
        return sorted(term_map.items(), key=lambda x: len(x[0]), reverse=True)

    def autolink(self, text: str) -> str:
        """
        Insert [[canonical]] wiki-links into body text.
        - Skips YAML frontmatter
        - Skips text already inside [[...]]
        - Links each concept at most once (first occurrence)
        - Skips headers (lines starting with #)
        """
        if not self.data:
            return text

        # Preserve YAML frontmatter verbatim
        fm_match = re.match(r"^(---\n.*?\n---\n)", text, re.DOTALL)
        if fm_match:
            frontmatter = fm_match.group(1)
            body = text[len(frontmatter):]
        else:
            frontmatter = ""
            body = text

        term_map = self._build_term_map()
        linked_canonicals: set[str] = set()   # track what's already been linked

        # Split body into [plain_text, [[existing_link]], plain_text, ...]
        # Only process plain_text segments
        segments = re.split(r"(\[\[[^\]]+\]\])", body)

        for term, canonical in term_map:
            if canonical in linked_canonicals:
                continue
            pattern = re.compile(
                rf"(?<!\w)\b{re.escape(term)}\b(?!\w)",
                re.IGNORECASE,
            )
            for i, seg in enumerate(segments):
                if i % 2 == 1:   # existing [[link]], skip
                    continue
                # Skip header lines
                lines = seg.split("\n")
                new_lines = []
                for line in lines:
                    if line.strip().startswith("#"):
                        new_lines.append(line)
                        continue
                    if canonical not in linked_canonicals:
                        new_line, count = pattern.subn(f"[[{canonical}]]", line, count=1)
                        if count:
                            linked_canonicals.add(canonical)
                        new_lines.append(new_line)
                    else:
                        new_lines.append(line)
                segments[i] = "\n".join(new_lines)

        return frontmatter + "".join(segments)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 3 — Claude analysis
# ══════════════════════════════════════════════════════════════════════════════

ANALYSIS_SYSTEM = """
You are building an Obsidian Zettelkasten vault from book-summary PDFs.
The input is a labeled document where:
  [H1] = major section heading
  [H2] = sub-heading
  [QUOTE] / [ATTR] = sidebar pull-quote and its attribution

Return ONLY a single valid JSON object — no markdown fences, no preamble.
Schema:

{
  "title": "canonical book title",
  "author": "book author full name",
  "notes_author": "summary/notes author if different, else null",
  "year": "publication year or null",
  "series": "series name or null",
  "tags": ["kebab-case", "topic", "tags"],
  "one_liner": "one sentence capturing the core thesis",
  "big_ideas": ["short string per key takeaway"],

  "sections": [
    {
      "heading": "section title (match [H1] markers exactly)",
      "summary": "2–4 sentence summary of this section",
      "key_insight": "single most important idea from this section",
      "atomic_worthy": true,
      "concepts_referenced": ["concepts from this section that appear in the top-level concepts list"],
      "quote_indices": [0, 2]
    }
  ],

  "quotes": [
    {
      "text": "quote text, cleaned",
      "attribution": "full name of speaker/author, normalized",
      "source": "pull_quote or inline"
    }
  ],

  "people": [
    {
      "name": "full name",
      "role": "philosopher | author | historical figure | etc.",
      "context": "one sentence: why they appear"
    }
  ],

  "books_mentioned": [
    {
      "title": "exact title",
      "author": "full name or null"
    }
  ],

  "concepts": ["Reusable concept names worth their own Obsidian node"],
  "connections": ["Broader themes or MOC names this note belongs in"]
}

Rules:
- sections[].atomic_worthy = true when the section has a distinct, standalone insight
  and enough content to be worth its own note (roughly 80+ words of content).
- Capture EVERY named person and EVERY book mentioned, no matter how briefly.
- For concepts, prefer reusable cross-book ideas: 'cardinal virtues', 'satyagraha',
  'comparative advantage', 'soul force', 'dialectical behavior therapy'.
- Normalize all attribution names to full name (e.g. 'MARCUS AURELIUS' → 'Marcus Aurelius').
- quote_indices reference the position in the quotes array (0-indexed).
"""


ENTITIES_SYSTEM = """
You are building an Obsidian Zettelkasten. Given a labeled book-summary document,
return ONLY a valid JSON object — no markdown fences, no preamble.

Schema:
{
  "title": "canonical book title",
  "author": "book author full name",
  "notes_author": "summary author if different, else null",
  "year": "publication year or null",
  "series": "series name or null",
  "tags": ["kebab-case", "topic", "tags"],
  "one_liner": "one sentence capturing the core thesis",
  "big_ideas": ["short string per key takeaway — 5 to 8 items"],
  "people": [
    {"name": "full name", "role": "philosopher|author|etc", "context": "one sentence why they appear"}
  ],
  "books_mentioned": [
    {"title": "exact title", "author": "full name or null"}
  ],
  "concepts": ["reusable concept names worth their own Obsidian node"],
  "connections": ["broader MOC names this note belongs in"]
}

Capture EVERY named person and EVERY book mentioned, no matter how briefly.
"""

SECTIONS_SYSTEM = """
You are building an Obsidian Zettelkasten. Given a labeled book-summary document
and its section headings, return ONLY a valid JSON object — no markdown fences, no preamble.

Schema:
{
  "sections": [
    {
      "heading": "section title (match [H1] markers exactly)",
      "summary": "3-5 sentence summary of this section",
      "key_insight": "single most important idea from this section",
      "atomic_worthy": true,
      "concepts_referenced": ["concepts relevant to this section"],
      "quote_indices": [0, 1]
    }
  ],
  "quotes": [
    {
      "text": "quote text cleaned up",
      "attribution": "full name normalized (e.g. MARCUS AURELIUS -> Marcus Aurelius)",
      "source": "pull_quote or inline"
    }
  ]
}

atomic_worthy = true when the section has a standalone insight worth its own note (roughly 80+ words).
quote_indices reference the position in the quotes array (0-indexed).
Include ALL quotes from both [QUOTE] blocks and inline quotes in the main text.
"""


def _call_claude(client, model: str, system: str, user: str) -> dict:
    """Single Claude call with JSON cleaning and up to 3 retries on parse error."""
    def _clean(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text.strip())
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
        return text

    user_content = user
    last_err = None
    for attempt in range(1, 4):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = _clean(msg.content[0].text)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            print(f"        JSON parse error (attempt {attempt}/3): {e}")
            if attempt < 3:
                # Retry original prompt — don't send a corrective message
                time.sleep(2)
    raise RuntimeError(f"Claude returned invalid JSON after 3 attempts: {last_err}")


def analyze(doc_struct: DocumentStructure, cfg: Config) -> dict:
    """
    Two-pass analysis to stay well under token limits:
      Pass 1 — metadata, entities (people/books/concepts), big ideas
      Pass 2 — section summaries, key insights, quotes
    Results are merged into one dict.
    """
    client = anthropic.Anthropic()

    prompt_text = doc_struct.to_prompt_text()
    max_chars = 40_000
    if len(prompt_text) > max_chars:
        prompt_text = prompt_text[:max_chars] + "\n\n[... truncated ...]"

    doc_header = f"Source file: {doc_struct.source_file}\n\nDocument:\n\n{prompt_text}"

    # Pass 1: entities + metadata
    print("        Pass 1/2: entities & metadata...")
    entities = _call_claude(client, cfg.claude_model, ENTITIES_SYSTEM, doc_header)

    # Pass 2: sections + quotes
    print("        Pass 2/2: sections & quotes...")
    headings = [b.text for b in doc_struct.blocks if b.kind == "heading"]
    headings_note = (
        f"The document has these main section headings: {headings}\n\n"
        + doc_header
    )
    sections_data = _call_claude(client, cfg.claude_model, SECTIONS_SYSTEM, headings_note)

    # Merge
    return {**entities, **sections_data}


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 — Note generation
# ══════════════════════════════════════════════════════════════════════════════

def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"\s+", "-", s.strip())
    return s.lower()


def _safe_title(name: str) -> str:
    """Strip Windows-invalid filename characters so wikilinks match actual filenames."""
    return re.sub(r'[:\\/*?"<>|]', '', name).strip()


def _short_title(name: str) -> str:
    """Return only the main title — everything before a colon subtitle — safe for filenames and folders."""
    short = name.split(":")[0].strip()
    return _safe_title(short)


def _wiki(name: str) -> str:
    return f"[[{_short_title(name)}]]"


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _append_mention(stub_path: Path, source_title: str, section: str = "## Mentioned In"):
    """
    Idempotently append a backlink to a stub note.
    If the section heading doesn't exist, create it at the end.
    """
    if not stub_path.exists():
        return
    content = stub_path.read_text(encoding="utf-8")
    entry = f"- [[{_short_title(source_title)}]]"
    if entry in content:
        return   # already linked
    if section in content:
        content = content.replace(section, f"{section}\n{entry}", 1)
    else:
        content = content.rstrip() + f"\n\n{section}\n{entry}\n"
    stub_path.write_text(content, encoding="utf-8")


# ── Atomic notes ──────────────────────────────────────────────────────────────

def generate_atomic_note(
    section: dict,
    analysis: dict,
    atomic_dir: Path,
    concept_dict: ConceptDictionary,
    cfg: Config,
) -> Optional[Path]:
    """
    Write one atomic note per qualifying section.
    Returns the path written, or None if skipped.
    """
    heading = section.get("heading", "Untitled")
    summary = section.get("summary", "")
    key_insight = section.get("key_insight", "")

    # Skip if the heading is essentially the book title itself (avoids ghost duplicate notes)
    title = analysis.get("title", "")
    if _slug(heading) == _slug(title) or _slug(heading).startswith(_slug(title)):
        return None

    # Enforce minimum word count
    word_count = len(summary.split())
    if not section.get("atomic_worthy", False) or word_count < cfg.atomic_min_words:
        return None

    title = analysis.get("title", "Untitled")
    author = analysis.get("author", "")
    tags = analysis.get("tags", [])
    all_quotes = analysis.get("quotes", [])
    concepts_referenced = section.get("concepts_referenced", [])
    quote_indices = section.get("quote_indices", [])

    section_quotes = [
        all_quotes[i] for i in quote_indices
        if isinstance(i, int) and 0 <= i < len(all_quotes)
    ]

    tag_str = "\n".join(f"  - {t}" for t in tags)

    frontmatter = textwrap.dedent(f"""\
        ---
        title: "{heading}"
        parent: "[[{_short_title(title)}]]"
        author: "[[{_short_title(author)}]]"
        type: atomic-note
        tags:
        {tag_str}
        ---
    """).strip()

    lines = [
        frontmatter, "",
        f"# {heading}", "",
        f"**Source:** [[{_short_title(title)}]] | **Author:** [[{_short_title(author)}]]",
        "",
        "## Summary", "",
        summary, "",
    ]

    if key_insight:
        lines += [
            "> [!insight]",
            f"> {key_insight}",
            "",
        ]

    if section_quotes:
        lines += ["## Key Quotes", ""]
        for q in section_quotes:
            attr = q.get("attribution", "")
            qtext = q.get("text", "").replace("\n", " ")
            if attr:
                lines.append(f"> {qtext}\n> — {_wiki(attr)}\n")
            else:
                lines.append(f"> {qtext}\n")

    if concepts_referenced:
        lines += ["## Concepts", ""]
        lines.append(", ".join(_wiki(c) for c in concepts_referenced))
        lines.append("")

    lines += ["## Connections", ""]

    content = concept_dict.autolink("\n".join(lines))
    out_path = atomic_dir / f"{_slug(heading)}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ── MOC (Map of Content) ──────────────────────────────────────────────────────

def generate_moc(
    analysis: dict,
    doc_struct: DocumentStructure,
    atomic_paths: dict,   # heading → Path
    concept_dict: ConceptDictionary,
    cfg: Config,
) -> Path:
    """
    Write the parent MOC note. Sections with atomic notes become transclusions.
    Sections without get their summaries inlined.
    """
    title        = analysis.get("title", "Untitled")

    out_dir = cfg.vault / cfg.source_notes_dir / _short_title(title)
    _ensure_dir(out_dir)
    author       = analysis.get("author", "")
    notes_author = analysis.get("notes_author") or ""
    year         = analysis.get("year") or ""
    series       = analysis.get("series") or ""
    tags         = analysis.get("tags", [])
    one_liner    = analysis.get("one_liner", "")
    big_ideas    = analysis.get("big_ideas", [])
    sections     = analysis.get("sections", [])
    quotes       = analysis.get("quotes", [])
    people       = analysis.get("people", [])
    books        = analysis.get("books_mentioned", [])
    concepts     = analysis.get("concepts", [])
    connections  = analysis.get("connections", [])

    tag_str = "\n".join(f"  - {t}" for t in tags)

    fm_lines = [
        "---",
        f'title: "{_short_title(title)}"',
        f'author: "[[{_short_title(author)}]]"',
    ]
    if notes_author:
        fm_lines.append(f'notes_author: "[[{_short_title(notes_author)}]]"')
    if year:
        fm_lines.append(f"year: {year}")
    if series:
        fm_lines.append(f'series: "{series}"')
    fm_lines += [
        f"source_pdf: \"{doc_struct.source_file}\"",
        "type: source-moc",
        f"tags:\n{tag_str}",
        "---",
    ]
    frontmatter = "\n".join(fm_lines)

    lines = [frontmatter, "", f"# {_short_title(title)}", ""]

    if one_liner:
        lines += [f"> {one_liner}", ""]

    # Big ideas
    if big_ideas:
        lines += ["## Big Ideas", ""]
        for idea in big_ideas:
            lines.append(f"- {idea}")
        lines.append("")

    # Contents — transclusions for atomic notes, inline summaries otherwise
    if sections:
        lines += ["## Contents", ""]
        for s in sections:
            heading = s.get("heading", "")
            if heading in atomic_paths:
                # Path relative to vault root for the transclusion
                rel = atomic_paths[heading].relative_to(cfg.vault)
                # Obsidian transclusion — strip .md suffix
                embed = str(rel).replace("\\", "/").removesuffix(".md")
                lines += [f"### {heading}", "", f"![[{embed}]]", ""]
            else:
                # Inline summary for short/non-atomic sections
                lines += [
                    f"### {heading}", "",
                    s.get("summary", ""),
                    "",
                    f"**Key insight:** {s.get('key_insight', '')}",
                    "",
                ]

    # Quote index — all quotes in one place for scanning
    if quotes:
        lines += ["## Quote Index", ""]
        for q in quotes:
            attr = q.get("attribution", "")
            qtext = q.get("text", "").replace("\n", " ")
            if attr:
                lines.append(f"> {qtext}\n> — {_wiki(attr)}\n")
            else:
                lines.append(f"> {qtext}\n")
        lines.append("")

    # Mentioned works
    if books:
        lines += ["## Mentioned Works", ""]
        for b in books:
            btitle  = b.get("title", "")
            bauthor = b.get("author", "")
            entry = f"- {_wiki(btitle)}"
            if bauthor:
                entry += f" by {_wiki(bauthor)}"
            lines.append(entry)
        lines.append("")

    # People
    if people:
        lines += ["## People", ""]
        for p in people:
            name = p.get("name", "")
            role = p.get("role", "")
            ctx  = p.get("context", "")
            lines.append(f"- {_wiki(name)} — *{role}* — {ctx}")
        lines.append("")

    # Concepts
    if concepts:
        lines += ["## Concepts", ""]
        lines.append(", ".join(_wiki(c) for c in concepts))
        lines.append("")

    # Connections / MOC
    if connections:
        lines += ["## Connections", ""]
        for c in connections:
            lines.append(f"- [[{_short_title(c)}]]")
        lines.append("")

    content = concept_dict.autolink("\n".join(lines))
    out_path = out_dir / f"{_short_title(title)}.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"  ✓ MOC note     → {out_path.relative_to(cfg.vault)}")
    return out_path


# ── Entity stubs ──────────────────────────────────────────────────────────────

def generate_entity_stubs(
    analysis: dict,
    concept_dict: ConceptDictionary,
    cfg: Config,
) -> dict:
    """
    Create stub notes for people, books, and concepts.
    Returns {type: [Path, ...]} for all written paths.
    """
    title = analysis.get("title", "Untitled")
    written = {"people": [], "books": [], "concepts": []}

    # ── People ────────────────────────────────────────────────────────────────
    people_dir = cfg.vault / cfg.people_dir
    _ensure_dir(people_dir)

    for p in analysis.get("people", []):
        name = p.get("name", "").strip()
        role = p.get("role", "")
        ctx  = p.get("context", "")
        if not name:
            continue
        out_path = people_dir / f"{_safe_title(name)}.md"
        if out_path.exists():
            _append_mention(out_path, title, "## Appearances")
            if not cfg.overwrite_stubs:
                continue

        content = textwrap.dedent(f"""\
            ---
            title: "{name}"
            type: person
            role: "{role}"
            tags:
              - person
            ---
            # {name}

            *{role}*

            {ctx}

            ## Notes

            ## Works

            ## Appearances
            - [[{_short_title(title)}]]
        """)
        out_path.write_text(content, encoding="utf-8")
        written["people"].append(out_path)
        print(f"  ✓ Person stub  → {out_path.relative_to(cfg.vault)}")

    # ── Books ─────────────────────────────────────────────────────────────────
    books_dir = cfg.vault / cfg.books_dir
    _ensure_dir(books_dir)

    for b in analysis.get("books_mentioned", []):
        btitle  = (b.get("title") or "").strip()
        bauthor = (b.get("author") or "").strip()
        if not btitle:
            continue
        out_path = books_dir / f"{_safe_title(btitle)}.md"
        if out_path.exists():
            _append_mention(out_path, title, "## Mentioned In")
            if not cfg.overwrite_stubs:
                continue

        author_line = f'author: "[[{_short_title(bauthor)}]]"' if bauthor else ""
        author_body = f"**Author:** [[{_short_title(bauthor)}]]" if bauthor else ""
        content = textwrap.dedent(f"""\
            ---
            title: "{_short_title(btitle)}"
            {author_line}
            type: book
            tags:
              - book
            ---
            # {_short_title(btitle)}

            {author_body}

            ## Summary

            ## Key Ideas

            ## My Notes

            ## Mentioned In
            - [[{_short_title(title)}]]
        """)
        out_path.write_text(content, encoding="utf-8")
        written["books"].append(out_path)
        print(f"  ✓ Book stub    → {out_path.relative_to(cfg.vault)}")

    # ── Concepts ──────────────────────────────────────────────────────────────
    concepts_dir = cfg.vault / cfg.concepts_dir
    _ensure_dir(concepts_dir)

    for concept in analysis.get("concepts", []):
        concept = concept.strip()
        if not concept:
            continue
        out_path = concepts_dir / f"{_safe_title(concept)}.md"
        note_path_str = str(out_path.relative_to(cfg.vault)).replace("\\", "/")

        # Register in concept dictionary (regardless of whether stub exists)
        concept_dict.add(concept, note_path=note_path_str)

        if out_path.exists():
            _append_mention(out_path, title, "## Sources")
            if not cfg.overwrite_stubs:
                continue

        content = textwrap.dedent(f"""\
            ---
            title: "{_short_title(concept)}"
            type: concept
            tags:
              - concept
            ---
            # {_short_title(concept)}

            ## Definition

            ## Why It Matters

            ## Related Concepts

            ## Sources
            - [[{_short_title(title)}]]
        """)
        out_path.write_text(content, encoding="utf-8")
        written["concepts"].append(out_path)
        print(f"  ✓ Concept stub → {out_path.relative_to(cfg.vault)}")

    return written


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def process_pdf(pdf_path: Path, cfg: Config, save_debug: bool = False):
    print(f"\n{'═'*60}")
    print(f"  {pdf_path.name}")
    print(f"{'═'*60}")

    # ── 1. Extract ─────────────────────────────────────────────────────────
    print("  [1/4] Extracting structured text...")
    doc_struct = extract_structured_pdf(pdf_path, cfg)
    print(f"        {len(doc_struct.blocks)} blocks · {len(doc_struct.pull_quotes)} pull quotes")

    if save_debug:
        debug = {
            "source_file": doc_struct.source_file,
            "blocks": [
                {"kind": b.kind, "level": b.level, "text": b.text, "page": b.page}
                for b in doc_struct.blocks
            ],
            "pull_quotes": [
                {"text": pq.text, "attribution": pq.attribution, "page": pq.page}
                for pq in doc_struct.pull_quotes
            ],
        }
        dbg_path = pdf_path.with_suffix(".extracted.json")
        dbg_path.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"        Debug → {dbg_path.name}")

    # ── 2. Load concept dictionary ─────────────────────────────────────────
    concept_dict = ConceptDictionary(cfg.vault)

    # ── 3. Analyze ─────────────────────────────────────────────────────────
    print("  [2/4] Analyzing with Claude...")
    analysis = analyze(doc_struct, cfg)

    if save_debug:
        analysis_path = pdf_path.with_suffix(".analysis.json")
        analysis_path.write_text(
            json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"        Analysis → {analysis_path.name}")

    # ── 4. Generate entity stubs ───────────────────────────────────────────
    print("  [3/4] Generating entity stubs...")
    generate_entity_stubs(analysis, concept_dict, cfg)

    # ── 5. Generate atomic + MOC notes ────────────────────────────────────
    print("  [4/4] Generating notes...")
    title = analysis.get("title", _slug(pdf_path.stem))
    atomic_paths: dict[str, Path] = {}

    if cfg.atomic_notes:
        atomic_dir = cfg.vault / cfg.source_notes_dir / _short_title(title)
        _ensure_dir(atomic_dir)

        for section in analysis.get("sections", []):
            heading = section.get("heading", "")
            path = generate_atomic_note(section, analysis, atomic_dir, concept_dict, cfg)
            if path:
                atomic_paths[heading] = path
                print(f"  ✓ Atomic note  → {path.relative_to(cfg.vault)}")

    generate_moc(analysis, doc_struct, atomic_paths, concept_dict, cfg)

    # ── 5b. Remove any Books stub that duplicates the MOC we just created ──
    books_stub = cfg.vault / cfg.books_dir / f"{_short_title(title)}.md"
    if books_stub.exists():
        books_stub.unlink()
        print(f"  ✓ Removed book stub (superseded by MOC) → {books_stub.relative_to(cfg.vault)}")

    # ── 6. Persist updated concept dictionary ─────────────────────────────
    concept_dict.save()
    print(f"  ✓ Concept dict → concepts_dictionary.json "
          f"({len(concept_dict.data)} entries)")

    print(f"\n  Done. Vault → {cfg.vault.resolve()}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PDF → Obsidian Zettelkasten pipeline (v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes
              python pdf_to_obsidian_v2.py *.pdf    --vault ~/Notes --debug
              python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes --no-atomic
              python pdf_to_obsidian_v2.py book.pdf --vault ~/Notes --col-split 0.0
        """),
    )
    parser.add_argument("pdfs", nargs="+", help="PDF file(s) to process")
    parser.add_argument("--vault",        default=r"C:\Users\abett\OneDrive\Desktop\Obsidian\Vault\Zettlekasten",    help="Obsidian vault root")
    parser.add_argument("--sources-dir",  default="Sources")
    parser.add_argument("--people-dir",   default="People")
    parser.add_argument("--books-dir",    default="Books")
    parser.add_argument("--concepts-dir", default="Concepts")
    parser.add_argument("--col-split",    type=float, default=0.35,
                        help="Sidebar column boundary (0.0 = full-width PDF)")
    parser.add_argument("--h1-ratio",     type=float, default=1.35,
                        help="Font size multiple of median → H1")
    parser.add_argument("--h2-ratio",     type=float, default=1.10,
                        help="Font size multiple of median → H2")
    parser.add_argument("--atomic-min-words", type=int, default=80,
                        help="Minimum summary word count for atomic note")
    parser.add_argument("--no-atomic",    action="store_true",
                        help="Disable atomic note splitting (single source note)")
    parser.add_argument("--overwrite-stubs", action="store_true",
                        help="Overwrite existing stub notes")
    parser.add_argument("--model",        default="claude-opus-4-6")
    parser.add_argument("--debug",        action="store_true",
                        help="Write extracted.json and analysis.json alongside PDF")
    args = parser.parse_args()

    cfg = Config(
        vault          = Path(args.vault).expanduser(),
        source_notes_dir = args.sources_dir,
        people_dir     = args.people_dir,
        books_dir      = args.books_dir,
        concepts_dir   = args.concepts_dir,
        claude_model   = args.model,
        col_split      = args.col_split,
        h1_size_ratio  = args.h1_ratio,
        h2_size_ratio  = args.h2_ratio,
        atomic_min_words = args.atomic_min_words,
        atomic_notes   = not args.no_atomic,
        overwrite_stubs = args.overwrite_stubs,
    )

    pdf_paths = []
    for pdf_str in args.pdfs:
        if "*" in pdf_str or "?" in pdf_str:
            pdf_paths.extend(sorted(Path(".").glob(pdf_str)))
        else:
            pdf_paths.append(Path(pdf_str))

    pdf_paths = [p for p in pdf_paths if p.suffix.lower() == ".pdf"]
    if not pdf_paths:
        print("No PDF files found.")
        sys.exit(1)

    print(f"Processing {len(pdf_paths)} PDF(s) → {cfg.vault.resolve()}")

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"WARNING: {pdf_path} not found, skipping.")
            continue
        process_pdf(pdf_path, cfg, save_debug=args.debug)
        if len(pdf_paths) > 1:
            time.sleep(1)


if __name__ == "__main__":
    main()
