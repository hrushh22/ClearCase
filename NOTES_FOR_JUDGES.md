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

## Data and privacy
- Gemini and Mistral free tiers may use inputs for training. The organizers approved sending this sample data. A real firm would use paid, no-training endpoints.
- Clio is never written to. Our data lives in SQLite (`clearcase.db`) plus caches under `backend/data/`, all gitignored.

## Cost per case
Free tiers: $0. Token counts per call are logged; `GET /api/usage` shows totals and an estimate at paid list prices. Re-opening the dashboard costs nothing (cached digest), and a re-sync only re-extracts sources whose content hash changed.
