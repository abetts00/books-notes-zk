"""
Heroic Zettelkasten MCP Server

Exposes the PDF-to-Obsidian pipeline and vault query tools to any
MCP-compatible AI assistant (Claude Desktop, Cursor, Windsurf, etc.)

Tools:
  process_pdf       — run the ingestion pipeline on a PDF
  enrich_concepts   — fill Definitions from Sources for unenriched concepts
  search_vault      — full-text search across concepts, sources, people
  get_note          — read a specific note by path
  vault_stats       — overview of vault size and coverage

Setup (Claude Desktop):
  Add to claude_desktop_config.json:
  {
    "mcpServers": {
      "heroic-zk": {
        "command": "python",
        "args": ["path/to/heroic-zettlekasten/mcp_server/server.py"],
        "env": {
          "ANTHROPIC_API_KEY": "sk-ant-...",
          "ZK_VAULT": "C:/path/to/your/vault"
        }
      }
    }
  }
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Vault path — set via env var or falls back to current directory
VAULT = Path(os.environ.get("ZK_VAULT", "."))
SCRIPTS = Path(__file__).parent.parent / "scripts"

mcp = FastMCP("heroic-zk")


# ---------------------------------------------------------------------------
# process_pdf
# ---------------------------------------------------------------------------

@mcp.tool()
def process_pdf(
    pdf_path: str,
    profile: str = "auto",
    vault: str = "",
) -> str:
    """
    Process a PDF through the ingestion pipeline.
    Creates source notes, atomic notes, entity stubs, and updates the concept dictionary.

    Args:
        pdf_path: Path to the PDF file (absolute, or relative to vault/raw/)
        profile:  Layout profile — auto | philosophers_notes | shortform | readingraphics | getabstract | generic
        vault:    Path to the Obsidian vault (defaults to ZK_VAULT env var)
    """
    vault_path = Path(vault) if vault else VAULT
    pdf = Path(pdf_path)
    if not pdf.is_absolute():
        pdf = vault_path / "raw" / "pdfs" / "philosophers-notes" / pdf

    if not pdf.exists():
        return f"PDF not found: {pdf}"

    script = SCRIPTS / "pdf_to_obsidian.py"
    result = subprocess.run(
        [sys.executable, str(script), str(pdf),
         "--vault", str(vault_path),
         "--profile", profile],
        capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    return output.strip() or "Pipeline completed."


# ---------------------------------------------------------------------------
# enrich_concepts
# ---------------------------------------------------------------------------

@mcp.tool()
def enrich_concepts(
    min_sources: int = 3,
    limit: int = 20,
    vault: str = "",
) -> str:
    """
    Fill in 'Definitions from Sources' for concept notes that haven't been enriched yet.
    Uses the Claude API to extract what each source says about each concept.

    Args:
        min_sources: Only enrich concepts with at least this many source references
        limit:       Max number of concepts to process in one run
        vault:       Path to the Obsidian vault (defaults to ZK_VAULT env var)
    """
    vault_path = Path(vault) if vault else VAULT
    script = SCRIPTS / "enrich_concepts.py"
    result = subprocess.run(
        [sys.executable, str(script),
         "--vault", str(vault_path),
         "--min-sources", str(min_sources),
         "--limit", str(limit)],
        capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    return output.strip() or "Enrichment completed."


# ---------------------------------------------------------------------------
# search_vault
# ---------------------------------------------------------------------------

@mcp.tool()
def search_vault(
    query: str,
    search_in: str = "concepts",
    vault: str = "",
) -> str:
    """
    Search the vault for notes matching a query.

    Args:
        query:     Search term (matched against filenames and note content)
        search_in: Where to search — concepts | sources | people | books | all
        vault:     Path to the Obsidian vault (defaults to ZK_VAULT env var)
    """
    vault_path = Path(vault) if vault else VAULT

    folder_map = {
        "concepts": ["Concepts"],
        "sources":  ["Sources"],
        "people":   ["People"],
        "books":    ["Books"],
        "all":      ["Concepts", "Sources", "People", "Books"],
    }
    folders = folder_map.get(search_in.lower(), ["Concepts"])

    results = []
    query_lower = query.lower()

    for folder in folders:
        folder_path = vault_path / folder
        if not folder_path.exists():
            continue
        for md_file in sorted(folder_path.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if query_lower in md_file.name.lower() or query_lower in content.lower():
                # Return filename + first meaningful line of content
                rel = md_file.relative_to(vault_path)
                snippet = _snippet(content, query_lower)
                results.append(f"[[{rel}]]\n{snippet}")

    if not results:
        return f"No results found for '{query}' in {search_in}."

    header = f"Found {len(results)} result(s) for '{query}' in {search_in}:\n\n"
    return header + "\n\n".join(results[:20])


def _snippet(content: str, query: str) -> str:
    """Return a short excerpt around the first match."""
    idx = content.lower().find(query)
    if idx == -1:
        lines = [l for l in content.splitlines() if l.strip() and not l.startswith("---") and not l.startswith("#")]
        return lines[0][:120] if lines else ""
    start = max(0, idx - 60)
    end = min(len(content), idx + 120)
    return "..." + content[start:end].replace("\n", " ").strip() + "..."


# ---------------------------------------------------------------------------
# get_note
# ---------------------------------------------------------------------------

@mcp.tool()
def get_note(
    note: str,
    vault: str = "",
) -> str:
    """
    Read the full content of a note from the vault.

    Args:
        note:  Note name or path, e.g. "Stoicism", "Concepts/Stoicism.md",
               "Sources/Atomic Habits/Atomic Habits.md"
        vault: Path to the Obsidian vault (defaults to ZK_VAULT env var)
    """
    vault_path = Path(vault) if vault else VAULT

    # Try direct path first
    candidate = vault_path / note
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")

    # Try appending .md
    if not note.endswith(".md"):
        candidate = vault_path / (note + ".md")
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    # Search for the name across folders
    note_lower = Path(note).stem.lower()
    for folder in ["Concepts", "Sources", "People", "Books"]:
        for md_file in (vault_path / folder).rglob("*.md"):
            if md_file.stem.lower() == note_lower:
                return md_file.read_text(encoding="utf-8")

    return f"Note not found: {note}"


# ---------------------------------------------------------------------------
# vault_stats
# ---------------------------------------------------------------------------

@mcp.tool()
def vault_stats(vault: str = "") -> str:
    """
    Return a summary of vault contents: source count, concept maturity breakdown,
    entity counts, and enrichment progress.

    Args:
        vault: Path to the Obsidian vault (defaults to ZK_VAULT env var)
    """
    vault_path = Path(vault) if vault else VAULT

    def count_files(folder):
        p = vault_path / folder
        return len(list(p.rglob("*.md"))) if p.exists() else 0

    sources = len(list((vault_path / "Sources").iterdir())) if (vault_path / "Sources").exists() else 0
    books   = count_files("Books")
    people  = count_files("People")

    # Concept maturity breakdown
    maturity = {"stub": 0, "developing": 0, "evergreen": 0, "unknown": 0}
    enriched = 0
    total_concepts = 0

    concepts_dir = vault_path / "Concepts"
    if concepts_dir.exists():
        for f in concepts_dir.glob("*.md"):
            total_concepts += 1
            text = f.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'maturity:\s*(\w+)', text)
            key = m.group(1) if m else "unknown"
            maturity[key] = maturity.get(key, 0) + 1
            defs_match = re.search(r'## Definitions from Sources\n(.+?)(?=\n##|\Z)', text, re.DOTALL)
            if defs_match and defs_match.group(1).strip():
                enriched += 1

    lines = [
        f"# Vault Stats — {vault_path.name}",
        "",
        f"**Sources processed:** {sources} books",
        f"**Book stubs:** {books}",
        f"**People:** {people}",
        f"**Concepts:** {total_concepts}",
        "",
        "**Concept maturity:**",
        f"  - stub: {maturity.get('stub', 0)}",
        f"  - developing: {maturity.get('developing', 0)}",
        f"  - evergreen: {maturity.get('evergreen', 0)}",
        "",
        f"**Concepts enriched:** {enriched} / {total_concepts}",
        f"**Concepts needing enrichment:** {total_concepts - enriched}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
