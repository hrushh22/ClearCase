# Notes for judges

## Where to look first
1. Click any number or date on the dashboard. It opens the source; for scanned PDFs it opens the exact page with the supporting text highlighted, using OCR word boxes ([documents.py](backend/app/documents.py), [SourceViewer.tsx](frontend/src/components/SourceViewer.tsx)).
2. **Coverage KPI.** It does not invent a limit. It reports the $100,000 per-person driver policy confirmed in writing, and that Metro-North is self-insured.
3. **Settlement waterfall.** Drag the slider and negotiate individual liens down. The math is [plain code with tests](backend/app/waterfall.py).
4. **Share with providers.** Look at the AI's share/withhold proposal, the live preview, and the signed provider page that verifies each line in the browser.
5. **Read-only Clio guard** and its tests: [clio_client.py](backend/app/clio_client.py), [test_clio_readonly.py](backend/tests/test_clio_readonly.py).

## Nothing about Sapini is hardcoded
Every value comes from Clio (or, offline only, the organizers' mirror of the same data) at runtime. Some code does rely on generic personal-injury vocabulary, never on Sapini specifics:
- Regex cues for stage evidence ("summons", "demand package", "settlement").
- Custom-field names mapped to fact types ("case value" → valuation, "policy" → coverage).
- Provider-name tokens used to match a provider to its own bills.

## Assumptions (labeled in the UI)
- Attorney fee defaults to 33.3%. Lien reductions default to 0%. Payment order defaults to asserted liens first, then largest bills. None of these are in the data, and all are adjustable and resettable.
- Provider bills may overlap with amounts already paid by no-fault or Medicaid. The file says chiro and PT ledgers are unreconciled. The attorney can exclude lines.
- "Today" for overdue and upcoming is the real current date.

## Mocked or partial
- **Email notifications.** Real only if `RESEND_API_KEY` is set. Otherwise they are written to the event log as "[mocked email]" and the provider page says so.
- **Heuristic mode.** With no LLM key, extraction, ranking and stage use rules, and the UI labels this. With keys, the agents use Mistral and Groq (and Gemini as failover).
- **Gemini vision.** Gemini is wired as a provider and failover, but scanned pages are read by local OCR (RapidOCR). We did not send ~520 page images to the free tier.
- **Merkle inclusion proofs and true ZK range proofs.** Roadmap. What ships is signed selective disclosure (Ed25519 over `{claim, case_ref, issued_at, expires_at, source_hash}`).
- **Users.** One attorney view ("attorney"); there is no login system.

## Live Clio differs from the JSON mirror (and we read live)
The live Sapini matter has 15 contacts (vs 10 in the JSON), 14 expenses (vs 5) and 31 documents. In place of the two large scanned
bundles it has per-provider records and itemized bills, mostly text PDFs. ClearCase reads whatever Clio returns. Clio returns
`statute_of_limitations` as a reference to the SOL task, so we resolve it to that task's due date.

## Free-tier reality
If a key has no quota (for example a Mistral key before the "Experiment" plan is activated; the API answers 429 with
`x-ratelimit-limit-req-minute: 0`), ClearCase disables that provider for the run and fails over. Groq's free tier allows
8,000 tokens/min per model, so we use two Groq buckets: `gpt-oss-20b` for bulk extraction and `gpt-oss-120b` for reasoning.
With only Groq available, the AI reads every note, email and bill, but only the first and last 3 pages of long medical
documents. The UI says so. All pages stay viewable and highlightable, and a re-sync with Mistral or Gemini available reads them in full.

## Data and privacy
- Gemini and Mistral free tiers may use inputs for training. The organizers approved sending this sample data. A real firm would use paid, no-training endpoints.
- Clio is never written to. Our data lives in SQLite (`clearcase.db`) plus caches under `backend/data/`, all gitignored.

## Cost per case
Free tiers: $0. Token counts per call are logged; `GET /api/usage` shows totals and an estimate at paid list prices. Re-opening the dashboard costs nothing (cached digest), and a re-sync only re-extracts sources whose content hash changed.

## Case X-Ray (attorney-only)
- **Deterministic vs AI.** Contradiction rules, gaps, evidence-coverage states, the injury map, the graph, Spotlight ranking, lifecycle and Time Travel are plain code. AI is used only for (a) one cached pass pairing semantically conflicting facts, and (b) Stress Test's three roles. Every AI item must cite real verified fact ids or it is dropped. AI-paired contradictions are always labeled "Needs review".
- **Verification.** An issue is hidden if any fact it cites is not a visible, verifier-passed fact, or if its source record no longer exists. Thin or inferred findings (dates before the incident, chronology gaps, AI pairs) show as "Needs review".
- **Live Sapini result.** The rules find the inconsistencies the file itself records (three accounts of the mechanism; denial of prior injuries contradicted by the client's paperwork). The AI pairing pass found no additional pair, so none is shown; nothing is invented to fill the slot.
- **Drafts are templates** filled from the file (provider, client, open item, cited evidence). They are never sent.
- **Time Travel** uses each fact's "known at" date (its source's date). Open requests waiting on others are left out of historical views, because Clio task creation dates are not available.
- **Graph layout** is a column layout (evidence → facts → propositions/issues → people) rather than force-directed, so it stays legible and stable across rebuilds.
