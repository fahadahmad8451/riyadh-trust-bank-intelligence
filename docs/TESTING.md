# Testing Phase — Project 1 (v0.5)

**Date:** 2026-11-06. **System under test:** v0.5.0 (Sprint 4 complete).
**Environment:** this VM, `~/rtb-venv` (Python 3.12, torch 2.15 CPU), no Docker,
no PostgreSQL server, no Ollama (extractive-fallback mode).
**Scope:** test only — no new features. Only one environment fix was made
(see BUG-1); no application code was changed, so **no v0.5.1 zip was created**
— v0.5 is unchanged; this file is the Testing deliverable.

## 1. Full regression — results

| Check | Command | Result |
|---|---|---|
| Full pytest suite | `python -m pytest ../tests/ -q` (from `backend/`) | **57 passed, 0 failed** (142 s) — after fixing BUG-1; first run was 20 passed / 4 failed / 33 errors |
| Search test | `python scripts/search_test.py` | **PASS 3/3** — KYC 0.6630, AML 0.4753, Account Opening 0.4524 |
| RAG test | `python scripts/rag_test.py` | **PASS 10/10** + out-of-scope refusal PASS |
| Full eval | `python scripts/run_eval.py` | 20 questions, aggregates reproduced exactly (see §4) |
| Frontend build | `npm install && npm run build` (in a /tmp copy) | **PASS** — tsc + vite, 38 modules, 2.69 s |
| py_compile | `python -m py_compile $(find app -name "*.py")` | **OK** |

## 2. End-to-end journeys (live uvicorn :8125, real HTTP)

Journey script: `/tmp/journeys.py` (kept outside the project on purpose —
it is a test harness, not project code). Demo users: admin / compliance /
service (see docs/SPRINT3.md).

| # | Journey step | Expected | Actual | Result |
|---|---|---|---|---|
| D1 | No-token POST /chat | 401 | 401 | PASS |
| D2 | Wrong password login | 401 | 401 | PASS |
| D3 | Unknown email login | 401 | 401 | PASS |
| A1 | Service login | 200 | 200 | PASS |
| A2 | Service KYC question (EN) | 200 + citations | 200, 5 citations (KYC p.1 top), 5.9–6.4 s | PASS |
| A3 | Service KYC citations RETAIL only | no AML/SAMA/HR/PDPL | KYC, Account Opening, Charges only | PASS |
| A4 | Service feedback thumbs-up | 200 | 200, "Shukriya, feedback mil gaya" | PASS |
| A5 | Service logout | 200 | 200 | PASS |
| B1 | Compliance login | 200 | 200 | PASS |
| B2 | Compliance AML question (AR) | AML citation | AML Policy cited (top), 0.18–0.25 s | PASS |
| B3 | Compliance GET /documents | 6 docs, no HR/PDPL | 6 docs, hr_seen=[] | PASS |
| B4 | Compliance logout | 200 | 200 | PASS |
| C1 | Admin login | 200 | 200 | PASS |
| C2 | Admin upload 1-page test PDF | 201 | 201, chunk_count 1, dept RETAIL | PASS |
| C3 | Uploaded doc in list | 9 docs incl. test-policy | 9 docs, test-policy.pdf present | PASS |
| C4 | Audit log shows upload | UPLOAD entry | 100 logs, 6 UPLOAD entries (incl. test-policy.pdf) | PASS |
| C5 | Admin delete test PDF | 200 | 200, chunks_removed 1 | PASS |
| C6 | Deleted doc gone | 8 docs | 8 docs | PASS |
| C7 | Admin logout | 200 | 200 | PASS |
| D4 | Service GET /documents/02-aml-policy.pdf | 404 | 404 | PASS |
| D5 | Service upload | 403 | 403 | PASS |
| D6 | Service GET /admin/audit-logs | 403 | 403 | PASS |
| E1 | Out-of-scope ("weather in Jeddah") | refusal, 0 citations | refused, "Is document me ye maloomat nahi hai." | PASS |
| E2 | Service AML question | RBAC refusal, 0 citations | rbac-refusal, "Aap ke role ko is topic ke documents dekhne ki ijazat nahi hai" | PASS |
| E3 | Service HR-leave question | RBAC refusal, 0 citations | rbac-refusal, 0 citations | PASS |

**Journeys: 25/25 PASS, 0 FAIL** (second full run; first run was 24/25 —
the one failure was a bug in my own test script's parsing of the
audit-logs response shape `{"audit_logs": [...]}`, not an app bug;
verified against `data/audit.jsonl`, which held the UPLOAD entry.)

Test data left behind: audit/conversations/feedback JSONL grew with test
traffic (expected — they are the audit record, gitignored, excluded from
zips). The test PDF was uploaded and then deleted; the manifest is back
to 8 documents and `data/docs/` holds no test file.

## 3. Success criteria (Plan §1) — honest check

| # | Criterion | Result | Verdict |
|---|---|---|---|
| 1 | Every non-refusal answer has source + page | 20/20 eval questions cited; 10/10 RAG test cited; journeys A2/B2 cited with page | **PASS** |
| 2 | Cross-access 0% | 23 RBAC tests pass; journeys B3/D4/D5/D6/E2/E3 — zero leaks found | **PASS** |
| 3 | Search answer < 3 s (steady-state, excl. first model load) | Arabic ~0.2 s PASS; **English 4.3–8.4 s FAIL** on this VM (warm server, 3 consecutive EN chats: 4.3 s, 6.7 s, 8.4 s; rag_test EN 3.7–4.1 s; eval p50 1,352 ms overall, p95 9,369 ms) — cross-encoder reranker (+ RBAC probe) adds 2–6 s per EN query | **PARTIAL FAIL** |
| 4 | ≥ 17/20 eval questions correct with source | Top-doc correct 19/20, context recall 1.00, all 20 cited | **PASS** (strict phrase match is only 12/20 — see BUG-3; the answers are correct and cited, but extractive quotes often pick the intro sentence instead of the fact sentence) |

## 4. Evaluation aggregates (re-run, reproduced exactly)

20 questions, ADMIN, extractive-fallback (Ollama not reachable on this VM).
Method: local RAGAS-style (no LLM judge) — see docs/SPRINT4.md.

| Metric | Actual | Target | Verdict |
|---|---|---|---|
| faithfulness | 1.0000 | ≥ 0.85 | PASS (trivial in extractive mode — answer IS the cited quote) |
| context_recall | 1.0000 | ≥ 0.80 | PASS |
| answer_relevancy | 0.4172 | ≥ 0.85 | MISS (MiniLM is English-only: EN mean 0.60, AR mean 0.24) |
| top_doc_accuracy | 0.95 (19/20) | — | — |
| phrase_present_rate | 0.60 (12/20) | — | — |
| latency p50 / p95 | 1,352 ms / 9,369 ms | — | — |

## 5. Bug list

| ID | Severity | Bug | Reproduce | Status |
|---|---|---|---|---|
| BUG-1 | **Major — FIXED** | First pytest run: **33 errors + 4 failed**. Root cause was environment drift, not app code: `~/rtb-venv` had **bcrypt 5.0.0** while `requirements.txt` pins `bcrypt==4.0.1`; passlib 1.7.4 is incompatible with bcrypt ≥ 4.1 (it reads the removed `bcrypt.__about__`) and `hash_password()` raised `ValueError: password cannot be longer than 72 bytes` in every test fixture that seeds users. | Run the suite in a venv with bcrypt 5.x | **Fixed** — `pip install bcrypt==4.0.1` in the venv (no code change). Re-run: **57 passed**. Related drift noted: venv also has fastapi 0.162.0 and sentence-transformers 6.2.0 vs pinned 0.115.0 / 3.1.1 — `pip check` is clean and tests pass, but a fresh venv should be built from `requirements.txt` exactly. |
| BUG-2 | **Major — KNOWN LIMITATION** | English chat latency 4–8 s steady-state vs the < 3 s criterion (see §3.3). Cause: cross-encoder reranker + RBAC probe per EN query, on a RAM-starved VM (~570 MB free). | Warm server, any EN chat (e.g. loan question) | **Not fixed** — fixing it means a design change (drop/skip the cross-encoder for EN, cache it, or accept it), which is out of Testing scope. Must be re-measured on Fahad's PC (more RAM, Ollama) during Staging. |
| BUG-3 | Minor — KNOWN | Arabic visual-order garbling: Arabic quotes come out with clauses/numbers in the wrong order (e.g. HR leave numbers attached to the wrong clause); breaks 5 of 20 eval phrases. Known since Sprint 1, carried through Sprint 4. | Any Arabic answer, e.g. annual-leave question | **Not fixed** — real fix is regenerating the source PDFs with logical-order Arabic (Sprint-1 data fix). |
| BUG-4 | Minor — KNOWN | answer_relevancy 0.4172 vs 0.85 target — MiniLM cannot judge Arabic; extractive quotes score 0.50–0.75 even in English. | `scripts/run_eval.py` | **Not fixed** — needs BGE-M3 (multilingual) + a real LLM; recorded in SPRINT4.md. |
| — | Test-harness notes (NOT product bugs) | (a) My first journey script crashed on httpx picking up a proxy env var for `127.0.0.1` — fixed with `trust_env=False`. (b) First C4 "failure" was my script reading the wrong response key (`logs` instead of `audit_logs`). Both fixed in `/tmp/journeys.py`; the app was correct in both cases. | — | Fixed in harness |

No other bugs found. No Blocker.

## 6. GO / NO-GO for Staging

**Recommendation: CONDITIONAL GO.**

Reasons for GO: all 57 unit tests pass; all 25 end-to-end journey checks
pass; RBAC is airtight in every test (0 leaks); every answer is cited;
refusals work (out-of-scope + RBAC-blocked); feedback and audit logging
work live; frontend builds cleanly; eval reproduces Sprint 4 exactly.

Conditions (must be carried into Staging, not hidden):
1. Re-measure English chat latency on Fahad's PC during Staging
   (Ollama live, more RAM). If it is still > 3 s there, decide then
   whether to keep the cross-encoder or make it optional.
2. Known limitations stay documented for the portfolio: Arabic
   visual-order garbling, relevancy 0.42 (MiniLM), extractive mode
   until Ollama runs, PgVector path still code-only (test on
   Fahad's PC, PostgreSQL on port 5432).
3. Rebuild the venv from `requirements.txt` on Fahad's PC
   (`bcrypt==4.0.1` — see BUG-1); do not copy this VM's venv.

## 7. Windows manual test checklist (Fahad — repeat on your PC)

Prerequisites: backend venv active, `uvicorn app.main:app --port 8000`,
frontend `npm run dev` (optional for UI checks). Demo logins:
`admin@rtb.local / Admin123!`, `compliance@rtb.local / Compliance123!`,
`service@rtb.local / Service123!` (DEMO ONLY).

```powershell
# 1. Health
curl http://127.0.0.1:8000/api/v1/health
# 2. Service login (PowerShell: capture the token, then use it)
# 3. Chat as service (KYC question) -> citations must be RETAIL only
# 4. Same question as compliance -> AML citation must appear
# 5. Service: GET /api/v1/documents/02-aml-policy.pdf -> must be 404
# 6. Out-of-scope: "What is the weather in Jeddah tomorrow?" -> refusal
# 7. Admin: upload a PDF -> it appears in documents; delete it again
# 8. Admin: GET /api/v1/admin/audit-logs -> upload must be listed
# 9. Eval: python ..\scripts\run_eval.py  (takes ~2 min, ADMIN)
# 10. pytest: python -m pytest ..\tests\ -q  (takes ~2-3 min)
```

If step 5 returns 200 or step 4 shows an AML citation for the service
user, STOP — that is an RBAC leak, and Staging must not proceed.
