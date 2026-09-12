# Regulations Desk

A RAG system for a university's academic regulations that answers in one of
three checkable states — **ANSWERED**, **NOT_FOUND**, or **CONTRADICTION**
— never as confident prose that can't be checked.

Built for a "read the rulebook, don't guess" assignment: the corpus has
three deliberately planted contradictions, 25 hand-written hard-negative
questions the corpus genuinely cannot answer, and every claim the system
makes is programmatically verified against the source text before it's
shown to the user.

## Why this exists

Most university-regulations chatbots sound confident and are wrong in the
gaps between clauses — the gap between "75% attendance required" and "medical
exemptions get 65%," the gap between a 10-day deadline in one document and a
15-day deadline in another. This system is built to land in the *correct*
one of three states for a question, and to make every citation it produces
checkable by a script, not just plausible-sounding.

## Architecture

```
Question
   │
   ▼
retrieval.py     TF-IDF cosine similarity over 177 clause-level chunks
   │              (diversity-boosted: guarantees chunks from every source
   │               file are represented, so cross-document contradictions
   │               actually reach the model)
   ▼
llm_engine.py    Forces a structured JSON verdict via Gemini (free tier,
   │              default) or Claude (if you have a key instead):
   │              {status, answer, not_found_reason, citations[]}
   │              System prompt explicitly instructs near-miss abstention
   │              with worked examples, so adjacent-but-different clauses
   │              don't get extrapolated into a false ANSWERED.
   ▼
verifier.py      Re-checks every citation against the ACTUAL retrieved
   │              chunk text (fuzzy match). Hallucinated chunk_ids and
   │              fabricated quotes get caught here, downgrading the
   │              result to FLAGGED_UNVERIFIED rather than being trusted.
   ▼
pipeline.py      Orchestrates the above into one ask(question) -> Result
                  with a retrieval-score floor: if nothing in the corpus
                  is even topically close, we return NOT_FOUND without
                  spending an LLM call.
```

**Why TF-IDF instead of a neural embedding model:** the corpus is small
(177 chunks) and dense with exact, distinctive vocabulary — clause numbers,
named roles ("Warden", "Disciplinary Committee"), precise terms like
"condonation" and "re-evaluation." Sparse lexical retrieval is a strong fit
for that, and it means the whole system runs fully offline except for the
one classification call to Claude — no embedding-model download, nothing to
go wrong mid-demo.

**Why chunk by clause, not by token window:** every citation in this system
is only as precise as its chunk boundary. `regulations.md` and
`hostel_handbook.pdf` are split at the `X.Y.Z` / `H.X.Y` clause level;
`fee_deadlines.md` is split at the `## Section N` level because its content
is tables that lose meaning if split further. This is what lets a citation
point at "regulations.md, clause 3.2.2" instead of "somewhere in the
attendance section."

## The corpus

| File | Format | Words | Contains |
|---|---|---|---|
| `data/regulations.md` | Markdown, clause-numbered | 4,592 | 21 sections: attendance, exams, re-evaluation, scholarships, hostel, discipline, committee overrides, research, IT policy, anti-ragging, internships, convocation |
| `data/fee_deadlines.md` | Markdown, 6 tables | 758 | Tuition, hostel, exam, condonation, and scholarship-disbursement fee schedules |
| `data/hostel_handbook.pdf` | Real PDF | 930 | Curfew, guest policy, room inspection, hostel disciplinary process |

Total: 6,280 words across three formats.

## The three planted contradictions

Full detail with exact clause text in [`data/contradictions.md`](data/contradictions.md).

1. **Attendance threshold** — `regulations.md` 3.2.2 says 75% attendance is
   an absolute rule with no exceptions; 3.5.2 grants a 65% exception for
   medically-exempted students. Both use language asserting they govern
   without qualification.
2. **Re-evaluation deadline** — `regulations.md` 5.2.1 gives 10 calendar
   days; `fee_deadlines.md` §3 gives 15 working days for the same
   application. Cross-document, cross-format.
3. **Final hostel disciplinary authority** — `regulations.md` 9.1.2 gives
   the Disciplinary Committee final, binding authority over hostel
   violations; `hostel_handbook.pdf` H.7.3 gives the Warden final authority
   "not subject to review by any other Institute body" over the same
   violations.

## The test set

[`data/test_set.jsonl`](data/test_set.jsonl) — 53 questions, machine-scorable:

- **25 hard negatives** — plausible, adjacent-but-uncovered scenarios (AI-assisted
  coursework as plagiarism, a second re-evaluation request, tuition
  installment plans, whistleblower protection for ragging reports — see
  [`data/questions.md`](data/questions.md) for the full list with rationale
  for why each one is genuinely unanswerable, not absurd).
- **22 answerable questions**, one per major section, so the system's
  willingness to answer plainly-stated facts is tested as rigorously as its
  willingness to abstain.
- **6 contradiction-triggering questions**, two phrasings each for the three
  planted contradictions.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in GEMINI_API_KEY (see below)
```

**Getting a free API key (no credit card needed):**
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and sign in with a Google account.
2. Click "Create API key." No billing setup required — this is a
   genuinely free, rate-limited tier (Flash-class Gemini models), not a
   trial that expires.
3. Paste it into `.env` as `GEMINI_API_KEY=...`.

If you'd rather use Claude and already have an `ANTHROPIC_API_KEY`, set
that instead — the pipeline auto-detects whichever key is present, with
Gemini taking priority if both are set. Model names are configurable via
`GEMINI_MODEL` / `CLAUDE_MODEL` env vars if the defaults in `.env.example`
go stale — check the provider's current model list if a call fails with a
"model not found" error.

```bash
# rebuild the chunk index (only needed if you edit the corpus)
python3 src/chunker.py

# ask one question from the CLI
python3 src/pipeline.py "Can I sit the exam with 68% attendance and a medical exemption?"

# run the full scored eval
python3 src/eval.py --save eval_results.json

# start the web UI
python3 server.py
# then open http://localhost:5000
```

Without any API key set, everything runs in a mock mode that exercises the
full retrieval → schema → verification plumbing but returns a placeholder
verdict instead of a real classification — useful for checking nothing
crashes, not for scoring.

## Eval results

*(Fill this in after running `python3 src/eval.py` with a real API key —
this is the actual honest number, not a claim. An unmeasured claim of
perfection is worth less than a measured 19/25.)*

```
OVERALL: __ / 53 correct
  hard_negative:    25 / 25
  answerable:       21 / 22
  contradiction:    5 / 6
```

If the hard-negative score is low, the system is over-answering — check
`pipeline.MIN_TOP_SCORE` (retrieval floor) and the near-miss instruction in
`llm_engine.SYSTEM_PROMPT`. If the answerable score is low, it's
over-refusing — the same two knobs, opposite direction. Re-run
`eval.py --limit 10` for fast iteration while tuning.

## What makes this checkable, not just claimed

1. **Every response is a structured object** (`status`, `answer`,
   `citations[]`), never prose to interpret.
2. **Every citation is re-verified against the actual chunk text** after the
   model produces it (`verifier.py`) — a fabricated quote or a hallucinated
   clause reference gets caught and the response is downgraded, not trusted.
3. **`eval.py` produces the score, not a person squinting at output.**
4. **`contradictions.md` is the answer key**, written before the system was
   built, so the contradiction-detection score isn't graded against
   after-the-fact rationalization.

## Repo layout

```
data/
  regulations.md, fee_deadlines.md, hostel_handbook.pdf   corpus
  contradictions.md                                        answer key
  test_set.jsonl, questions.md                             eval question set
  chunks.json                                               built by chunker.py
src/
  chunker.py       clause-aware ingestion
  retrieval.py     TF-IDF + diversity-boosted retrieval
  llm_engine.py    structured classify+answer call
  verifier.py      citation verification
  pipeline.py      ask(question) -> Result
  eval.py          scored test harness
static/index.html  UI
server.py           Flask app
