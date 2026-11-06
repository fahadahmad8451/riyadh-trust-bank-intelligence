# Sprint 4 — Evaluation + Polish (v0.5)

**Status:** DONE and verified on this VM, 2026-11-06.
**Last development sprint.** What comes after this is Testing → Staging →
Production → Monitoring (NOT built in this sprint — see "What comes next").

Scope: (1) real user feedback on answers, (2) honest evaluation of the
20-question test set with local RAGAS-style metrics, (3) polish from the
Sprint 2/3 known-limitations list. No Docker (Fahad's laptop cannot run
it — BIOS locked + VT-x Disabled); local-first, same as Sprints 1–3.

## 1. What was built

### Feedback (real, not a stub)
- `POST /api/v1/feedback` — login required. Body
  `{message_id, rating: up|down, comment?}`. The `message_id` must be a
  real assistant message in `data/conversations.jsonl` (every chat answer
  now returns a `message_id`); a made-up id is rejected. One vote per
  (user, message) — voting again updates the vote, it does not duplicate
  it. Stores in `data/feedback.jsonl` (gitignored). Returns
  `"Shukriya, feedback mil gaya."`
- `GET /api/v1/admin/feedback-stats` — ADMIN only: `total`, `up`, `down`,
  `percent_up`, and `worst` — the down-rated messages with the preceding
  user question, the answer excerpt and its citations.
- Feedback DB table: **NOT populated** (honest note). Messages live in
  `data/conversations.jsonl`, not in the database, so the `feedback`
  table's foreign key to a DB message cannot be satisfied. The JSONL file
  is the record; the table exists in the schema for the PostgreSQL
  deployment, when chat history moves to the DB.
- Frontend: every assistant answer in Chat has 👍 / 👎 buttons (uses the
  real `message_id`); on success it shows "Shukriya, feedback mil gaya."
  Admin has a Feedback section (totals + worst table, empty state when
  there is no feedback yet).

### Evaluation (honest, no fake scores)
- Test set `tests/eval_set.json` — **20 questions, fixed set, do not edit
  to pass**: 10 English + 10 Arabic, each with `expected_documents`,
  `expected_page` and a short `expected_phrase`. Reuses the Sprint 2 ten
  (e01–e10) and adds ten new ones (e11–e20) covering SAMA complaints,
  PDPL data requests, HR leave, loan terms/fees and charges.
- `backend/app/services/evaluation.py` + `scripts/run_eval.py` +
  `GET /api/v1/eval/run` (ADMIN, synchronous, `?limit=N` for tests) +
  `GET /api/v1/eval/results` (ADMIN, reads the last stored run).
  Runs the 20 questions as ADMIN (all departments visible) and stores
  the full report in `data/eval_results.json` (gitignored).
- **ragas is NOT installed on this VM**, and RAGAS needs a paid LLM
  judge (OpenAI/Azure) — so the metrics are **local RAGAS-style
  (no LLM judge)**, labelled as such in every output (script, API,
  frontend, this doc). They are NEVER presented as official RAGAS scores.

### RBAC-blocked refusal (polish)
- When a role asks about a topic in a department they cannot see AND no
  allowed chunk matches well, the answer is now a clean refusal:
  - EN: *"You do not have permission to view documents on this topic."*
  - AR: *"ليس لديك صلاحية لعرض المستندات المتعلقة بهذا الموضوع."*
  - Roman Urdu (chat display): *"Aap ke role ko is topic ke documents
    dekhne ki ijazat nahi hai"*
  - `generation_mode: "rbac-refusal"`, `refused: true`, `citations: []`,
    `rbac_blocked: true`, `blocked_department: COMPLIANCE|HR`.
- How it decides (see `generation._rbac_blocked_department`): one
  unrestricted probe (top-1, all departments) vs the allowed retrieval,
  compared on reranker scores — blocked = the best chunk is in a hidden
  department, matches strongly, and the allowed retrieval is clearly
  weaker; plus a gate (unrestricted vector ≥ 0.35 or BM25 > 0) so a
  genuinely out-of-scope question still gets the normal refusal, not
  the RBAC one. The old behaviour (an answer from allowed chunks) is
  kept only when an allowed chunk genuinely matches.
- Verified live: service + AML → rbac-refusal COMPLIANCE; service /
  compliance + HR leave → rbac-refusal HR; service + KYC → answered;
  service + weather → normal refusal; compliance + AR AML → answered
  with AML citation; admin + HR → answered with HR citation. (8/8)

### Arabic (attempted, NOT fixed — honest)
- The visual-order defect from Sprint 1 is still there: the synthetic
  PDFs store Arabic in presentation forms, so PyMuPDF extraction returns
  clauses in reverse order with numbers attached to the wrong clause
  (e.g. HR chunk shows maternity as "30 days" and sick leave as "3…").
  Two small fixes were tried (reversing each Arabic run character-wise;
  reversing token order) — both produce gibberish. **No reliable small
  string fix exists, so the text is left visual-order and recorded here
  as a remaining limitation.** The real fix is regenerating the PDFs
  with logical-order Arabic (or a different PDF generator) — a
  Sprint-1 data fix, not a Sprint-4 code fix.

### Small UX polish
- Chat: thumbs up/down per answer, "Shukriya, feedback mil gaya" on
  success, error text in plain Roman Urdu/English.
- Admin: Evaluation section (aggregates vs targets, per-question table,
  "Run evaluation" button with a running state + "2–4 minute" note, and
  an empty state when no run exists yet) and a Feedback section (totals
  + worst table, empty state).
- RBAC refusals show a "No access to this topic" badge in Chat.

## 2. Evaluation method (exact formulas)

All three metrics are computed WITHOUT a paid LLM, from the real
pipeline output (retrieval + extractive answer) and the cited chunks.

- **faithfulness** = (answer sentences supported by the cited chunks) /
  (answer sentences counted). A sentence is a *claim* if it has ≥ 3
  content tokens (short fragments/intros are not counted). A claim is
  *supported* if ≥ 30% of its content tokens appear in the union of the
  cited chunks' content tokens. Content tokens = retrieval tokenisation
  minus stopwords. Refusals score 0.0 (no answer to support).
  **Known blind spot:** this checks the answer against the *cited
  chunk*, not against the truth — so a garbled Arabic quote scores 1.0
  because it matches its (garbled) source. `phrase_present` is the
  check that catches garbling (see §3).
- **context_recall** = 1 if any expected document appears in the top-5
  citations, else 0 — averaged over questions. (Per-question 0/1;
  the Design target ≥ 0.80 is on the mean.)
- **answer_relevancy** = cosine similarity between the MiniLM
  (all-MiniLM-L6-v2, 384-dim — the same model as Sprint 1) embeddings
  of the question and the answer. **Caveat:** MiniLM is English-only,
  so Arabic Q/A cosines are low by construction (see §3) — the metric
  is reported, not hidden, but it is not a fair judge of Arabic.
- Also reported: `top_doc_accuracy` (share of questions whose top-1
  citation is an expected document), `phrase_present_rate` (share whose
  expected phrase appears in the answer — the strictest check),
  latency p50/p95 per question.
- Targets (Design §10): faithfulness ≥ 0.85, context_recall ≥ 0.80,
  answer_relevancy ≥ 0.85. A missed target is reported as-is; the test
  set was NOT tuned to pass.

**Bug found and fixed during this sprint (2026-11-06):** the first full
eval run reported faithfulness **0.00 for all 20 questions**. Cause:
`evaluate_question` looked the cited chunks up by
`(document_id, chunk_index)`, but citations carry only
`(document_id, page_no)` — `generation._citations` drops `chunk_index`.
The lookup matched nothing, so faithfulness fell back to 0. Fixed by
looking up by `(document_id, page_no)` (all chunks of the cited page).
The corrected run is the one reported in §3; the broken run was
discarded, not reported.

## 3. Results — 20-question eval (run 2026-11-06, ~94 s, ADMIN)

Aggregates (mean over 20 questions):

| Metric | Actual | Target | Verdict |
|---|---|---|---|
| faithfulness | **1.0000** | ≥ 0.85 | ✅ PASS |
| context_recall | **1.0000** | ≥ 0.80 | ✅ PASS |
| answer_relevancy | **0.4172** | ≥ 0.85 | ❌ MISS — reported as-is |
| top_doc_accuracy | 0.9500 (19/20) | — | — |
| phrase_present_rate | 0.6000 (12/20) | — | — |
| refused | 0/20 | — | — |
| latency p50 / p95 | 1,340 / 10,579 ms | — | — |

**All targets met: NO** (relevancy misses).

Per-question table (run as ADMIN, mode extractive-fallback for all 20 —
Ollama is not reachable on this VM, same as Sprints 2–3):

| ID | Lang | Top doc | Recall | Faith. | Relev. | Phrase | ms |
|---|---|---|---|---|---|---|---|
| e01 | en | 01-kyc-policy.pdf | 1 | 1.00 | 0.75 | no | 25,177 |
| e02 | en | 02-aml-policy.pdf | 1 | 1.00 | 0.57 | yes | 2,403 |
| e03 | en | 05-account-opening-policy.pdf | 1 | 1.00 | 0.52 | no | 9,811 |
| e04 | en | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.59 | yes | 5,309 |
| e05 | en | 06-hr-leave-policy.pdf | 1 | 1.00 | 0.50 | yes | 8,728 |
| e06 | en | 07-charges-fees-schedule.pdf | 1 | 1.00 | 0.67 | yes | 8,515 |
| e07 | ar | 05-account-opening-policy.pdf | 1 | 1.00 | 0.30 | no | 253 |
| e08 | ar | 02-aml-policy.pdf | 1 | 1.00 | 0.14 | yes | 234 |
| e09 | ar | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.28 | yes | 278 |
| e10 | ar | 06-hr-leave-policy.pdf | 1 | 1.00 | 0.29 | no | 213 |
| e11 | ar | 03-sama-compliance-summary.pdf | 1 | 1.00 | 0.12 | no | 223 |
| e12 | en | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.53 | no | 3,998 |
| e13 | en | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.60 | yes | 5,216 |
| e14 | en | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.70 | yes | 5,486 |
| e15 | en | 06-hr-leave-policy.pdf | 1 | 1.00 | 0.56 | yes | 9,077 |
| e16 | ar | 06-hr-leave-policy.pdf | 1 | 1.00 | 0.24 | no | 218 |
| e17 | ar | 03-sama-compliance-summary.pdf | 1 | 1.00 | 0.16 | yes | 259 |
| e18 | ar | 07-charges-fees-schedule.pdf | 1 | 1.00 | 0.42 | no | 206 |
| e19 | ar | 04-personal-loan-policy.pdf | 1 | 1.00 | 0.25 | yes | 271 |
| e20 | ar | 02-aml-policy.pdf | 1 | 1.00 | 0.16 | yes | 230 |

### How to read these numbers (honest)
- **faithfulness 1.00 is expected, not a triumph.** In extractive mode
  the answer IS a quote from the cited chunks, so every sentence is
  "supported" by construction. This metric becomes meaningful only once
  a real LLM generates answers (Ollama on Fahad's PC). It still proves
  the pipeline never invents text — it only quotes.
- **context_recall 1.00 / top-doc 19/20:** retrieval works. The one
  top-doc miss is e07 (Arabic "what documents to open an account" —
  top doc was Account Opening, expected KYC; KYC was still in the
  top-5, so recall is 1).
- **answer_relevancy 0.4172 MISS — two real causes.** English mean
  0.5986, Arabic mean 0.2359. (a) MiniLM is English-only: Arabic Q/A
  cosines sit at 0.12–0.42 no matter how good the answer is — this
  metric cannot judge Arabic until a multilingual embedding model
  (BGE-M3, per Design) is used. (b) Even in English, long extractive
  quotes score 0.50–0.75 against a short question; the 0.85 target was
  set for a real LLM + better embeddings, not for MiniLM + extractive
  quotes. The target is NOT lowered and the set was NOT tuned — the
  miss stands until the stack improves.
- **phrase_present 12/20 — the strictest check, and the most useful
  one.** The 8 misses have two root causes: (1) extractive top-2
  sentences pick the intro/heading sentence instead of the fact
  sentence — e01 ("National ID card" never quoted), e03 (answer is
  about *closing* an account, not the 45-minute opening time), e12
  (answer quotes the loan "Purpose" intro, not the 60-month term).
  (2) Arabic visual-order garbling — e07, e10, e11, e16, e18: the
  expected phrase is split across scrambled clauses or its numbers are
  attached to the wrong clause (e.g. e16 maternity "10 أسابيع" comes
  out as "10 يوما إجازة سنوية… 30"). These 5 are the same defect as
  §1 — fix the PDF data, not the scorer.
- **Latency:** p50 1,340 ms, p95 10,579 ms. Arabic is fast (~200 ms —
  score-based rerank, no cross-encoder); English pays 2–10 s for the
  cross-encoder reranker + the RBAC probe (one extra unrestricted
  retrieval per question). e01 took 25 s (first question — model
  warm-up). Full 20-question run: ~94 s.

### Feedback (live, at verification time)
- One real vote during the live test: admin 👍 on a KYC answer →
  `POST /feedback` returned "Shukriya, feedback mil gaya." and
  `GET /admin/feedback-stats` showed `total 1, up 1, down 0,
  percent_up 100.0`. (This is one demo vote, not a user study.)

## 4. Verification (all run, real output)

- **Eval:** `python ../scripts/run_eval.py` — full 20-question table
  above; aggregates faithfulness 1.0000, recall 1.0000, relevancy
  0.4172; run 93.6 s. Full report in `data/eval_results.json`.
- **pytest:** full suite **57 passed, 0 failed** (43 from Sprints 1–3
  + 14 new: feedback auth/validation/upsert/stats, eval-set validity,
  metric unit tests, RBAC-refusal ×3, eval-run limit-2 + admin-only).
  Two old health tests were updated for v0.5 (version 0.5.0; the 501
  test became "no endpoints left unimplemented" — feedback and eval
  are built now, so there is no stub left to return 501).
- **Live FastAPI test** (uvicorn, port 8123): admin login → chat
  (extractive-fallback, 5 citations, `message_id` returned) → POST
  /feedback up → `"Shukriya, feedback mil gaya."` → GET
  /admin/feedback-stats `{total: 1, up: 1, down: 0, percent_up: 100.0}`
  → GET /eval/results (aggregates as above) → GET /health
  `version 0.5.0, status ok`.
- **py_compile:** all new/changed backend files pass.
- **Frontend:** `npm run build` in a /tmp copy passes (tsc + vite,
  38 modules, ~2 s). Chat thumbs + Admin Evaluation/Feedback sections
  included.
- **No 501 stubs remain** — `app/api/v1/stubs.py` is empty in v0.5;
  `/api/v1/metrics` reports `endpoints_pending: []`.

## 5. Files changed (Sprint 4)

| File | Change |
|---|---|
| `tests/eval_set.json` | 20 questions (10 EN + 10 AR), fixed set |
| `backend/app/services/evaluation.py` | NEW — local RAGAS-style metrics + `run_eval` |
| `backend/app/api/v1/feedback.py` | NEW — POST /feedback, GET /admin/feedback-stats |
| `backend/app/api/v1/eval.py` | NEW — GET /eval/run, GET /eval/results |
| `backend/app/api/v1/chat.py` | `message_id` per message, returned in response; forwards `rbac_blocked` / `blocked_department` |
| `backend/app/services/generation.py` | RBAC-blocked refusal (`rbac-refusal` mode) |
| `backend/app/api/v1/stubs.py` | Emptied — no stubs left in v0.5 |
| `backend/app/main.py` | Wires feedback + eval routers; IMPLEMENTED list updated |
| `backend/app/core/config.py` | version 0.4.0 → **0.5.0** |
| `scripts/run_eval.py` | NEW — CLI eval runner (exit 0 always; measurement, not a gate) |
| `tests/test_feedback_eval.py` | NEW — 14 tests |
| `tests/test_health.py` | Updated for v0.5 (version + no-stubs test) |
| `frontend/src/api/client.ts` | `feedback`, `feedbackStats`, `evalResults`, `evalRun` + types |
| `frontend/src/pages/Chat.tsx` | Thumbs up/down per answer + "Shukriya" message |
| `frontend/src/pages/Admin.tsx` | Evaluation + Feedback sections |
| `docs/SPRINT4.md` | This file |

## 6. Remaining limitations (carried forward, NOT fixed)

From Sprint 4 (new) and earlier sprints:
- **Arabic visual-order defect** (§1) — numbers attached to wrong
  clauses in Arabic quotes; breaks 5 of the 20 eval phrases. Fix =
  regenerate the source PDFs with logical-order Arabic.
- **answer_relevancy misses target (0.42 vs 0.85)** — needs BGE-M3
  (multilingual) + a real LLM; MiniLM cannot judge Arabic.
- **Extractive top-2 sentences** sometimes quote the intro instead of
  the fact (e01/e03/e12) — a real LLM answer (Ollama) or a
  sentence-ranker that prefers fact sentences would fix this.
- **faithfulness 1.00 is trivially high** in extractive mode — it only
  becomes a real test with LLM generation.
- Tokens in localStorage (demo; httpOnly cookie is the production fix);
  access tokens not revocable before 15-min expiry; audit DB table
  mirrors only on PostgreSQL; cross-encoder adds ~2–6 s/query
  (English); PgVector path still code-only, not live-tested on this VM
  (test on Fahad's PC, port 5432).
- Feedback DB table not populated (JSONL is the record — see §1).

## 7. Windows PowerShell run steps (Fahad's PC)

```powershell
cd C:\path\to\riyadh-trust-bank-intelligence\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --port 8000
# new terminal, same folder, venv active:
python ..\scripts\run_eval.py        # full 20-question eval (~2 min)
# or in the browser: Admin -> Evaluation -> "Run evaluation"
# Feedback: Chat me kisi jawab par 👍 ya 👎 dabao; Admin -> Feedback me dekho.
```

Ollama (real LLM answers, not extractive): install Ollama for Windows,
`ollama pull llama3.1:8b`, leave it running — the backend auto-detects
it and switches `generation_mode` to `ollama`. Steps in docs/SPRINT2.md.

## 8. What comes next (NOT built in this sprint)

Per the locked process: **Testing → Staging → Production → Monitoring.**
- Testing: full user-acceptance test on Fahad's PC (PostgreSQL on
  5432, Ollama live, real LLM answers, re-run the 20-question eval and
  compare), Arabic PDF regeneration (logical order), BGE-M3 embeddings
  (needs good internet + RAM), RAGAS with a real LLM judge if a budget
  ever exists.
- Staging / Production / Monitoring: deployment, httpOnly-cookie auth,
  token revocation, Langfuse observability, monitoring dashboards —
  separate steps, after Fahad's approval.
