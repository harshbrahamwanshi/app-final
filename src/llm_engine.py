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

Worked examples of the NOT_FOUND near-miss case (do not answer by analogy in cases like these):
- Passages cover medical-emergency leave from exams; question asks about missing an exam due to a family wedding -> NOT_FOUND (wedding is not medical emergency, hospitalization, or death of immediate family).
- Passages define plagiarism as presenting "another person's" work as one's own; question asks whether AI-generated text counts -> NOT_FOUND (the passages never address AI-generated content).
- Passages state a GPA threshold for internal programme transfer; question asks about the GPA threshold for transferring in from another college -> NOT_FOUND (these are different transfer types and only one has a stated threshold).

You must respond with ONLY a JSON object matching this exact schema, and nothing else — no markdown fences, no preamble, no commentary outside the JSON:

{
  "status": "ANSWERED" | "NOT_FOUND" | "CONTRADICTION",
  "answer": string or null,       // plain-language answer if ANSWERED; short explanation of the two incompatible provisions if CONTRADICTION; null if NOT_FOUND
  "not_found_reason": string or null,  // if NOT_FOUND: one sentence on what the passages DO cover that is adjacent to, but doesn't answer, this question. null otherwise
  "citations": [                   // passages supporting the answer (ANSWERED), or the 2+ conflicting passages (CONTRADICTION). Empty array for NOT_FOUND
    {
      "chunk_id": string,          // the exact chunk_id from the provided passages, e.g. "regulations.md::3.2.2"
      "quote": string              // a verbatim quote (<=25 words) from that exact chunk supporting this citation
    }
  ]
}"""

JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
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
    "required": ["status", "answer", "not_found_reason", "citations"],
}

# Same schema, Anthropic tool-use flavor (lowercase types, "object"/"string").
ANTHROPIC_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the structured verdict for the student's question.",
    "input_schema": {
        "type": "object",
        "properties": {
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
        "required": ["status", "answer", "not_found_reason", "citations"],
    },
}


@dataclass
class Verdict:
    status: str
    answer: str | None
    not_found_reason: str | None
    citations: list[dict]
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
        raw_chunks_shown=chunks,
    )


class MockClient:
    """Deterministic stand-in used when no API key is available. Not used
    for real scoring — only for offline smoke-testing the plumbing."""

    def classify(self, question: str, chunks: list[dict]) -> dict:
        return {
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
