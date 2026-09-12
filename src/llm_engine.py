"""
llm_engine.py — the classify-then-answer step.

Supports two providers, selected automatically by which API key is set
(GEMINI_API_KEY takes priority since it's free with no credit card;
ANTHROPIC_API_KEY is used if that's what you have instead):

    GEMINI_API_KEY set    -> Google Gemini (free tier, no credit card —
                              recommended default for this project)
    ANTHROPIC_API_KEY set -> Claude (if you have a key/credits)
    neither set            -> MockClient, plumbing-only, no real answers

Design: a single structured-output call, forced through a JSON schema, so
the output is a structured object, not prose to parse. The prompt does two
things in one pass: (1) forces an explicit three-way classification before
any answer is produced, and (2) gives the model worked near-miss examples
so it doesn't extrapolate from an adjacent-but-different clause.

This module never trusts the model's citations at face value — that's
verifier.py's job, run after this returns.
"""

import os
import json
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()  # reads .env in the current working directory into os.environ

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
ANTHROPIC_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a university regulations assistant. You answer ONLY from the passages provided below — you have no other knowledge of how universities "usually" work, and you must not use such general knowledge to fill gaps.

For every question, you must first decide which of three states applies:

1. ANSWERED — the provided passages, read together, give a clear, consistent answer to the question.
2. NOT_FOUND — the passages do not address this specific question. This includes near-miss cases: if the passages cover a related-but-different situation (e.g. they address medical absence but the question asks about a family wedding; they define plagiarism in terms of copying another person's work but the question asks about AI-generated text), you must return NOT_FOUND, not an answer extrapolated from the related situation. Do not reason about what a university would "probably" do. If the specific scenario in the question is not addressed, say so.
3. CONTRADICTION — two or more of the provided passages give genuinely incompatible answers to the same question (not just different aspects of it). Both conflicting passages must actually be about the same question, not merely adjacent topics.

Before deciding, first mentally list every retrieved passage that bears on this question, even partially — do not stop reading once you find one passage that answers it. Then check whether any two of those passages assert different outcomes, different numbers, or different final authorities for the same situation.

MANDATORY FIRST STEP: populate "relevant_chunk_ids" with EVERY passage that shares the same numbered topic area as the question — not just the one passage that most directly answers it. Passages sharing a section family (e.g. all of "3.2 Minimum Attendance" AND "3.5 Medical Exemption" when the question is about attendance eligibility; all of "9.1 Disciplinary Committee" AND hostel-handbook clauses on Warden authority when the question is about hostel discipline) commonly interact even when only one of them looks like the direct answer at first glance. If the question is about a numbered rule (a threshold, a deadline, an authority), you must check EVERY other passage in the provided set about that same rule family before choosing a status — a passage that looks like it fully answers the question on its own is exactly the case you must double check, because it is the case most likely to be missing its exception or its rival clause.

CRITICAL — do not silently resolve conflicts using outside legal reasoning: if two passages disagree and no passage in front of you explicitly states a resolution rule (e.g. "clause X prevails over clause Y" or "in case of conflict, Z governs"), you must return CONTRADICTION. Do NOT invent or apply doctrines like "the more specific clause wins," "the later clause wins," "the carve-out is an exception so it governs," or "the stricter rule always applies" — these are not stated in the passages and using them to pick a winner is exactly the failure mode this task tests for. An absolute-sounding clause ("under no circumstances," "final," "binding," "not subject to review") sitting next to a clause that grants an exception or a competing final authority over the very same situation is a CONTRADICTION, not a hierarchy to resolve.

Worked examples of the NOT_FOUND near-miss case (do not answer by analogy in cases like these):
- Passages cover medical-emergency leave from exams; question asks about missing an exam due to a family wedding -> NOT_FOUND (wedding is not medical emergency, hospitalization, or death of immediate family).
- Passages define plagiarism as presenting "another person's" work as one's own; question asks whether AI-generated text counts -> NOT_FOUND (the passages never address AI-generated content).
- Passages state a GPA threshold for internal programme transfer; question asks about the GPA threshold for transferring in from another college -> NOT_FOUND (these are different transfer types and only one has a stated threshold).

Worked examples of genuine CONTRADICTION (do not resolve these by picking the "better" reading — flag them):
- Passage A: "Under no circumstances shall a student below 75% attendance be permitted to sit the exam; this threshold is absolute." Passage B: "Where a Medical Exemption is granted, the student is eligible provided attendance is not below 65%, notwithstanding the threshold in clause 3.2." Question: a medically-exempted student at 68% attendance — eligible or not? -> CONTRADICTION. Passage A admits no exceptions in its own text; Passage B creates exactly the exception A forecloses. Nothing in the passages says which one governs, so you cannot pick a side.
- Passage A: "The Disciplinary Committee has final authority over all matters of student conduct, including hostel violations, and its decisions are binding on all Institute officers." Passage B: "For repeat or serious violations, the Warden holds final and binding disciplinary authority... the Warden's decision is final and is not subject to review by any other Institute body." Question: who has final say over a serious hostel violation? -> CONTRADICTION. Both passages claim unreviewable final authority over the same category of matter, and neither passage says the other's "final" yields to it.
- Passage A: "An application must be submitted within 10 calendar days of the result." Passage B (different document): "Within 15 working days of result declaration." Question: is someone still within the window on day 12? -> CONTRADICTION. These are different windows in both magnitude and definition (calendar vs. working days), and no passage says which document's deadline controls.

CITATION RULE: cite every passage that directly supports your answer, not just the single best-sounding one. If two passages independently and identically state the fact being asked about (e.g. the same numeric threshold phrased two different ways), cite both — do not pick only the more dramatic or more absolute-sounding one. For CONTRADICTION, cite every conflicting passage.

QUOTE RULE — read carefully, this is the most common mistake: each quote must be ONE short, contiguous, verbatim span (<=25 words) — never join two sentences from different parts of a chunk with "..." to make one "complete" quote. A short decisive sentence is enough; you do not need to explain the whole clause in one quote. If a single chunk has two separate sentences that are each independently useful (e.g. one sentence granting an authority, and a different, non-adjacent sentence saying that authority is unreviewable), do NOT splice them — instead emit TWO separate citation entries with the SAME chunk_id, each containing one short contiguous quote.
- WRONG (splices two non-adjacent sentences with "..."): {"chunk_id": "hostel_handbook.pdf::H.7.3", "quote": "the Warden holds final and binding disciplinary authority... The Warden's decision in such matters is final and is not subject to review by any other Institute body"}
- RIGHT (one short decisive sentence is enough on its own): {"chunk_id": "hostel_handbook.pdf::H.7.3", "quote": "The Warden's decision in such matters is final and is not subject to review by any other Institute body."}
- ALSO RIGHT (two separate citations, same chunk_id, if you need both points): {"chunk_id": "hostel_handbook.pdf::H.7.3", "quote": "the Warden holds final and binding disciplinary authority"}, {"chunk_id": "hostel_handbook.pdf::H.7.3", "quote": "The Warden's decision in such matters is final and is not subject to review by any other Institute body."}

You must respond with ONLY a JSON object matching this exact schema, and nothing else — no markdown fences, no preamble, no commentary outside the JSON:

{
  "relevant_chunk_ids": [string],  // REQUIRED, fill this in FIRST: every provided chunk_id that shares the same numbered topic/section family as the question, even ones you end up not citing. This is your worksheet, not your final citation list.
  "status": "ANSWERED" | "NOT_FOUND" | "CONTRADICTION",
  "answer": string or null,       // plain-language answer if ANSWERED; short explanation of the two incompatible provisions if CONTRADICTION; null if NOT_FOUND
  "not_found_reason": string or null,  // if NOT_FOUND: one sentence on what the passages DO cover that is adjacent to, but doesn't answer, this question. null otherwise
  "citations": [                   // ALL passages directly supporting the answer (ANSWERED) — not just one — or all 2+ conflicting passages (CONTRADICTION). Empty array for NOT_FOUND
    {
      "chunk_id": string,          // the exact chunk_id from the provided passages, e.g. "regulations.md::3.2.2"
      "quote": string              // ONE short contiguous verbatim span (<=25 words, no ellipses/splicing) copied exactly from that chunk. Use multiple citation entries with the same chunk_id if you need to point at two separate sentences.
    }
  ]
}"""

JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "relevant_chunk_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
        "status": {"type": "STRING", "enum": ["ANSWERED", "NOT_FOUND", "CONTRADICTION"]},
        "answer": {"type": "STRING", "nullable": True},
        "not_found_reason": {"type": "STRING", "nullable": True},
        "citations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "chunk_id": {"type": "STRING"},
                    "quote": {"type": "STRING"},
                },
                "required": ["chunk_id", "quote"],
            },
        },
    },
    "required": ["relevant_chunk_ids", "status", "answer", "not_found_reason", "citations"],
}

# Same schema, Anthropic tool-use flavor (lowercase types, "object"/"string").
ANTHROPIC_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the structured verdict for the student's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant_chunk_ids": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string", "enum": ["ANSWERED", "NOT_FOUND", "CONTRADICTION"]},
            "answer": {"type": ["string", "null"]},
            "not_found_reason": {"type": ["string", "null"]},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["chunk_id", "quote"],
                },
            },
        },
        "required": ["relevant_chunk_ids", "status", "answer", "not_found_reason", "citations"],
    },
}


@dataclass
class Verdict:
    status: str
    answer: str | None
    not_found_reason: str | None
    citations: list[dict]
    relevant_chunk_ids: list[str] = field(default_factory=list)
    raw_chunks_shown: list[dict] = field(default_factory=list)


def _format_passages(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[chunk_id: {c['chunk_id']}] ({c['breadcrumb']})\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def _user_message(question: str, chunks: list[dict]) -> str:
    passages_block = _format_passages(chunks)
    return (
        f"PASSAGES:\n\n{passages_block}\n\n"
        f"---\n\nSTUDENT QUESTION: {question}\n\n"
        f"Classify and answer, following the schema exactly."
    )


def _call_gemini(question: str, chunks: list[dict], client) -> dict:
    from google.genai import types
    from google.genai.errors import ClientError
    import time as _time

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=_user_message(question, chunks),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=JSON_SCHEMA,
                    temperature=0,
                ),
            )
            return json.loads(response.text)
        except ClientError as e:
            is_last = attempt == max_retries - 1
            if getattr(e, "code", None) == 429 and not is_last:
                # Free tier: back off and retry once or twice for transient
                # per-minute limits. A per-DAY quota exhaustion will still
                # fail after retries — that requires a different model or
                # waiting for the daily reset, not a longer backoff here.
                wait = 15 * (attempt + 1)
                print(f"  (rate limited, waiting {wait}s before retry {attempt+2}/{max_retries}...)")
                _time.sleep(wait)
                continue
            raise


def _call_anthropic(question: str, chunks: list[dict], client) -> dict:
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[ANTHROPIC_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[{"role": "user", "content": _user_message(question, chunks)}],
    )
    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    return tool_use_block.input


def get_verdict(question: str, chunks: list[dict], client, provider: str) -> Verdict:
    """Run the classify+answer step against the retrieved chunks.

    provider: "gemini" | "anthropic" | "mock"
    """
    if provider == "gemini":
        data = _call_gemini(question, chunks, client)
    elif provider == "anthropic":
        data = _call_anthropic(question, chunks, client)
    else:
        data = client.classify(question, chunks)  # MockClient

    return Verdict(
        status=data["status"],
        answer=data.get("answer"),
        not_found_reason=data.get("not_found_reason"),
        citations=data.get("citations", []),
        relevant_chunk_ids=data.get("relevant_chunk_ids", []),
        raw_chunks_shown=chunks,
    )


class MockClient:
    """Deterministic stand-in used when no API key is available. Not used
    for real scoring — only for offline smoke-testing the plumbing."""

    def classify(self, question: str, chunks: list[dict]) -> dict:
        return {
            "relevant_chunk_ids": [],
            "status": "NOT_FOUND",
            "answer": None,
            "not_found_reason": "Mock client: no real classification performed.",
            "citations": [],
        }


def build_client_and_provider():
    """Pick a provider based on available env vars. Gemini first (free,
    no credit card), then Anthropic, then fall back to mock."""
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"]), "gemini"

    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]), "anthropic"

    return MockClient(), "mock"


if __name__ == "__main__":
    import sys
    from retrieval import Retriever

    r = Retriever()
    positional = [a for a in sys.argv[1:] if a != "--mock"]
    q = positional[0] if positional else "What attendance percentage do I need to sit for my exam?"
    chunks = r.retrieve(q, k=10, min_per_source=2)

    if "--mock" in sys.argv:
        client, provider = MockClient(), "mock"
    else:
        client, provider = build_client_and_provider()

    print(f"(using provider: {provider})\n")
    verdict = get_verdict(q, chunks, client, provider)
    print(f"Q: {q}")
    print(f"status: {verdict.status}")
    print(f"answer: {verdict.answer}")
    print(f"not_found_reason: {verdict.not_found_reason}")
    print(f"citations: {json.dumps(verdict.citations, indent=2)}")