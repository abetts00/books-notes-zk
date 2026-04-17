# Heroic Zettelkasten

Convert Philosopher's Notes, Shortform, and other book summary PDFs into an interconnected Obsidian knowledge base — with entity extraction, auto-linking, concept enrichment via Claude API, and an MCP server so any AI assistant can query and extend your vault.

Built around Brian Johnson's Philosopher's Notes library and the [Karpathy LLM knowledge base pattern](https://karpathy.ai).

## What it does

Feed it book summary PDFs → get a living knowledge graph:

- **Source notes** with inline `[[wiki-links]]` to every person, book, and concept mentioned
- **Atomic notes** per section (one idea per note, Zettelkasten-style)
- **Concept notes** with definitions pulled from every source that mentions them, plus space for your own synthesis
- **Entity stubs** for people, books, and concepts — with bidirectional backlinks
- **Concept dictionary** that grows across PDFs with fuzzy alias matching
- **MCP server** so Claude Desktop, Cursor, or any MCP-compatible AI can process PDFs and query your vault

## Quick start

```bash
git clone https://github.com/abetts00/heroic-zettlekasten
cd heroic-zettlekasten
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# Process a PDF into your vault
python scripts/pdf_to_obsidian.py book.pdf --vault ~/Notes --profile philosophers_notes

# Enrich concept notes with definitions from source notes
python scripts/enrich_concepts.py --vault ~/Notes --min-sources 3

# Find and review duplicate notes
python scripts/find_duplicates.py --vault ~/Notes
```

## Vault structure

```
your-vault/
├── CLAUDE.md                        <- Schema (auto-created on first run)
├── concepts_dictionary.json         <- Grows with every PDF
├── raw/pdfs/philosophers-notes/     <- Drop PDFs here
├── Sources/                         <- One folder per processed book
│   └── Atomic Habits/
│       ├── Atomic Habits.md         <- Literature note
│       ├── identity.md              <- Atomic note per section
│       └── ...
├── Concepts/                        <- Where learning happens
│   └── antifragility.md            <- Definitions from Sources + your synthesis
├── People/                          <- Person stubs
├── Books/                           <- Referenced book stubs
└── permanent/                       <- Your own notes (LLM never writes here)
    ├── insights/
    └── projects/
```

## Concept notes

Every concept note follows this structure — the machine fills in the sources, you fill in the synthesis:

```markdown
## Definitions from Sources
**[[Atomic Habits]]:** Identity change is the North Star of habit change...
**[[The Daily Stoic]]:** ...

## Cross-Source Synthesis
How this concept appears and evolves across multiple sources.

## My Synthesis
Your space. What do YOU actually think about this?
```

Concept maturity is tracked automatically: `stub` → `developing` (5+ sources) → `evergreen` (15+ sources or you've written your synthesis).

## Supported PDF formats

| Format | Source | Status |
|--------|--------|--------|
| Philosopher's Notes | Brian Johnson / Heroic | Tested on 100+ PDFs |
| Shortform | shortform.com | Profile ready |
| ReadingGraphics | readingraphics.com | Profile ready |
| getAbstract | getabstract.com | Profile ready |
| Generic | Any book notes PDF | Fallback |

Auto-detects format from page content. Override with `--profile`.

## MCP server

Gives any MCP-compatible AI assistant direct access to your vault.

**Tools exposed:**
| Tool | What it does |
|------|-------------|
| `process_pdf` | Run the ingestion pipeline on a PDF |
| `enrich_concepts` | Fill Definitions from Sources for unenriched concepts |
| `search_vault` | Full-text search across concepts, sources, people, books |
| `get_note` | Read any note by name or path |
| `vault_stats` | Overview of vault size, concept maturity, enrichment progress |

**Setup (Claude Desktop):**

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "heroic-zk": {
      "command": "python",
      "args": ["path/to/heroic-zettlekasten/mcp_server/server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "ZK_VAULT": "C:/path/to/your/obsidian/vault"
      }
    }
  }
}
```

**Setup (other MCP clients):** Same pattern — point `command` at `mcp_server/server.py` and set `ZK_VAULT`.

## As a Claude Code skill

Drop into your project's `.claude/skills/` directory:

```
your-project/.claude/skills/pdf-to-obsidian/
├── SKILL.md
├── references/
└── scripts/
```

Then tell Claude Code: *"Process these PDFs into Obsidian notes"* or *"Enrich my concept files"*.

## Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/pdf_to_obsidian.py` | Main ingestion pipeline |
| `scripts/enrich_concepts.py` | Enrich concept notes with Claude API |
| `scripts/update_concept_template.py` | Migrate concept files to new template |
| `scripts/find_duplicates.py` | Find fuzzy duplicate notes across vault |
| `scripts/clean_vault.py` | Vault maintenance utilities |

## CLI options (pdf_to_obsidian.py)

```
--vault PATH          Obsidian vault root (default: ./vault)
--profile ID          auto|philosophers_notes|shortform|readingraphics|getabstract|generic
--model MODEL         Claude model (default: claude-sonnet-4-6)
--resume              Skip already-processed files
--no-atomic           Disable per-section atomic notes
--overwrite-stubs     Overwrite existing entity stubs
--debug               Save extraction debug JSON
--delay SECONDS       Rate limit between API calls (default: 1.0)
```

## Cost estimate

Using Claude Sonnet for ingestion: ~$0.01-0.02 per PDF.
100 PDFs ≈ $1-2. Concept enrichment adds ~$0.005 per concept.

## Dependencies

- Python 3.9+
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF extraction with font metadata
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — Claude API
- [rapidfuzz](https://github.com/maxbachmann/RapidFuzz) — Fuzzy concept matching
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP server

## License

MIT
