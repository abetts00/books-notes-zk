---
name: pdf-to-obsidian
description: >
  Convert book summary PDFs into interconnected Obsidian vault notes with entity extraction,
  auto-linking, and knowledge graph generation. Use this skill whenever the user wants to:
  process PDFs into Obsidian notes, extract book summaries into markdown, build a Zettelkasten
  from PDF book notes, batch-process Philosopher's Notes or Shortform or ReadingGraphics or
  getAbstract PDFs, create interconnected knowledge notes from any book summary PDF, set up
  or extend a PDF-to-notes pipeline, debug extraction issues with book summary PDFs, or
  configure layout profiles for new PDF formats. Also trigger when the user mentions
  "philosophers notes", "book summary PDF", "obsidian extraction", "vault notes from PDF",
  "entity linking", "concept dictionary", or "atomic notes". This skill handles the full
  pipeline: layout-aware extraction → Claude API analysis → markdown generation → entity
  stub creation → concept auto-linking → bidirectional backlinks.
---

# PDF-to-Obsidian Pipeline

Converts book summary PDFs into a network of interconnected Obsidian markdown notes.

## Architecture Overview

The pipeline has 4 stages:

```
PDF file(s)
  │
  ▼
┌──────────────────────────────┐
│  Stage 1: EXTRACT            │  Layout-aware PDF text extraction
│  - Profile-driven column     │  using PyMuPDF get_text("dict")
│    detection                 │  for font-size-aware heading and
│  - Font-aware heading/body   │  quote detection.
│    classification            │
│  - Sidebar quote extraction  │
│    with attribution          │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  Stage 2: ANALYZE            │  Single Claude API call with
│  - Section boundaries        │  structured JSON output.
│  - Entity extraction         │  Model: claude-sonnet-4-20250514
│    (people, books, concepts) │  (use Sonnet for batch cost)
│  - Quote attribution cleanup │
│  - Tag generation            │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  Stage 3: GENERATE           │  Write source note + MOC parent
│  - Source note with YAML     │  + atomic child notes per section.
│    frontmatter               │  Entity stubs with backlinks.
│  - Atomic section notes      │
│  - Entity stub notes         │
│  - Concept dictionary update │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  Stage 4: LINK               │  Post-generation pass:
│  - Bidirectional backlinks   │  fuzzy-match concepts across
│  - "Mentioned In" updates    │  all notes, append "Mentioned In"
│  - Concept fuzzy-matching    │  sections idempotently.
└──────────────────────────────┘
```

## Dependencies

```bash
pip install pymupdf anthropic rapidfuzz
```

- **PyMuPDF (fitz):** PDF extraction with font/coordinate metadata
- **anthropic:** Claude API for semantic analysis
- **rapidfuzz:** Fuzzy string matching for concept auto-linking

Requires `ANTHROPIC_API_KEY` environment variable.

## Vault Directory Structure (Karpathy-style)

```
vault/
├── CLAUDE.md                        ← Knowledge base schema (auto-copied on first run)
├── concepts_dictionary.json         ← Master concept registry
├── processing_log.json              ← Batch processing tracker
├── raw/                             ← Source material (IMMUTABLE)
│   ├── pdfs/                        ← Book summary PDFs by source
│   │   ├── philosophers-notes/
│   │   ├── shortform/
│   │   └── other/
│   ├── clippings/                   ← Web clips, articles
│   └── personal-notes/              ← Your own reading notes
├── wiki/                            ← LLM-maintained
│   ├── _index.md                    ← Auto-generated master index
│   ├── sources/                     ← Literature notes (1 per PDF)
│   ├── atomic/                      ← Per-section child notes
│   ├── entities/
│   │   ├── people/
│   │   ├── books/
│   │   └── concepts/
│   ├── themes/                      ← Cross-cutting synthesis (LLM-generated)
│   └── queries/                     ← Filed Q&A outputs
├── permanent/                       ← Human-owned (LLM reads, never writes)
│   ├── insights/                    ← Your permanent notes / zettels
│   └── projects/                    ← Book wisdom applied to active projects
└── scripts/
    └── pdf_to_obsidian.py
```

## Layout Profiles

The pipeline uses **layout profiles** to adapt extraction to different PDF formats.
Each profile defines column geometry, heading detection thresholds, and junk-line filters.

Read `references/layout_profiles.md` for the full profile specification and how to create
new profiles for unsupported PDF formats.

### Built-in Profiles

| Profile ID            | Source                    | Layout          | col_split | Notes                                      |
|----------------------|---------------------------|-----------------|-----------|---------------------------------------------|
| `philosophers_notes` | Brian Johnson / Heroic     | 2-col sidebar   | 0.28      | Left sidebar = pull quotes, right = body    |
| `shortform`          | Shortform.com              | Full-width      | 0.0       | Chapter headers, exercise blocks, key points|
| `readingraphics`     | ReadingGraphics.com        | Mixed           | 0.0       | Text pages + infographic pages (skip infog) |
| `getabstract`        | getAbstract.com            | Full-width      | 0.0       | Structured sections, rating box, "What..."  |
| `generic`            | Any full-width book notes  | Full-width      | 0.0       | Relies on font-size heading detection only  |

### Auto-Detection

When no `--profile` flag is passed, the script inspects:
1. Page 1 text for signature strings (e.g. "Philosopher's Notes", "Shortform", "getAbstract")
2. Page geometry for multi-column layout
3. Falls back to `generic` if no match

## Frontmatter Schema

Every note type has a consistent YAML frontmatter schema.

### Source Note
```yaml
---
title: "Right Thing Right Now"
author: "Ryan Holiday"
summarizer: "Brian Johnson"
series: "Philosopher's Notes"
source_pdf: "right-thing-right-now.pdf"
profile: "philosophers_notes"
type: source-note
date_processed: "2026-04-12"
tags:
  - philosophy
  - stoicism
  - justice
---
```

### Atomic Note (section child)
```yaml
---
title: "Right Thing Right Now - The Ultimate Virtue"
parent: "[[Right Thing Right Now]]"
type: atomic-note
section_index: 1
tags:
  - stoicism
  - virtue
---
```

### Entity Stub (People / Books / Concepts)
```yaml
---
title: "Marcus Aurelius"
type: person
aliases:
  - "Aurelius"
  - "Emperor Marcus Aurelius"
---
```

## Analysis Prompt

The Claude API call in Stage 2 uses a structured system prompt. The full prompt is in
`references/analysis_prompt.md`. Key behaviors:

- Returns **JSON only** (no markdown fences, no preamble)
- Extracts: `title`, `author`, `summarizer`, `sections[]`, `pull_quotes[]`,
  `people[]`, `books[]`, `concepts[]`, `tags[]`, `theme`
- Each person/book/concept includes a `context` field explaining relevance
- Pull quotes get cleaned attribution (first name + last name, no titles)

## CLI Usage

```bash
# Single file with auto-detect
python pdf_to_obsidian.py book.pdf --vault ~/Notes

# Batch with explicit profile
python pdf_to_obsidian.py ~/PDFs/*.pdf --vault ~/Notes --profile philosophers_notes

# Full-width PDF, no atomic splitting
python pdf_to_obsidian.py notes.pdf --vault ~/Notes --profile generic --no-atomic

# Debug mode (saves extraction JSON alongside notes)
python pdf_to_obsidian.py book.pdf --vault ~/Notes --debug

# Overwrite existing entity stubs
python pdf_to_obsidian.py book.pdf --vault ~/Notes --overwrite-stubs

# Custom column split for unusual layouts
python pdf_to_obsidian.py book.pdf --vault ~/Notes --col-split 0.40
```

## Config Dataclass

```python
@dataclass
class Config:
    vault: Path              = Path("./vault")
    source_notes_dir: str    = "wiki/sources"
    atomic_dir: str          = "wiki/atomic"
    people_dir: str          = "wiki/entities/people"
    books_dir: str           = "wiki/entities/books"
    concepts_dir: str        = "wiki/entities/concepts"
    themes_dir: str          = "wiki/themes"
    claude_model: str        = "claude-sonnet-4-20250514"
    profile: str             = "auto"
    col_split: float         = 0.28      # overridden by profile
    h1_size_ratio: float     = 1.35
    h2_size_ratio: float     = 1.10
    h2_bold_ratio: float     = 0.95
    atomic_min_words: int    = 50
    atomic_notes: bool       = True
    overwrite_stubs: bool    = False
    debug: bool              = False
```

## Key Implementation Details

### Font-Aware Heading Detection (Stage 1)
Uses `page.get_text("dict")` which returns font size and bold flags per span.
Heading classification uses ratios relative to the page's **median font size**:

- `size >= median * h1_size_ratio` → H1 heading
- `size >= median * h2_size_ratio` → H2 subheading
- Bold AND `size >= median * h2_bold_ratio` → H2 subheading

### Pull Quote Extraction (Stage 1)
For two-column profiles, spans with `x0 < page_width * col_split` are classified
as sidebar content. Italic or larger-than-body text in the sidebar → pull quote.
The next non-quote sidebar text → attribution. Claude cleans attributions in Stage 2.

### Concept Dictionary (Stage 4)
`concepts_dictionary.json` at vault root is the master registry of known concepts.
Structure:
```json
{
  "stoicism": {
    "canonical": "Stoicism",
    "aliases": ["stoic philosophy", "the Stoa"],
    "category": "philosophy"
  }
}
```

New concepts found during analysis are appended. Fuzzy matching (via rapidfuzz,
threshold 85) links mentions in note body text to existing concepts using
`[[Concept Name]]` wiki-links.

### Bidirectional Backlinks (Stage 4)
After generating all notes for a batch, a linking pass:
1. For each entity stub, finds all source notes that mention it
2. Appends/updates a `## Mentioned In` section with links
3. Idempotent — won't duplicate entries on re-runs

### Error Handling for Batch Processing
At 700 PDFs, failures will happen. The pipeline:
- Logs per-file success/failure to `processing_log.json`
- Continues on individual file errors (doesn't abort batch)
- Rate-limits Claude API calls (configurable delay between calls)
- Supports `--resume` flag to skip already-processed files

## Extending for New PDF Formats

To add support for a new book summary format:

1. Get a sample PDF and run with `--profile generic --debug`
2. Inspect the debug JSON to understand the layout
3. Create a new profile entry in `references/layout_profiles.md`
4. Add a detection signature to the auto-detect function
5. Add any format-specific junk-line filters
6. Test on 3-5 samples before batch processing

Read `references/layout_profiles.md` for the full specification.

## Bundled Files

| File | Purpose |
|------|---------|
| `references/layout_profiles.md` | Full profile specs, detection signatures, how to add new ones |
| `references/analysis_prompt.md` | The Claude API system prompt for Stage 2 analysis |
| `references/vault_schema.md` | Karpathy-style vault structure, frontmatter schemas, linking conventions |
| `references/CLAUDE.md` | Drop-in knowledge base schema for vault root (auto-copied on first run) |
| `scripts/pdf_to_obsidian.py` | Main pipeline script |
