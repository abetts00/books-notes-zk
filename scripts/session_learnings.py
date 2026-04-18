#!/usr/bin/env python3
"""Stop-hook: read session transcript, ask Claude to propose diffs against
SKILL.md / CLAUDE.md / references/*.md, write proposal to learnings/pending/.

Invoked by Claude Code's Stop hook. Receives JSON on stdin with at least
`session_id` and `transcript_path`. Exits 0 silently whether or not a proposal
was written; any errors go to stderr without blocking the session.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = REPO_ROOT / "learnings" / "pending"
DOCS = [
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "references" / "analysis_prompt.md",
    REPO_ROOT / "references" / "layout_profiles.md",
    REPO_ROOT / "references" / "vault_schema.md",
]
MODEL = os.environ.get("LEARNINGS_MODEL", "claude-sonnet-4-6")
MAX_TRANSCRIPT_CHARS = 120_000
MIN_TRANSCRIPT_CHARS = 400


def log(msg: str) -> None:
    sys.stderr.write(f"[session_learnings] {msg}\n")


def read_transcript(path: Path) -> str:
    if not path.exists():
        return ""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        role = evt.get("type") or evt.get("role")
        msg = evt.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if role == "user" and isinstance(content, str):
            lines.append(f"USER: {content}")
        elif role == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    lines.append(f"USER: {block.get('text', '')}")
        elif role == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    lines.append(f"ASSISTANT: {block.get('text', '')}")
        elif role == "summary" and isinstance(msg, str):
            lines.append(f"SUMMARY: {msg}")
    joined = "\n\n".join(lines)
    if len(joined) > MAX_TRANSCRIPT_CHARS:
        joined = joined[-MAX_TRANSCRIPT_CHARS:]
    return joined


def load_docs() -> str:
    chunks: list[str] = []
    for p in DOCS:
        if p.exists():
            rel = p.relative_to(REPO_ROOT)
            chunks.append(f"=== {rel} ===\n{p.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


PROMPT = """You are reviewing a Claude Code session that just ended, for a
repository that maintains a book-notes Zettelkasten pipeline plus its own
skill file and schema doc. Your job is to propose concrete, minimal updates
to the repository's documentation so future sessions benefit from whatever
was learned in this one.

Focus on durable, reusable lessons:
- new failure modes and their fixes
- clarifications that would have prevented a wrong turn
- missing schema rules, naming conventions, or pipeline caveats
- prompt tweaks worth adopting in references/analysis_prompt.md

Ignore one-off debugging noise, chit-chat, and anything already covered in
the current docs.

Output format: a single markdown document with this structure:

# Session Learnings — <one-line summary>

## What happened
2-4 bullets describing what the session actually accomplished or uncovered.

## Proposed doc changes
For each file that should change, a block like:

### <relative/path.md>
**Rationale:** one sentence on why.

```diff
- old line
+ new line
```

Use unified-diff-style fenced blocks with enough surrounding context that a
human can locate the edit. If a file needs a new section, show it as a pure
addition with `+` lines.

If nothing durable was learned, output exactly:

# Session Learnings — no durable changes

and stop.

---

CURRENT DOCS:

{docs}

---

SESSION TRANSCRIPT (trimmed to last {n} chars):

{transcript}
"""


def call_claude(transcript: str, docs: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        log("anthropic SDK not installed; skipping")
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY not set; skipping")
        return None
    client = anthropic.Anthropic(api_key=api_key)
    prompt = PROMPT.format(docs=docs, transcript=transcript, n=len(transcript))
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        log(f"API call failed: {e}")
        return None
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip() or None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        log("no JSON on stdin; exiting")
        return 0
    session_id = payload.get("session_id", "unknown")
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        log("no transcript_path in payload; exiting")
        return 0
    transcript = read_transcript(Path(transcript_path))
    if len(transcript) < MIN_TRANSCRIPT_CHARS:
        log(f"transcript too short ({len(transcript)} chars); skipping")
        return 0
    proposal = call_claude(transcript, load_docs())
    if not proposal:
        return 0
    if proposal.strip().endswith("no durable changes"):
        log("no durable changes proposed")
        return 0
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = PENDING_DIR / f"{stamp}-{session_id[:8]}.md"
    out.write_text(proposal + "\n", encoding="utf-8")
    log(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    try:
        rc = main()
    except Exception as e:
        log(f"unhandled error: {e}")
        rc = 0
    log(f"done in {time.time() - t0:.1f}s")
    sys.exit(rc)
