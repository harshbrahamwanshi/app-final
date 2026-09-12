# Planted Contradictions — Answer Key

This file documents the three contradictions deliberately planted in the corpus
(`regulations.md`, `fee_deadlines.md`, `hostel_handbook.pdf`). These are the
ground truth used to test whether the system correctly reaches the
`CONTRADICTION` state. This file is **not** part of the corpus the RAG system
indexes — it is the answer key used only by `eval.py` / by us when grading.

---

## Contradiction 1 — Attendance threshold for exam eligibility

**File:** `regulations.md`
**Clause A:** 3.2.2
**Clause B:** 3.5.2

> **3.2.2** — "Under no circumstances shall a student with attendance below
> seventy-five percent (75%) in a course be permitted to appear for the
> end-term examination of that course. This threshold is absolute and
> applies uniformly to every student and every course offered by the
> Institute."

> **3.5.2** — "Where a Medical Exemption is granted under clause 3.5.1, the
> student shall be deemed eligible to sit for the end-term examination
> provided their attendance in the affected course is not below sixty-five
> percent (65%), notwithstanding the threshold specified in clause 3.2."

**Why this is a genuine contradiction, not a nuance:** 3.2.2 does not say
"75%, subject to Section 3.5" — it explicitly asserts the threshold is
**absolute** and admits **no exceptions** ("under no circumstances"). Clause
3.5.2 then creates exactly the exception 3.2.2 says cannot exist, lowering
the bar to 65% for medically-exempted students. A careful reader cannot
determine, from the text alone, whether a medically-exempted student at 68%
attendance is eligible (per 3.5.2) or categorically barred (per 3.2.2's "under
no circumstances" language). Nothing in the document states that 3.5
overrides 3.2; clause 4.1.1 even cites both as jointly governing eligibility
without resolving the clash.

**Test question this should trigger on:** "I have a medical exemption and
68% attendance in a course. Can I sit the end-term exam?"

**Expected system behavior:** `status: CONTRADICTION`, citing both 3.2.2 and
3.5.2.

---

## Contradiction 2 — Re-evaluation application deadline

**File A:** `regulations.md`, clause 5.2.1
**File B:** `fee_deadlines.md`, Section 3 table, "Re-evaluation Fee" row

> **regulations.md, 5.2.1** — "An application for re-evaluation must be
> submitted to the Controller of Examinations within **ten (10) calendar
> days** of the Result Declaration Date, accompanied by the prescribed fee."

> **fee_deadlines.md, Section 3** — Re-evaluation Fee row: "**Within 15
> working days of result declaration**."

**Why this is a genuine contradiction:** the two numbers are not merely
different units of the same figure — 10 calendar days and 15 working days
are different windows in both magnitude and definition (a "working day"
excludes Sundays and holidays per regulations.md clause 1.2.3, so 15 working
days is meaningfully longer than 10 calendar days). Clause 8.1.2 of
regulations.md states fee_deadlines.md prevails over regulations.md for
*amounts*, but re-evaluation *deadlines* are not amounts, so it is genuinely
ambiguous which document governs the deadline itself.

**Test question this should trigger on:** "I got my result 12 days ago and
want to apply for re-evaluation. Am I still within the deadline?"

**Expected system behavior:** `status: CONTRADICTION`, citing both
regulations.md 5.2.1 and the fee_deadlines.md re-evaluation row.

---

## Contradiction 3 — Final authority over hostel disciplinary violations

**File A:** `regulations.md`, clause 9.1.2
**File B:** `hostel_handbook.pdf`, clause H.7.3

> **regulations.md, 9.1.2** — "The Disciplinary Committee has final authority
> over all matters of student conduct across the Institute, including but
> not limited to academic dishonesty, examination unfair means, **hostel
> violations**, harassment complaints, and damage to Institute property, and
> its decisions on such matters are binding on all Institute officers."

> **hostel_handbook.pdf, H.7.3** — "...the Warden holds **final and binding**
> disciplinary authority and may impose sanctions including a fine, a formal
> warning placed on the student's record, temporary suspension of hostel
> privileges, or recommendation for eviction from the hostel. **The Warden's
> decision in such matters is final and is not subject to review by any
> other Institute body.**"

**Why this is a genuine contradiction:** both clauses use the word "final."
regulations.md 9.1.2 names hostel violations explicitly as within the
Disciplinary Committee's final authority. hostel_handbook.pdf H.7.3 grants
the Warden final authority over serious/repeat hostel violations and
explicitly forecloses review "by any other Institute body" — which on its
face would include the Disciplinary Committee. regulations.md 7.3.2 says
serious hostel matters "shall be referred to" the Disciplinary Committee,
which is in tension with the Warden's H.7.3 authority being final and
unreviewable. The corpus gives no rule for resolving which body's "final"
actually wins.

**Test question this should trigger on:** "The hostel warden suspended my
hostel privileges for a repeat violation and won't reconsider. Can I take
this to the Disciplinary Committee?"

**Expected system behavior:** `status: CONTRADICTION`, citing both
regulations.md 9.1.2 (and optionally 7.3.2) and hostel_handbook.pdf H.7.3.

---

## Summary table

| # | Topic | Clause A | Clause B | Nature of conflict |
|---|---|---|---|---|
| 1 | Attendance threshold w/ medical exemption | regulations.md 3.2.2 | regulations.md 3.5.2 | Absolute rule vs. explicit carve-out of same rule |
| 2 | Re-evaluation deadline | regulations.md 5.2.1 | fee_deadlines.md §3 (Re-evaluation Fee row) | Different deadline windows across two documents |
| 3 | Final hostel disciplinary authority | regulations.md 9.1.2 | hostel_handbook.pdf H.7.3 | Two different bodies both claim unreviewable "final" authority over the same matter |
