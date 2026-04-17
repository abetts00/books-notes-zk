# Philosophy & Book Notes — LLM Knowledge Base

This is the schema file for maintaining a Zettelkasten-style knowledge base built from book summary PDFs (Philosopher's Notes, Shortform, etc.) and personal reading notes. It follows the Karpathy LLM knowledge base pattern: raw sources go in, compiled wiki comes out.

## Vault Structure

```
vault/
├── CLAUDE.md                    ← You are here. The schema.
├── concepts_dictionary.json     ← Master concept registry (shared across all sources)
├── processing_log.json          ← Batch processing tracker
│
├── raw/                         ← Source material (IMMUTABLE — never edited by LLM)
│   ├── pdfs/                    ← Philosopher's Notes, Shortform, etc. PDFs
│   │   ├── philosophers-notes/  ← ~700 Brian Johnson 6-page summaries
│   │   ├── shortform/           ← Shortform book guides
│   │   ├── readingraphics/      ← ReadingGraphics visual summaries
│   │   └── other/               ← Any other PDF book notes
│   ├── clippings/               ← Web clips, articles, highlights (Obsidian Web Clipper)
│   └── personal-notes/          ← Your own handwritten/typed reading notes
│
├── wiki/                        ← LLM-maintained (human reads, LLM writes)
│   ├── _index.md                ← Master index of all wiki articles
│   ├── _overview.md             ← Knowledge base stats, coverage gaps, health
│   ├── sources/                 ← Literature notes (1 per book summary PDF)
│   │   ├── The 80-20 Principle.md
│   │   └── Right Thing Right Now.md
│   ├── atomic/                  ← Per-section child notes (Zettelkasten zettels)
│   │   ├── The 80-20 Principle - Pareto and 80-20.md
│   │   └── Right Thing Right Now - The Ultimate Virtue.md
│   ├── entities/
│   │   ├── people/              ← Person stubs with accumulated backlinks
│   │   ├── books/               ← Referenced work stubs
│   │   └── concepts/            ← Concept stubs → evolve into evergreen notes
│   ├── themes/                  ← Cross-cutting theme articles (LLM-synthesized)
│   │   ├── stoicism.md          ← Synthesizes all sources that touch stoicism
│   │   ├── 80-20-thinking.md
│   │   └── self-actualization.md
│   └── queries/                 ← Filed outputs from Q&A sessions worth keeping
│
├── permanent/                   ← YOUR notes (human writes, LLM reads)
│   ├── insights/                ← Your own permanent notes, ideas, connections
│   └── projects/                ← Notes connecting book wisdom to active projects
│
└── scripts/
    └── pdf_to_obsidian.py       ← The ingestion pipeline
```

## Conventions

### Key Principles
1. **Never modify files in `raw/`** — they are immutable source documents.
2. **The LLM owns `wiki/`** — human reads, LLM writes.
3. **The human owns `permanent/`** — LLM reads for context, never writes.
4. **`concepts_dictionary.json` is shared** — both pipeline and LLM maintain it.
5. **Cite sources** — every claim traces back to a `raw/` source or is flagged as inferred.
6. **Flag contradictions** — don't silently resolve conflicting information between sources.

### Note Types

| Type | Location | Owner | Frontmatter `type` |
|------|----------|-------|--------------------|
| Literature note (source) | `wiki/sources/` | Pipeline + LLM | `source-note` |
| Atomic note (section) | `wiki/atomic/` | Pipeline | `atomic-note` |
| Person stub | `wiki/entities/people/` | Pipeline + LLM | `person` |
| Book stub | `wiki/entities/books/` | Pipeline + LLM | `book` |
| Concept stub | `wiki/entities/concepts/` | Pipeline + LLM | `concept` |
| Theme synthesis | `wiki/themes/` | LLM | `theme` |
| Permanent note | `permanent/insights/` | Human | `permanent-note` |
| Query result | `wiki/queries/` | LLM | `query` |

### Frontmatter Schema

Source notes:
```yaml
---
title: "The 80/20 Principle"
author: "Richard Koch"
summarizer: "Brian Johnson"
series: "Philosopher's Notes"
source_pdf: "the-8020-principle.pdf"
profile: "philosophers_notes"
type: source-note
permanent_note: false
date_processed: "2026-04-14"
tags: [pareto-principle, productivity, strategy, focus]
---
```

`permanent_note: false` means this is still a literature note — you haven't added your own thinking yet. When you write in the `## My Notes` section, flip it to `true`.

Concept stubs (with maturity tracking):
```yaml
---
title: "Stoicism"
type: concept
category: "philosophy"
maturity: stub | developing | evergreen
source_count: 47
aliases: [stoic philosophy, the Stoa]
---
```

Theme synthesis articles:
```yaml
---
title: "Stoicism Across Sources"
type: theme
sources_synthesized: 47
last_synthesized: "2026-04-14"
tags: [stoicism, philosophy, meta]
---
```

### Linking Conventions
- Wiki-links: `[[Entity Name]]` or `[[Entity Name|display text]]`
- All entity mentions in body text get wiki-linked (first occurrence per note)
- Backlinks: every entity stub has `## Mentioned In` with source links
- Cross-references between theme articles use `## See Also` sections
- Concept aliases link with display text: `[[Stoicism|stoic philosophy]]`

### Concept Maturity Lifecycle

```
stub (auto-created, < 5 sources)
  → developing (5+ sources, LLM adds synthesis paragraph)
    → evergreen (15+ sources OR human-written content in permanent/)
```

When `source_count` crosses 5, the LLM should expand the stub into a developing article that synthesizes how the concept appears across multiple sources. When it crosses 15 OR the human has written a permanent note about it, it becomes an evergreen note.

## Workflows

### 1. Ingest PDFs (Primary Workflow)

Run the pipeline:
```bash
python scripts/pdf_to_obsidian.py raw/pdfs/philosophers-notes/*.pdf \
  --vault . --profile philosophers_notes --resume
```

The pipeline handles Stages 1-4 automatically:
1. Extract (layout-aware, font-based heading detection)
2. Analyze (Claude API for entity/concept extraction)
3. Generate (source notes, atomic notes, entity stubs with inline wiki-linking)
4. Link (concept dictionary update, bidirectional backlinks)

After a batch run, tell Claude Code to:
- Update `wiki/_index.md` with new source notes
- Run the concept maturity check (promote stubs → developing)
- Generate/update theme articles for concepts with 5+ sources
- Update `wiki/_overview.md` with current stats

### 2. Ingest a Web Clipping or Article

When a new file is added to `raw/clippings/`:
1. Read the source completely
2. Identify key concepts, entities, and facts
3. Check `wiki/_index.md` — does a relevant source note exist?
4. Create or update wiki articles
5. Update concept dictionary and backlinks
6. Update `wiki/_index.md`

### 3. Synthesize a Theme

When a concept reaches 5+ source mentions:
1. Read all source notes that reference the concept
2. Read the concept's entity stub
3. Write a theme article in `wiki/themes/` that synthesizes:
   - How different authors approach this concept
   - Points of agreement and disagreement
   - Key quotes across sources
   - Connections to other concepts
4. Update backlinks in relevant source notes

### 4. Answer a Question (Query)

When asked a question against the knowledge base:
1. Read `wiki/_index.md` to identify relevant articles
2. Read those articles fully
3. If needed, read underlying `raw/` sources
4. Synthesize an answer with citations
5. If substantial and reusable, file in `wiki/queries/`

### 5. Lint / Health Check

Run periodically:
1. Orphan check — concepts with no backlinks
2. Stale check — source notes older than theme articles
3. Maturity check — concepts that should be promoted
4. Coverage gaps — highly-cited authors/books with no stub
5. Concept dictionary integrity — duplicates, missing aliases
6. Report findings as a checklist

### 6. Concept Dictionary Maintenance

`concepts_dictionary.json` structure:
```json
{
  "stoicism": {
    "canonical": "Stoicism",
    "aliases": ["stoic philosophy", "the Stoa"],
    "category": "philosophy",
    "definition": "Ancient Greek philosophy emphasizing virtue and reason.",
    "source_count": 47
  }
}
```

Rules:
- Key is always lowercased canonical name
- Aliases are case-insensitive, stored as-is
- `source_count` increments on each new source that mentions the concept
- When merging near-duplicates, keep the more general form as canonical
- Categories: philosophy, psychology, business, science, spirituality, practice, framework, other

## Pipeline Configuration

### Layout Profiles
The pipeline supports multiple PDF formats via layout profiles:
- `philosophers_notes` — 2-column, sidebar quotes, col_split=0.28
- `shortform` — full-width, chapter-based
- `readingraphics` — mixed text + infographic
- `getabstract` — structured business summaries
- `generic` — fallback, font-size detection only

Auto-detects from page 1 content. Override with `--profile`.

### Cost Estimates
- Sonnet (batch): ~$0.01-0.02 per PDF
- 700 PDFs: ~$7-14 total
- Theme synthesis: ~$0.05-0.10 per theme article

### Key Files
| File | Purpose |
|------|---------|
| `CLAUDE.md` | This schema (you are here) |
| `concepts_dictionary.json` | Master concept registry |
| `processing_log.json` | Batch progress tracker |
| `scripts/pdf_to_obsidian.py` | Ingestion pipeline |

## Domain Seed Knowledge

These concepts appear frequently across Philosopher's Notes and should be recognized early:

**Philosophical Traditions:** Stoicism, Buddhism, Taoism, Existentialism, Positive Psychology, Transcendentalism

**Recurring Frameworks:** 80/20 Principle, Flow State, Growth Mindset, Hierarchy of Needs, Hero's Journey, Ikigai, Kaizen, Amor Fati, Eudaimonia, Self-Actualization

**Frequently Referenced People:** Marcus Aurelius, Seneca, Epictetus, Aristotle, Socrates, Lao Tzu, Buddha, Ralph Waldo Emerson, William James, Abraham Maslow, Martin Seligman, Mihaly Csikszentmihalyi, Viktor Frankl, Joseph Campbell, Stephen Covey, Peter Drucker, Jim Rohn, Brian Johnson

**Frequently Referenced Works:** Meditations, Letters from a Stoic, Nicomachean Ethics, Tao Te Ching, Man's Search for Meaning, Flow, Authentic Happiness, The 7 Habits of Highly Effective People, The Hero with a Thousand Faces, Thinking Fast and Slow
