"""
pipeline.py — the single entrypoint: ask(question) -> Result.

Ties together:
  retrieval.Retriever  -> top chunks for the question
  llm_engine.get_verdict -> model's classification + draft answer + citations
  verifier.apply_verification -> programmatic check of every citation

The Result this returns is what both eval.py and the web UI consume. Its
`status` field is always one of ANSWERED / NOT_FOUND / CONTRADICTION /
FLAGGED_UNVERIFIED — never free text to interpret.

Retrieval threshold: if the top retrieved chunk's score is below
MIN_TOP_SCORE, we skip the LLM call entirely and return NOT_FOUND directly.
This is the primary abstention knob referenced in the project plan — tune
it against eval.py's results.
"""

import os
from dataclasses import dataclass, field

from retrieval import Retriever
from llm_engine import get_verdict, build_client_and_provider
from verifier import apply_verification, CitationCheck

MIN_TOP_SCORE = 0.03  # below this, retrieval is too weak to bother asking the model
DEFAULT_K = 10
DEFAULT_MIN_PER_SOURCE = 2


@dataclass
class Result:
    question: str
    status: str                     # ANSWERED | NOT_FOUND | CONTRADICTION | FLAGGED_UNVERIFIED
    answer: str | None
    not_found_reason: str | None
    citations: list[dict]
    citation_checks: list[CitationCheck] = field(default_factory=list)
    top_retrieval_score: float = 0.0
    retrieved_chunk_ids: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "question": self.question,
            "status": self.status,
            "answer": self.answer,
            "not_found_reason": self.not_found_reason,
            "citations": [
                {
                    "chunk_id": c.chunk_id,
                    "quote": c.quote,
                    "verified": c.verified,
                }
                for c in self.citation_checks
            ] if self.citation_checks else self.citations,
            "top_retrieval_score": self.top_retrieval_score,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
        }


class Pipeline:
    def __init__(self, use_mock: bool = False):
        self.retriever = Retriever()
        if use_mock:
            from llm_engine import MockClient
            self.client, self.provider = MockClient(), "mock"
        else:
            self.client, self.provider = build_client_and_provider()
        self.use_mock = self.provider == "mock"

    def ask(self, question: str, k: int = DEFAULT_K, min_per_source: int = DEFAULT_MIN_PER_SOURCE) -> Result:
        chunks = self.retriever.retrieve(question, k=k, min_per_source=min_per_source)
        top_score = chunks[0]["score"] if chunks else 0.0
        retrieved_ids = [c["chunk_id"] for c in chunks]

        if top_score < MIN_TOP_SCORE:
            return Result(
                question=question,
                status="NOT_FOUND",
                answer=None,
                not_found_reason="No passage in the corpus is closely related to this question.",
                citations=[],
                top_retrieval_score=top_score,
                retrieved_chunk_ids=retrieved_ids,
            )

        verdict = get_verdict(question, chunks, self.client, self.provider)

        final_status, checks = apply_verification(
            verdict.status, verdict.answer, verdict.citations, chunks
        )

        answer = verdict.answer
        not_found_reason = verdict.not_found_reason
        if final_status == "FLAGGED_UNVERIFIED":
            # The model claimed ANSWERED/CONTRADICTION but its citations
            # didn't check out — do not serve the unverified claim as fact.
            answer = None
            not_found_reason = (
                "The system produced an answer but could not verify its "
                "citations against the source text, so it is withheld. "
                f"(Model's original claimed status: {verdict.status})"
            )

        return Result(
            question=question,
            status=final_status,
            answer=answer,
            not_found_reason=not_found_reason,
            citations=verdict.citations,
            citation_checks=checks,
            top_retrieval_score=top_score,
            retrieved_chunk_ids=retrieved_ids,
        )


if __name__ == "__main__":
    import sys
    import json

    p = Pipeline()
    if p.use_mock:
        print("(No GEMINI_API_KEY or ANTHROPIC_API_KEY set — running in mock mode, for plumbing checks only.)\n")

    q = sys.argv[1] if len(sys.argv) > 1 else "What attendance percentage do I need to sit for my exam?"
    result = p.ask(q)
    print(json.dumps(result.to_dict(), indent=2))
