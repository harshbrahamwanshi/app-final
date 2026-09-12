"""
verifier.py — programmatic citation verification.

The whole point of this project is that citations are checkable, not just
claimed. This module does the checking: for every citation the LLM emits,
confirm (a) the chunk_id it cites was actually shown to the model, and
(b) the quote it attributes to that chunk actually appears in that chunk's
real text (fuzzy match, to tolerate minor whitespace/punctuation drift,
not to tolerate fabrication).

If any citation fails, the result is downgraded — we do not silently
trust an unverified claim just because the model sounded confident.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

FUZZY_MATCH_THRESHOLD = 85  # rapidfuzz partial_ratio, 0-100


@dataclass
class CitationCheck:
    chunk_id: str
    quote: str
    chunk_was_shown: bool
    quote_found_in_chunk: bool
    match_score: float

    @property
    def verified(self) -> bool:
        return self.chunk_was_shown and self.quote_found_in_chunk


def verify_citations(citations: list[dict], shown_chunks: list[dict]) -> list[CitationCheck]:
    """Check each citation against the chunks that were actually shown to
    the model. shown_chunks is the exact list retrieved for this question —
    the same list the model saw — so a citation to a chunk_id outside that
    list is automatically a hallucinated reference, not just an unlucky
    fuzzy-match miss."""
    shown_by_id = {c["chunk_id"]: c for c in shown_chunks}

    checks = []
    for cit in citations:
        chunk_id = cit.get("chunk_id", "")
        quote = cit.get("quote", "")

        shown = chunk_id in shown_by_id
        found = False
        score = 0.0

        if shown:
            actual_text = shown_by_id[chunk_id]["text"]
            score = fuzz.partial_ratio(quote.lower(), actual_text.lower())
            found = score >= FUZZY_MATCH_THRESHOLD

        checks.append(CitationCheck(
            chunk_id=chunk_id,
            quote=quote,
            chunk_was_shown=shown,
            quote_found_in_chunk=found,
            match_score=score,
        ))
    return checks


def apply_verification(verdict_status: str, verdict_answer, citations: list[dict], shown_chunks: list[dict]):
    """Run verification and return a possibly-downgraded final status.

    Policy:
    - NOT_FOUND requires no citations; nothing to verify, passes through.
    - ANSWERED / CONTRADICTION require every citation to verify. If any
      citation fails, we do not serve the claim as trustworthy — we
      downgrade to a FLAGGED state rather than letting an unverifiable
      claim through as if it were checked.
    - CONTRADICTION additionally requires at least 2 *distinct* chunk_ids
      among the verified citations (a "contradiction" citing only one
      passage is not actually a contradiction).
    """
    checks = verify_citations(citations, shown_chunks)

    if verdict_status == "NOT_FOUND":
        return "NOT_FOUND", checks

    if not checks:
        # ANSWERED or CONTRADICTION with zero citations is itself a failure —
        # an unsupported claim is exactly what this system must not produce.
        return "FLAGGED_UNVERIFIED", checks

    all_verified = all(c.verified for c in checks)
    if not all_verified:
        return "FLAGGED_UNVERIFIED", checks

    if verdict_status == "CONTRADICTION":
        distinct_verified_ids = {c.chunk_id for c in checks if c.verified}
        if len(distinct_verified_ids) < 2:
            return "FLAGGED_UNVERIFIED", checks

    return verdict_status, checks


if __name__ == "__main__":
    # Quick self-test against a known-good and a known-bad citation.
    shown = [{
        "chunk_id": "regulations.md::3.2.2",
        "text": "3.2.2 Under no circumstances shall a student with attendance below seventy-five percent (75%) in a course be permitted to appear for the end-term examination of that course.",
    }]

    good = [{"chunk_id": "regulations.md::3.2.2", "quote": "Under no circumstances shall a student with attendance below seventy-five percent"}]
    bad_chunk = [{"chunk_id": "regulations.md::9.9.9", "quote": "made up clause that was never shown"}]
    bad_quote = [{"chunk_id": "regulations.md::3.2.2", "quote": "students must wear formal attire during examinations"}]

    for label, cits in [("good", good), ("bad_chunk_id", bad_chunk), ("bad_quote", bad_quote)]:
        status, checks = apply_verification("ANSWERED", "some answer", cits, shown)
        print(f"{label}: final_status={status}  checks={checks}")
