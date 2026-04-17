# Vault Schema Reference

## Vault Structure (Karpathy-style)

```
vault/
├── CLAUDE.md                        ← Knowledge base schema
├── concepts_dictionary.json         ← Master concept registry
├── processing_log.json              ← Batch processing tracker
├── raw/                             ← Source material (IMMUTABLE)
│   ├── pdfs/{source}/               ← Book summary PDFs by source
│   ├── clippings/                   ← Web clips, articles
│   └── personal-notes/              ← Your own reading notes
├── wiki/                            ← LLM-maintained
│   ├── _index.md                    ← Auto-generated master index
│   ├── sources/                     ← Literature notes (1 per PDF)
│   ├── atomic/                      ← Per-section child notes
│   ├── entities/{people,books,concepts}/
│   ├── themes/                      ← Cross-cutting synthesis articles
│   └── queries/                     ← Filed Q&A outputs
├── permanent/                       ← Human-owned
│   ├── insights/                    ← Your permanent notes / zettels
│   └── projects/                    ← Notes connecting to active work
└── scripts/pdf_to_obsidian.py
```

## Note Types and Frontmatter

### Source Note
Location: `wiki/sources/` | Type: `source-note` | Owner: Pipeline

```yaml
title, author, summarizer, series, source_pdf, profile, type, permanent_note, date_processed, tags
```

`permanent_note: false` → flip to `true` when you add your own thinking in `## My Notes`.

### Atomic Note
Location: `wiki/atomic/` | Type: `atomic-note` | Owner: Pipeline

```yaml
title, parent (wiki-link), type, section_index
```

### Entity Stubs
Location: `wiki/entities/{people,books,concepts}/` | Types: `person`, `book`, `concept`

Concepts track maturity: `stub` (<5 sources) → `developing` (5-14) → `evergreen` (15+).

### Theme Synthesis
Location: `wiki/themes/` | Type: `theme` | Owner: LLM

Cross-cutting synthesis articles generated when concept source_count reaches 5+.

## Linking

- Inline wiki-linking during generation (not post-hoc)
- Entity lookup from current analysis + existing concept dictionary
- Longer terms match first, aliases use display text: `[[80/20 Principle|Pareto Principle]]`
- First occurrence only, already-bracketed terms skipped
- Bidirectional `## Mentioned In` backlinks on all entity stubs (idempotent)

## concepts_dictionary.json

Key: lowercased canonical name. Fields: `canonical`, `aliases`, `category`, `definition`, `source_count`.
