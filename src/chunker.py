"""
chunker.py — clause-aware ingestion for the regulations RAG system.

Design principle: chunk boundaries must match citation granularity.
- regulations.md and hostel_handbook.pdf are chunked per numbered clause
  (e.g. "3.2.2", "H.7.3") because that's the precision the corpus supports
  and the precision contradictions.md / test_set.jsonl cite at.
- fee_deadlines.md is chunked per top-level "## Section N" because its
  content is tables, which lose their header/column context if split
  further, and because that's the granularity test_set.jsonl cites at
  for this file (e.g. "fee_deadlines.md:Section 3").

Each chunk is a dict:
    {
        "chunk_id": "regulations.md::3.2.2",
        "source_file": "regulations.md",
        "section_id": "3.2.2",
        "breadcrumb": "9. Discipline > 9.1 Disciplinary Committee",
        "text": "<verbatim clause text>",
    }

Output: data/chunks.json — the single artifact every later stage reads.
"""

import json
import re
import unicodedata
from pathlib import Path

import fitz  # pymupdf

DATA_DIR = Path(__file__).parent.parent / "data"

CLAUSE_RE = re.compile(r"^(\d+\.\d+\.\d+)\s+(.*)$")        # e.g. "3.2.2 Under no circumstances..."
SUBSECTION_RE = re.compile(r"^### (\d+\.\d+) (.*)$")        # e.g. "### 3.2 Minimum Attendance..."
SECTION_RE = re.compile(r"^## (\d+)\. (.*)$")                # e.g. "## 3. Attendance Requirements"

HOSTEL_CLAUSE_RE = re.compile(r"^(H\.\d+\.\d+)\s+(.*)$")    # e.g. "H.7.3 For repeat violations..."
HOSTEL_SECTION_RE = re.compile(r"^(H\.\d+)\s+(.*)$")         # e.g. "H.7 Disciplinary Process..."

FEE_SECTION_RE = re.compile(r"^## (\d+)\. (.*)$")            # e.g. "## 3. Examination-Related Fees"


def normalize(text: str) -> str:
    """Fix ligatures (ﬀ, ﬁ, etc.) introduced by PDF text extraction, and
    collapse whitespace, without altering wording — this keeps verbatim
    quotes matchable later by the citation verifier."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ﬀ", "ff").replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_regulations(path: Path) -> list[dict]:
    """Chunk regulations.md at the X.Y.Z clause level, carrying a
    breadcrumb of the enclosing ## and ### headings for retrieval context."""
    lines = path.read_text(encoding="utf-8").splitlines()

    chunks = []
    current_section_title = None   # "3. Attendance Requirements"
    current_subsection_title = None  # "3.2 Minimum Attendance to Sit for Examinations"
    current_clause_id = None
    current_clause_lines: list[str] = []

    def flush():
        if current_clause_id and current_clause_lines:
            breadcrumb_parts = [p for p in (current_section_title, current_subsection_title) if p]
            chunks.append({
                "chunk_id": f"regulations.md::{current_clause_id}",
                "source_file": "regulations.md",
                "section_id": current_clause_id,
                "breadcrumb": " > ".join(breadcrumb_parts),
                "text": normalize(" ".join(current_clause_lines)),
            })

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        sec_match = SECTION_RE.match(line)
        if sec_match:
            flush()
            current_clause_id, current_clause_lines = None, []
            current_section_title = f"{sec_match.group(1)}. {sec_match.group(2)}"
            current_subsection_title = None
            continue

        subsec_match = SUBSECTION_RE.match(line)
        if subsec_match:
            flush()
            current_clause_id, current_clause_lines = None, []
            current_subsection_title = f"{subsec_match.group(1)} {subsec_match.group(2)}"
            continue

        clause_match = CLAUSE_RE.match(line)
        if clause_match:
            flush()
            current_clause_id = clause_match.group(1)
            current_clause_lines = [line]
            continue

        # Continuation of the current clause (wrapped line, or a clause
        # occasionally followed by a plain continuation sentence).
        if current_clause_id:
            current_clause_lines.append(line)

    flush()
    return chunks


def chunk_fee_deadlines(path: Path) -> list[dict]:
    """Chunk fee_deadlines.md at the '## N. Title' level — one chunk per
    section, tables included whole, so headers/rows stay aligned."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    chunks = []
    current_id = None
    current_title = None
    current_lines: list[str] = []

    def flush():
        if current_id and current_lines:
            chunks.append({
                "chunk_id": f"fee_deadlines.md::Section {current_id}",
                "source_file": "fee_deadlines.md",
                "section_id": f"Section {current_id}",
                "breadcrumb": f"Section {current_id}. {current_title}",
                "text": normalize("\n".join(current_lines)),
            })

    for raw_line in lines:
        line = raw_line.rstrip()
        sec_match = FEE_SECTION_RE.match(line.strip())
        if sec_match:
            flush()
            current_id = sec_match.group(1)
            current_title = sec_match.group(2)
            current_lines = [line]
            continue
        if current_id:
            current_lines.append(line)

    flush()
    return chunks


def chunk_hostel_handbook(path: Path) -> list[dict]:
    """Extract hostel_handbook.pdf text and chunk at the H.X.Y clause level,
    mirroring the regulations.md approach."""
    doc = fitz.open(str(path))
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()

    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    chunks = []
    current_section_title = None
    current_clause_id = None
    current_clause_lines: list[str] = []

    def flush():
        if current_clause_id and current_clause_lines:
            chunks.append({
                "chunk_id": f"hostel_handbook.pdf::{current_clause_id}",
                "source_file": "hostel_handbook.pdf",
                "section_id": current_clause_id,
                "breadcrumb": current_section_title or "",
                "text": normalize(" ".join(current_clause_lines)),
            })

    # Skip the title/subtitle lines at the very top (before "H.1 Room Allotment").
    started = False
    for line in lines:
        if not started:
            if HOSTEL_SECTION_RE.match(line):
                started = True
            else:
                continue

        sec_match = HOSTEL_SECTION_RE.match(line)
        # A bare "H.N Title" line (section header) is distinguished from a
        # "H.N.M text..." clause line by the regex requiring exactly one dot.
        if sec_match and not HOSTEL_CLAUSE_RE.match(line):
            flush()
            current_clause_id, current_clause_lines = None, []
            current_section_title = line
            continue

        clause_match = HOSTEL_CLAUSE_RE.match(line)
        if clause_match:
            flush()
            current_clause_id = clause_match.group(1)
            current_clause_lines = [line]
            continue

        if current_clause_id:
            current_clause_lines.append(line)

    flush()
    return chunks


def build_all_chunks() -> list[dict]:
    chunks = []
    chunks += chunk_regulations(DATA_DIR / "regulations.md")
    chunks += chunk_fee_deadlines(DATA_DIR / "fee_deadlines.md")
    chunks += chunk_hostel_handbook(DATA_DIR / "hostel_handbook.pdf")
    return chunks


if __name__ == "__main__":
    chunks = build_all_chunks()
    out_path = DATA_DIR / "chunks.json"
    out_path.write_text(json.dumps(chunks, indent=2), encoding="utf-8")

    print(f"Built {len(chunks)} chunks -> {out_path}")
    by_source = {}
    for c in chunks:
        by_source.setdefault(c["source_file"], 0)
        by_source[c["source_file"]] += 1
    for src, n in by_source.items():
        print(f"  {src}: {n} chunks")

    print("\nSample chunks:")
    for c in chunks[:2] + [c for c in chunks if c["section_id"] == "3.2.2"] + [c for c in chunks if c["section_id"] == "H.7.3"]:
        print(f"  [{c['chunk_id']}] ({c['breadcrumb']})")
        print(f"    {c['text'][:140]}...")
