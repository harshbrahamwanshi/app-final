"""
retrieval.py — TF-IDF cosine-similarity retrieval over regulation chunks.

Why TF-IDF instead of a neural embedding model: this corpus is small
(177 chunks) and dense with exact vocabulary that matters precisely —
numbers, clause references, named roles ("Warden", "Disciplinary
Committee"), specific nouns ("re-evaluation", "condonation"). Sparse
lexical retrieval is a strong, fast, fully-offline fit for that, and
avoids a large model download / dependency footprint for a live demo.

No vector DB: at this scale a plain numpy cosine-similarity matrix is
simpler, faster to build, and has nothing to configure or break.
"""

import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_DIR = Path(__file__).parent.parent / "data"


class Retriever:
    def __init__(self, chunks_path: Path = DATA_DIR / "chunks.json"):
        self.chunks: list[dict] = json.loads(chunks_path.read_text(encoding="utf-8"))

        # Index on breadcrumb + text so section/heading vocabulary
        # (e.g. "Attendance", "Re-evaluation") helps matching even when
        # the question doesn't repeat the exact clause wording.
        corpus_texts = [f"{c['breadcrumb']} {c['text']}" for c in self.chunks]

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
            min_df=1,
        )
        self.matrix = self.vectorizer.fit_transform(corpus_texts)

    def retrieve(self, query: str, k: int = 10, min_per_source: int = 2) -> list[dict]:
        """Return top chunks by similarity, with a diversity guarantee.

        Plain top-k by global score under-represents small source files
        (fee_deadlines.md has 6 chunks, hostel_handbook.pdf has 29, vs.
        regulations.md's 142) even when one of their chunks is the exact
        other half of a cross-document contradiction. Two of this corpus's
        three planted contradictions span two files — if the second file's
        clause never reaches the model, CONTRADICTION detection silently
        degrades to a plain ANSWERED. So after taking the global top-k, we
        top up with each source file's best-scoring chunk(s) if that file
        isn't yet represented at least `min_per_source` times.
        """
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.matrix).flatten()
        ranked_idx = np.argsort(scores)[::-1]

        selected_idx: list[int] = list(ranked_idx[:k])
        selected_set = set(selected_idx)

        sources = sorted({c["source_file"] for c in self.chunks})
        for src in sources:
            src_idx_ranked = [i for i in ranked_idx if self.chunks[i]["source_file"] == src]
            present_count = sum(1 for i in selected_idx if self.chunks[i]["source_file"] == src)
            j = 0
            while present_count < min_per_source and j < len(src_idx_ranked):
                cand = src_idx_ranked[j]
                if cand not in selected_set:
                    selected_idx.append(cand)
                    selected_set.add(cand)
                    present_count += 1
                j += 1

        # Re-sort the final (possibly topped-up) set by score, descending.
        selected_idx.sort(key=lambda i: -scores[i])

        results = []
        for i in selected_idx:
            chunk = dict(self.chunks[i])
            chunk["score"] = float(scores[i])
            results.append(chunk)
        return results


if __name__ == "__main__":
    r = Retriever()
    print(f"Indexed {len(r.chunks)} chunks.\n")

    test_queries = [
        "What attendance percentage do I need to sit for my exam?",
        "I have a medical exemption and 68% attendance, can I sit the exam?",
        "How many days do I have to apply for re-evaluation?",
        "Can I bring a lawyer to my disciplinary hearing?",
        "Is there a fee discount for siblings enrolled at the Institute?",
    ]

    for q in test_queries:
        print(f"Q: {q}")
        results = r.retrieve(q, k=5)
        for res in results:
            print(f"   [{res['score']:.3f}] {res['chunk_id']}  — {res['text'][:80]}...")
        print()
