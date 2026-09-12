# Test Set — Human-Readable

Machine-readable version for `eval.py`: `test_set.jsonl` (53 questions total:
25 hard negatives, 22 answerable, 6 contradiction-triggering).

This file exists so a grader can judge question quality without parsing
JSON. Each hard negative names the real clause it sits next to, and why that
clause does *not* actually cover the question.

---

## 25 Hard Negatives (expected: `NOT_FOUND`)

Grouped by which section of the corpus they're adjacent to, to show spread
rather than one repeated trick.

### Academics / Exams / Attendance
1. Extra fee for internship-caused registration delay — internships block registration (19.1.4) but no fee for the delay is ever specified.
2. Second re-evaluation of an already re-evaluated script — 5.3.3 calls the revised mark "final" but never explicitly forbids a repeat request.
3. Whether online-session attendance during a facility outage counts toward 75% — emergency powers (10.2) exist, but attendance *computation* during such periods is never defined.
4. Whether the 75% attendance rule applies to part-time/distance programmes — the entire attendance section assumes full-time, on-campus study; the mode is never varied.
5. Audit/non-credit course attendance — the concept of an audited course doesn't exist anywhere in the corpus.
6. Extra-credit overload registration for early graduation — registration rules cover deadlines and withdrawal, never a per-term credit cap or overload approval process.

### Scholarships / Financial Aid
7. Scholarship continuity during a semester abroad — no clause addresses what happens to a scholarship if the recipient studies elsewhere for a term.

### Hostel
8. Requesting a specific roommate — allotment is priority-based only; preference is never mentioned.
9. Security deposit treatment on eviction (vs. normal vacating) — H.8.2 covers voluntary vacating, not the eviction scenario H.7.3 itself creates.
10. Cap on total years a student may stay in the hostel — allotment priority (7.1.2) says who gets in first, not how long anyone can stay.

### Fees
11. Tuition paid in installments — every fee in the schedule has one due date and a late penalty; no installment structure exists.
12. Duplicate degree certificate fee — the fee table lists transcript and migration certificate fees but not a duplicate-degree fee.
13. Sibling fee discount/waiver — no family-based waiver appears anywhere in the fee schedule.

### Discipline
14. Removing an old warning from a student's record — sanctions and appeals are defined; expungement after good behavior is not.
15. Legal representation at a Disciplinary Committee hearing — the right to respond "in writing or in person" (9.2.2) says nothing about counsel.
16. Guardian filing an appeal on the student's behalf — 9.4.1 says "a student may appeal," full stop.

### Academic Integrity
17. Whether AI-assisted writing counts as plagiarism — plagiarism is defined via "another person's" work (14.1.2); AI-generated text is a genuinely novel case the definition doesn't anticipate.

### Postgraduate
18. Max duration for a coursework-only (non-research) Master's — 15.4.1 caps research Master's at 3 years and is silent on coursework-only Master's entirely.

### Grievances
19. Filing a grievance anonymously — 13.1.2 requires written submission; anonymity is addressed only for ragging (17.2.1), a different committee and a different clause.

### IT / Library
20. Remote/VPN access to digital library resources — network credentials and monitoring are covered (16.2); remote access provisioning is not.

### Student Societies
21. Off-campus event funding from the Student Activities Fund — event registration (18.2.1) only covers campus events.

### Transfer
22. Minimum GPA for inter-institutional transfer — 12.1 sets a 50% credit-recognition cap but, unlike internal transfer (12.2.1's explicit 6.5 GPA), states no GPA threshold at all.

### Fees / Discipline crossover
23. Tuition refund after expulsion — the refund schedule (fee_deadlines §6) is keyed to voluntary withdrawal timing and never mentions expulsion.

### Anti-Ragging
24. Whistleblower protection for a student reporting ragging — reporting channels exist (17.2); protection against retaliation is not addressed.

---

## 22 Answerable Questions (expected: `ANSWERED`)

One per major section, so the system's willingness to answer plainly-stated
facts is tested as rigorously as its willingness to abstain. Covers:
attendance threshold, grading, library borrowing, Merit Scholarship CGPA
cutoff, scholarship-combination rule, internship length, hostel curfew,
hostel guest policy, hostel deposit amount, tuition late fee, Disciplinary
Committee composition, disciplinary appeal route, PhD duration cap, Academic
Council waiver power, hostel withdrawal refund rule, internal transfer GPA
threshold, ragging prohibition, minimum society size, Leave-of-Absence fee
liability, condonation fee amount, convocation attendance optionality, and
Supplementary Examination eligibility grounds.

---

## 6 Contradiction-Triggering Questions (expected: `CONTRADICTION`)

Two phrasings each for the three planted contradictions (see
`contradictions.md` for full detail):

- **Attendance threshold vs. medical exemption** (regulations.md 3.2.2 vs. 3.5.2)
- **Re-evaluation deadline** (regulations.md 5.2.1: 10 calendar days vs. fee_deadlines.md §3: 15 working days)
- **Final authority over hostel discipline** (regulations.md 9.1.2 vs. hostel_handbook.pdf H.7.3)

Two phrasings per contradiction are included deliberately — one direct
factual question, one framed as a real student's specific situation — so the
system isn't just pattern-matching a single sentence shape to detect the
conflict.
