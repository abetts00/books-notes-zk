---
name: book-notes-zk
description: >
  Convert book summary PDFs into an interconnected Obsidian Zettelkasten with entity
  extraction, auto-linking, concept enrichment, and knowledge graph generation.
  Use this skill whenever the user wants to: process PDFs into Obsidian notes, build
  a Zettelkasten from book summary PDFs, batch-process Philosopher's Notes, Shortform,
  ReadingGraphics, or getAbstract PDFs, enrich concept notes with definitions from
  source material, find or merge duplicate notes in the vault, set up a new vault from
  scratch, run the ingestion pipeline, debug extraction issues, or configure layout
  profiles for new PDF formats. Also trigger when the user mentions "book summary PDF",
  "obsidian extraction", "vault notes from PDF", "entity linking", "concept dictionary",
  "atomic notes", "philosophers notes", "shortform notes", or "enrich concepts".
---

# book-notes-zk

Converts book summary PDFs into a network of interconnected Obsidian markdown notes,
with concept enrichment via Claude API and an MCP server for vault queries.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup.py` | First-run vault setup — creates directory structure, installs skill, verifies deps |
| `scripts/pdf_to_obsidian.py` | Main ingestion pipeline (Extract → Analyze → Generate → Link) |
| `scripts/enrich_concepts.py` | Fill Definitions from Sources using Claude API |
| `scripts/update_concept_template.py` | Migrate concept files to current schema |
| `scripts/find_duplicates.py` | Find fuzzy duplicate notes across vault |
| `scripts/clean_vault.py` | Vault maintenance utilities |

## Vault Structure

```
your-vault/
├── CLAUDE.md                        ← Knowledge base schema
├── concepts_dictionary.json         ← Master concept registry
├── processing_log.json              ← Tracks processed PDFs for --resume
│
├── raw/                             ← IMMUTABLE — source PDFs live here
│   ├── pdfs/
│   │   ├── philosophers-notes/
│   │   ├── shortform/
│   │   ├── readingraphics/
│   │   ├── getabstract/
│   │   └── other/
│   ├── clippings/
│   └── personal-notes/
│
├── Sources/                         ← One folder per processed book
│   └── Atomic Habits/
│       ├── Atomic Habits.md         ← Source note (literature note + MOC)
│       ├── identity.md              ← Atomic note per section
│       └── ...
│
├── Concepts/                        ← Concept notes (where learning happens)
├── People/                          ← Person stubs with backlinks
├── Books/                           ← Referenced book stubs
│
├── permanent/                       ← Human-owned (pipeline never writes here)
│   ├── insights/                    ← Your own permanent notes
│   └── projects/                    ← Book wisdom applied to active work
│
├── scripts/                         ← Pipeline scripts (copied here by setup)
└── .claude/skills/book-notes-zk/   ← This skill
```

## Frontmatter Schemas

### Source Note
```yaml
---
title: "Atomic Habits"
author: "[[James Clear]]"
notes_author: "[[Brian Johnson]]"
series: "Philosopher's Notes"
source_pdf: "atomic-habits-pn.pdf"
profile: "philosophers_notes"
type: source-moc
date_processed: "2026-04-14"
tags:
  - habits
  - behavior-change
---
```

### Atomic Note (per section)
```yaml
---
title: "Identity"
parent: "[[Atomic Habits]]"
author: "[[James Clear]]"
type: atomic-note
tags:
  - habits
  - identity
---
```

### Concept Note
```yaml
---
title: "antifragility"
aliases: ["anti-fragility"]
type: concept
maturity: stub | developing | evergreen
source_count: 8
tags:
  - concept
---
```

Concept maturity lifecycle:
- `stub` — auto-created, < 5 sources
- `developing` — 5+ sources, Definitions from Sources populated
- `evergreen` — 15+ sources OR human has written in My Synthesis

### Concept Note Body Structure
```markdown
## Definitions from Sources
**[[Book Title]]:** What this source says about the concept in 1-2 sentences.
**[[Another Book]]:** ...

## Cross-Source Synthesis
LLM-written paragraph synthesizing how the concept appears across sources.

## My Synthesis
Human-owned space. LLM never writes here.

## Related Concepts
- [[X]] — why related

## Sources
- [[Book1]]
- [[Book2]]
```

### Person Stub
```yaml
---
title: "James Clear"
aliases: ["Jim Clear"]
type: person
role: "author"
tags:
  - person
---
```

### Book Stub
```yaml
---
title: "Atomic Habits"
author: "[[James Clear]]"
type: book
tags:
  - book
---
```

## Pipeline Architecture

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
│  - Entity extraction         │  Model: claude-sonnet-4-6
│    (people, books, concepts) │  (use Sonnet for batch cost)
│  - Quote attribution cleanup │
│  - Tag generation            │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  Stage 3: GENERATE           │  Write source note + atomic child
│  - Source note with YAML     │  notes per section. Entity stubs
│    frontmatter               │  with backlinks. Concept stubs
│  - Atomic section notes      │  added to Concepts/.
│  - Entity stubs              │
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

## Layout Profiles

| Profile ID | Source | Layout | Notes |
|------------|--------|--------|-------|
| `philosophers_notes` | Brian Johnson / Heroic | 2-col sidebar | Left sidebar = pull quotes |
| `shortform` | Shortform.com | Full-width | Chapter headers, key points |
| `readingraphics` | ReadingGraphics.com | Mixed | Text + infographic pages |
| `getabstract` | getAbstract.com | Full-width | Structured sections, ratings |
| `generic` | Any book notes PDF | Full-width | Font-size detection fallback |

Auto-detected from page 1 content. Override with `--profile`.

Full profile specs and how to add new ones: `references/layout_profiles.md`

## CLI Usage

```bash
# First-time setup
python scripts/setup.py --vault "C:/path/to/vault"

# Single PDF (auto-detects format)
python scripts/pdf_to_obsidian.py book.pdf --vault .

# Batch with explicit profile, skip already-processed
python scripts/pdf_to_obsidian.py raw/pdfs/philosophers-notes/*.pdf \
  --vault . --profile philosophers_notes --resume

# Enrich concepts with Claude (fills Definitions from Sources)
python scripts/enrich_concepts.py --vault . --min-sources 3 --limit 20

# Find duplicate notes
python scripts/find_duplicates.py --vault .

# Debug extraction
python scripts/pdf_to_obsidian.py book.pdf --vault . --debug
```

## Pipeline CLI Options

```
--vault PATH          Obsidian vault root
--profile ID          auto | philosophers_notes | shortform | readingraphics | getabstract | generic
--model MODEL         Claude model (default: claude-sonnet-4-6)
--resume              Skip already-processed files (checks processing_log.json)
--no-atomic           Disable per-section atomic notes
--overwrite-stubs     Overwrite existing entity stubs
--debug               Save extraction debug JSON alongside notes
--delay SECONDS       Rate limit between API calls (default: 1.0)
--col-split FLOAT     Override column split fraction for layout detection
```

## Concept Enrichment

After running the pipeline, enrich concept notes with what each source actually says:

```bash
python scripts/enrich_concepts.py --vault . --min-sources 3 --limit 20
```

This reads each concept's Sources list, finds the corresponding source notes, and uses
Claude to extract a 1-2 sentence definition for each source. Writes into
`## Definitions from Sources`. Safe to re-run — skips already-enriched concepts.

## Concept Dictionary

`concepts_dictionary.json` at vault root is the master registry of known concepts:

```json
{
  "stoicism": {
    "canonical": "Stoicism",
    "aliases": ["stoic philosophy", "the Stoa"],
    "category": "philosophy",
    "definition": "Ancient Greek philosophy emphasizing virtue and reason."
  }
}
```

New concepts found during analysis are appended. Fuzzy matching (rapidfuzz, threshold 85)
links concept mentions in note body text to existing concepts as `[[Concept Name]]` wiki-links.

## Bidirectional Backlinks

After generating all notes for a batch, a linking pass:
1. For each entity stub, finds all source notes that mention it
2. Appends/updates a `## Mentioned In` section with source links
3. Idempotent — won't duplicate entries on re-runs

## Error Handling

The pipeline continues on individual file errors without aborting the batch.
Per-file success/failure logged to `processing_log.json`. Use `--resume` to skip
successfully processed files on re-runs.

## Adding New PDF Formats

1. Run `--profile generic --debug` on a sample
2. Inspect the debug JSON for layout characteristics
3. Add a profile entry following `references/layout_profiles.md`
4. Add a detection signature to the auto-detect function in `pdf_to_obsidian.py`
5. Test on 3-5 samples before batch processing

## Reference Files

| File | Purpose |
|------|---------|
| `references/layout_profiles.md` | Full profile specs and how to add new ones |
| `references/analysis_prompt.md` | Claude API system prompt for Stage 2 analysis |
| `references/vault_schema.md` | Full vault schema, frontmatter specs, linking conventions |
