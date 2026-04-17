# books-notes-zk

Turn distilled book summary PDFs into an interconnected Obsidian knowledge base — with entity extraction, auto-linking, concept enrichment via Claude API, and an MCP server so any AI assistant can query and extend your vault.

Supports **Philosopher's Notes, Shortform, ReadingGraphics, getAbstract**, and any generic book notes PDF.

## Supported formats

| Service | Format | Status |
|---------|--------|--------|
| [Philosopher's Notes](https://www.heroic.us) | 2-column, sidebar quotes | Tested on 100+ PDFs |
| [Shortform](https://shortform.com) | Full-width, chapter-based | Ready |
| [ReadingGraphics](https://readingraphics.com) | Mixed text + infographic | Ready |
| [getAbstract](https://getabstract.com) | Structured business summaries | Ready |
| Generic | Any book notes PDF | Auto-detect fallback |

Format is auto-detected from page content. Override with `--profile` if needed.

## What it produces

Feed it PDFs → get a living knowledge graph in Obsidian:

- **Source notes** — one per book, with `[[wiki-links]]` to every person, book, and concept mentioned
- **Atomic notes** — one per section, Zettelkasten-style
- **Concept notes** — definitions pulled from every source that mentions them, plus space for your own synthesis
- **Entity stubs** — people, books, and concepts with bidirectional backlinks
- **Concept dictionary** — grows across PDFs with fuzzy alias matching

## Quick start

```bash
git clone https://github.com/abetts00/books-notes-zk
cd books-notes-zk
pip install -r requirements.txt

# Set up a new vault
python scripts/setup.py --vault "C:/path/to/your/obsidian/vault"

# Drop your PDFs into the vault
# vault/raw/pdfs/philosophers-notes/
# vault/raw/pdfs/shortform/
# vault/raw/pdfs/getabstract/
# etc.

# Run the pipeline (auto-detects format, skips already-processed)
cd your-vault
python path/to/books-notes-zk/scripts/pdf_to_obsidian.py raw/pdfs/**/*.pdf --vault . --resume

# Enrich concept notes with definitions from source notes
python path/to/books-notes-zk/scripts/enrich_concepts.py --vault . --min-sources 3
```

## Vault structure

```
your-vault/
├── CLAUDE.md                        ← Schema (auto-created by setup)
├── concepts_dictionary.json
├── raw/                             ← Drop PDFs here (immutable)
│   ├── pdfs/
│   │   ├── philosophers-notes/
│   │   ├── shortform/
│   │   ├── readingraphics/
│   │   ├── getabstract/
│   │   └── other/
│   └── clippings/
├── Sources/                         ← One folder per processed book
│   └── Atomic Habits/
│       ├── Atomic Habits.md         ← Literature note
│       ├── identity.md              ← Atomic note per section
│       └── ...
├── Concepts/                        ← Where learning happens
├── People/
├── Books/
└── permanent/                       ← Your own notes (pipeline never writes here)
    ├── insights/
    └── projects/
```

## Concept notes

The machine fills in the sources, you fill in the synthesis:

```markdown
## Definitions from Sources
**[[Atomic Habits]]:** Identity change is the North Star of habit change...
**[[The Daily Stoic]]:** The Stoics understood this concept as...
**[[Grit]]:** Duckworth frames this as the foundation of perseverance...

## Cross-Source Synthesis
How this concept appears across multiple authors and traditions.

## My Synthesis
Your space — what do YOU actually think about this?
```

Concept maturity is tracked automatically:
- `stub` — created, < 5 sources
- `developing` — 5+ sources, definitions populated
- `evergreen` — 15+ sources or you've written your own synthesis

## MCP server

Gives any MCP-compatible AI assistant (Claude Desktop, Cursor, Windsurf, etc.) direct access to your vault.

**Tools:**
| Tool | What it does |
|------|-------------|
| `process_pdf` | Run the ingestion pipeline on a PDF |
| `enrich_concepts` | Fill Definitions from Sources for unenriched concepts |
| `search_vault` | Full-text search across concepts, sources, people, books |
| `get_note` | Read any note by name or path |
| `vault_stats` | Overview of vault size, maturity breakdown, enrichment progress |

**Setup (Claude Desktop)** — add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "books-notes-zk": {
      "command": "python",
      "args": ["path/to/books-notes-zk/mcp_server/server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "ZK_VAULT": "C:/path/to/your/vault"
      }
    }
  }
}
```

## As a Claude Code skill

The setup script installs the skill automatically. Or drop it manually:

```
your-vault/.claude/skills/books-notes-zk/
├── SKILL.md
├── references/
└── scripts/
```

Then tell Claude Code: *"Process these PDFs into Obsidian notes"*, *"Enrich my concept files"*, or *"Find duplicate notes in my vault"*.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup.py` | First-run vault setup |
| `scripts/pdf_to_obsidian.py` | PDF ingestion pipeline |
| `scripts/enrich_concepts.py` | Enrich concept notes with Claude API |
| `scripts/update_concept_template.py` | Migrate concept files to current schema |
| `scripts/find_duplicates.py` | Find fuzzy duplicate notes |
| `scripts/clean_vault.py` | Vault maintenance utilities |

## Pipeline options

```
--vault PATH          Obsidian vault root
--profile ID          auto | philosophers_notes | shortform | readingraphics | getabstract | generic
--model MODEL         Claude model (default: claude-sonnet-4-6)
--resume              Skip already-processed files
--no-atomic           Disable per-section atomic notes
--overwrite-stubs     Overwrite existing entity stubs
--debug               Save extraction debug JSON
--delay SECONDS       Rate limit between API calls (default: 1.0)
```

## Cost

Using Claude Sonnet for ingestion: ~$0.01–0.02 per PDF.
100 PDFs ≈ $1–2. Concept enrichment adds ~$0.005 per concept.

## Dependencies

- Python 3.9+
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF extraction with font metadata
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — Claude API
- [rapidfuzz](https://github.com/maxbachmann/RapidFuzz) — Fuzzy concept matching
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP server

## Security

Before deploying the MCP server broadly, review [`SECURITY.md`](SECURITY.md) for hardening guidance and operational controls.

## License

MIT
