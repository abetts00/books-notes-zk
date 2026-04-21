# Security Notes

This project handles local files (PDFs + Markdown) and can expose operations through an MCP server. Before sharing publicly, review this checklist.

## Threat model highlights

- **Primary risk surface:** `mcp_server/server.py` tools that read/write inside a vault and run pipeline scripts.
- **Assumption:** Vault content and PDF inputs are untrusted until validated.
- **High-impact outcomes:** Local file disclosure, uncontrolled long-running jobs, and accidental secret leakage.

## Current hardening in repo

- MCP note path reads are constrained to remain inside the configured vault root.
- MCP absolute PDF paths are rejected unless they are inside the configured vault root.
- MCP profile input is allow-listed.
- Subprocess calls have an execution timeout.
- Very large note reads are capped to avoid excessive responses.

## Recommended deployment controls

1. Run MCP server with a **least-privilege OS account**.
2. Set `ZK_VAULT` to a dedicated directory containing only intended notes.
3. Keep `ANTHROPIC_API_KEY` in environment variables or a secret manager — never commit it.
4. Use egress restrictions where possible (only required API endpoints).
5. Add CI checks:
   - dependency vulnerability scan (`pip-audit`)
   - static analysis (`bandit`)
   - secret scanning (`gitleaks`)
6. Pin and regularly update dependencies in `requirements.txt`.
7. If exposing MCP remotely, place behind authentication + TLS and rate limits.

## Security reporting

If you discover a vulnerability, please open a private report with:
- affected file/function
- reproduction steps
- potential impact
- suggested fix (if available)
