# Layout Profiles Reference

Layout profiles tell the extraction engine how to interpret a PDF's visual structure.
Each profile defines column geometry, heading thresholds, junk-line filters, and
optional format-specific parsing rules.

## Profile Schema

```python
@dataclass
class LayoutProfile:
    id: str                     # e.g. "philosophers_notes"
    name: str                   # Human-readable name
    col_split: float            # Fraction of page width where main column starts (0.0 = full-width)
    extract_sidebar: bool       # Whether to extract sidebar as separate pull-quote channel
    h1_size_ratio: float        # Font size >= median * this → H1
    h2_size_ratio: float        # Font size >= median * this → H2
    h2_bold_ratio: float        # Bold AND size >= median * this → H2
    junk_patterns: list[str]    # Regex patterns for header/footer/noise lines to strip
    detection_signatures: list[str]  # Strings to search on page 1 for auto-detection
    page_skip: list[int]        # Page indices to skip entirely (e.g. cover pages)
    special_blocks: dict        # Format-specific block types to detect
```

## Built-in Profiles

### philosophers_notes

Brian Johnson's Philosopher's Notes / Heroic platform. 6-page PDFs with:
- Left sidebar (~35% width): pull quotes with attribution, occasional labels
- Right main column (~65% width): body text with bold section headings
- Repeated header: "Philosopher's Notes | {Book Title} {page_num}"
- Repeated footer: "philosophersnotes.com"

```python
LayoutProfile(
    id="philosophers_notes",
    name="Philosopher's Notes (Brian Johnson / Heroic)",
    col_split=0.28,
    extract_sidebar=True,
    h1_size_ratio=1.35,
    h2_size_ratio=1.10,
    h2_bold_ratio=0.95,
    junk_patterns=[
        r"Philosopher'?s\s+Notes\s*\|",
        r"^\d+\s+Philosopher'?s\s+Notes",
        r"^philosophersnotes\.com",
        r"^heroic\.us",
        r"^optimize\.me",
    ],
    detection_signatures=[
        "Philosopher's Notes",
        "PhilosophersNotes",
        "philosophersnotes.com",
        "heroic.us",
        "Brian Johnson",
    ],
    page_skip=[],
    special_blocks={
        "big_ideas": {
            "trigger": "The Big Ideas",
            "type": "bullet_list",
            "description": "List of key takeaways, usually on page 1"
        }
    }
)
```

### shortform

Shortform.com book guides. Multi-page PDFs with:
- Full-width layout (single column)
- Chapter-based structure with clear H1/H2 headings
- "Key Points" and "Exercise" blocks
- "Shortform Note" callout blocks (editorial commentary)

```python
LayoutProfile(
    id="shortform",
    name="Shortform Book Guides",
    col_split=0.0,
    extract_sidebar=False,
    h1_size_ratio=1.40,
    h2_size_ratio=1.15,
    h2_bold_ratio=1.0,
    junk_patterns=[
        r"^Shortform\s",
        r"^www\.shortform\.com",
        r"^Page\s+\d+\s+of\s+\d+",
    ],
    detection_signatures=[
        "Shortform",
        "shortform.com",
        "Shortform Note",
    ],
    page_skip=[0],  # Usually a cover/TOC page
    special_blocks={
        "exercise": {
            "trigger": "Exercise:",
            "type": "callout",
            "description": "Interactive exercise block"
        },
        "shortform_note": {
            "trigger": "Shortform Note",
            "type": "callout",
            "description": "Editorial commentary by Shortform team"
        },
        "key_point": {
            "trigger": "Key Point",
            "type": "highlight",
            "description": "Emphasized key takeaway"
        }
    }
)
```

### readingraphics

ReadingGraphics.com summaries. Mixed-format PDFs with:
- Full-width text summary pages
- Infographic pages (mostly images, minimal extractable text)
- Actionable tips sections

```python
LayoutProfile(
    id="readingraphics",
    name="ReadingGraphics Book Summaries",
    col_split=0.0,
    extract_sidebar=False,
    h1_size_ratio=1.50,
    h2_size_ratio=1.20,
    h2_bold_ratio=1.0,
    junk_patterns=[
        r"^readingraphics\.com",
        r"^ReadinGraphics",
        r"^©\s*ReadinGraphics",
    ],
    detection_signatures=[
        "ReadinGraphics",
        "readingraphics.com",
        "readingraphics",
    ],
    page_skip=[],
    special_blocks={
        "infographic_page": {
            "trigger": None,  # Detected by low text-to-image ratio
            "type": "skip",
            "description": "Pages that are mostly infographic — skip text extraction"
        }
    }
)
```

### getabstract

getAbstract.com business book summaries. Structured format with:
- Full-width layout
- Rating box on page 1 (Applicability, Innovation, Style ratings)
- "What You'll Learn" / "Recommendation" / "Summary" / "About the Author" sections
- Take-Aways bullet list

```python
LayoutProfile(
    id="getabstract",
    name="getAbstract Book Summaries",
    col_split=0.0,
    extract_sidebar=False,
    h1_size_ratio=1.40,
    h2_size_ratio=1.15,
    h2_bold_ratio=1.0,
    junk_patterns=[
        r"^getAbstract",
        r"^©\s*\d{4}\s+getAbstract",
        r"^www\.getabstract\.com",
    ],
    detection_signatures=[
        "getAbstract",
        "getabstract.com",
        "What You'll Learn",
        "Take-Aways",
    ],
    page_skip=[],
    special_blocks={
        "rating_box": {
            "trigger": "Applicability",
            "type": "metadata",
            "description": "Rating scores for the book"
        },
        "take_aways": {
            "trigger": "Take-Aways",
            "type": "bullet_list",
            "description": "Key takeaways list"
        }
    }
)
```

### generic

Fallback for any full-width PDF. No special block detection, relies purely on
font-size-based heading classification.

```python
LayoutProfile(
    id="generic",
    name="Generic Full-Width PDF",
    col_split=0.0,
    extract_sidebar=False,
    h1_size_ratio=1.35,
    h2_size_ratio=1.10,
    h2_bold_ratio=0.95,
    junk_patterns=[],
    detection_signatures=[],
    page_skip=[],
    special_blocks={}
)
```

## Creating a New Profile

When encountering a new PDF format:

### Step 1: Inspect the PDF structure

Run with `--profile generic --debug` to produce the extraction JSON:

```bash
python pdf_to_obsidian.py sample.pdf --vault ./test --profile generic --debug
```

The debug JSON (`sample_debug.json`) contains:
- Every text block with coordinates, font size, bold flag
- Page dimensions
- Computed median font sizes per page

### Step 2: Identify layout characteristics

Look for:
- **Column layout**: Do blocks cluster into distinct X-coordinate ranges?
  If yes, determine the `col_split` fraction.
- **Heading sizes**: What font sizes are used for H1 vs H2 vs body?
  Calculate ratios relative to the median.
- **Repeated junk**: Headers, footers, page numbers, watermarks.
  Write regex patterns to filter them.
- **Detection signatures**: Unique strings on page 1 that identify this format.
- **Special blocks**: Callout boxes, exercise sections, rating widgets, etc.

### Step 3: Define the profile

Add a new `LayoutProfile` entry following the schema above. Place it in
the `PROFILES` dict in `pdf_to_obsidian.py`.

### Step 4: Test on 3-5 samples

Run the full pipeline on a small batch and verify:
- Headings detected correctly (check the source note structure)
- Pull quotes captured with correct attribution (if applicable)
- Junk lines filtered out
- Entity extraction reasonable

### Step 5: Batch process

Once validated, run on the full collection. Use `--resume` to pick up where
you left off if interrupted.

## Profile Selection Priority

1. Explicit `--profile` flag (highest priority)
2. Auto-detection from page 1 signatures
3. Column geometry analysis (col_split > 0 detected → likely sidebar format)
4. Falls back to `generic`
