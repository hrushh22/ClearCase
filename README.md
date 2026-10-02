# ClearCase

**A visual case digest for personal-injury firms, and a status page for the medical providers treating their clients on a lien.**

ClearCase reads one matter (Sapini) live from Clio Manage, read-only. It turns about 200 records and 660 pages of documents (most of them scans) into one dashboard an attorney can absorb in about 90 seconds. Every number, date and sentence on screen opens the note, email, task or exact PDF page it came from, with the supporting text highlighted, including inside scans.

## What you see

**Attorney dashboard** (`/`)
- **Snapshot.** Client photo (found by face detection in the scanned photo ID), matter, stage, incident date, SOL, responsible attorney, and when anyone last actually spoke to the client.
- **Two KPIs that matter.** Estimated case value, and the coverage behind it. Coverage is reported exactly as the file states it: here, a $100,000 per-person driver's policy confirmed in writing, while Metro-North is a self-insured public authority with no limit to find. Also medical specials (reconciled against the provider bills found in the file) and firm spend.
- **What changed since you last opened.** A diff against your last-viewed digest, plus everything dated since your last visit.
- **The ten that matter.** Out of 125 notes, emails and tasks, each with a one-line "why it matters".
- **Needs attention.** Overdue, coming up, and waiting on someone else.
- **Injuries and treatment.** From the scanned medical records, with page-level sources.
- **Settlement waterfall.** Gross, then fee, costs and each lien, then client net. Includes a settlement slider, per-lien "negotiate down" control, payment order, include/exclude, and fully / partly / not covered status at the chosen gross. Fee %, reductions and order are labeled assumptions with a reset button.
- **Stage tracker.** Treatment → Demand sent → Negotiation → Litigation → Settlement, classified from evidence with sources, plus the last-movement date.
- **Timeline with time travel.** Every date has a source. Drag the slider to see the case as of any day.
- **Dig deep mode.** Every verified fact, searchable and filterable, plus every document.

**Provider sharing** (`/share`, then `/p/<token>`)
- The **Share-Policy agent** proposes what a provider may see: status, stage, their own bill and place in line, what the firm needs from their office, upcoming visits. It also proposes what to hold back: strategy, valuation, liability problems, other providers' money.
- The attorney toggles each item and sees a **live preview of exactly the provider's page**.
- Approved items are **signed with Ed25519**. The provider's browser checks each signature against the firm's public key and shows "Verified by [Firm], as of [time]".
- Links **expire and can be revoked**. Every open is written to an **access log**. Providers can ask to be **notified when the case moves**: stage changes re-issue a signed stage claim and send an email (Resend if configured, otherwise a labeled in-app mock).
- **The allowlist is enforced on the server.** The provider endpoint only ever returns signed claims the attorney approved. Nothing is filtered in the browser.

**Case X-Ray** (`/xray`, attorney-only)
- **Case Constellation:** an interactive evidence graph built from verified facts (pan, zoom, drag, filter, click any edge or node). Documents and notes → facts → propositions and issues → providers, parties and injuries, with typed edges (supports, contradicts, missing evidence for, treated by, billed by, depends on). **Show Me Why** isolates the evidence chain behind any proposition, injury or fact, and every node opens the source viewer at the cited page.
- **Contradiction Inspector:** deterministic checks first (incident dates, Clio charge totals vs. stated amounts, liability limits, lien amounts, entries dated before the incident, inconsistencies the file itself records). Then one cached AI pass pairs facts that conflict in meaning. Results show side by side, with both sources one click away. ClearCase never decides which side is right.
- **Evidence Gap Detector + care-chain Gap Map:** providers without records or bills, imaging without reports, recommended procedures with no record of a date, material the file says is outstanding, open requests waiting on others, and chronology gaps. Framed as "ClearCase could not locate expected supporting evidence in the available case file." **Resolve this gap** drafts a records request or follow-up, creates an internal follow-up, or marks the issue reviewed, snoozed or explained. All of this is stored in ClearCase; nothing is sent and nothing is written to Clio.
- **Evidence coverage:** a support state per key proposition (well corroborated / supported / limited / incomplete / conflicting) from countable components, with the rule shown. No percentages and no outcome scores.
- **Injury X-Ray map:** body regions only where the text names a body part (side only when stated). Each region shows its findings, imaging, treatment, providers, known billed total and issues. Anything else stays unmapped.
- **Stress Test My Case:** a supporting analyst, an adversarial reviewer (using only the file) and an evidence judge. Every item must cite real, verified facts or it is rejected.
- **AI Spotlight:** steps through the highest-ranked open issues with a deterministic ranking (severity, deadline, money, facts affected, recency).
- **What changed and Time Travel:** issue lifecycle (first detected / resolved / reopened) and a "New evidence impact" strip after each sync. The Time Travel slider reconstructs "what the file showed as of [date]" from persisted facts without calling an LLM.

> Case X-Ray evaluates consistency and evidence completeness within the available file. It does not determine legal truth, predict case outcomes, or replace attorney judgment.

## How it works

```
Clio API (GET only) → INGEST → own SQLite DB (raw records, sources, documents, pages)
   → DOCUMENT AGENT     PDF text layer, or local OCR (RapidOCR) with boxes for scans; cached by SHA-256
   → EXTRACTION AGENT   structured Clio fields → facts in code; notes, emails, pages → facts via Mistral
   → VERIFIER           quote must be in the cited source (code) + "does it support the claim?" (Groq)
   → KPI · STAGE · TIMELINE · PRIORITY · INJURIES (LLM reads, code sums) · ATTENTION · CONTACT (code)
   → DIGEST CACHE       keyed by a content hash of every Clio record and document
   → SHARE-POLICY → attorney review → SIGNER → provider link
```

- **Read-only Clio, enforced twice.** All Clio traffic goes through [`ClioReadClient`](backend/app/clio_client.py), which only exposes `get()`. A transport hook also refuses any non-GET request, even one that bypasses the client. Both are covered by [tests](backend/tests/test_clio_readonly.py).
- **No AI on open.** Opening the dashboard reads the cached digest. Sync re-reads Clio and only re-runs the pipeline if the content hash changed, and then only for the sources that changed. Every LLM response is cached by prompt hash.
- **No fact without a source.** Each fact stores `source_type`, `source_id`, `page`, an exact `quote` and highlight boxes. A claim whose quote is not in its source is hidden and can never be shared or signed.
- **Deterministic money.** Waterfall math, specials sums and firm spend are plain code with [unit tests](backend/tests/test_waterfall.py). The coverage headline is LLM-written, but any dollar figure in it must appear in a cited quote, or a code-built headline replaces it.

### Models (free tiers) and cost per case

| Job | Model |
|---|---|
| Bulk extraction, timeline milestones, KPI/injury reading | Mistral `mistral-small-latest` |
| Verifier, Top-10 ranking, stage, share policy | Groq `openai/gpt-oss-120b` |
| Vision / page understanding (failover) | Google Gemini, newest Flash model the key lists |

Failover on 429 or error: Gemini → Mistral → Groq. Per-provider rate limiters keep the run inside free-tier limits. Every call's tokens are logged (`GET /api/usage`). On free tiers, one Sapini run costs **$0**. At paid list prices, a full first run is estimated at a few cents to tens of cents (see `/api/usage` after a run). Re-opening costs nothing.

If no LLM key is set, ClearCase still runs end to end in a clearly labeled **heuristic mode** (rule-based extraction and ranking), so the UI never pretends AI ran when it didn't.

## Run it

Requirements: Python 3.11+, Node 20+.

```bash
# 1. keys: paste values into .env (already created with every variable blank)
# 2. backend
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
# 3. frontend (dev)
cd ../frontend
npm install
npm run dev            # http://localhost:5173
```

Or build the frontend once (`npm run build`) and open http://localhost:8000; the backend serves `frontend/dist`.

**Clio connection.** Create a Clio developer app with redirect URI `http://localhost:8000/auth/clio/callback` and read access to Matters, Contacts, Notes, Communications, Tasks, Calendars, Activities, Documents, Custom Fields, Users and Practice Areas. Put `CLIO_CLIENT_ID` and `CLIO_CLIENT_SECRET` in `.env`, then open http://localhost:8000/auth/clio/login once. You can also paste a `CLIO_ACCESS_TOKEN` directly. Then press **Sync from Clio**.

The first sync OCRs about 520 scanned pages locally (roughly 5 to 10 s per page on a laptop CPU). That happens once: results are cached by file hash. To pre-warm the cache: `python scripts/ocr_documents.py`.

**Offline mirror (development only).** `CLIO_SOURCE=mirror` reads the organizers' `sapini-clio-data.json`, the exact bodies their setup app sends to Clio. The UI labels this "offline mirror, not live Clio". The demo and judging run on `CLIO_SOURCE=live`.

Scripts: `python scripts/sync.py [--force]` (sync and build from the CLI), `python scripts/run_digest.py` (print the cached digest).

Tests: `cd backend && python -m pytest -q`. They cover the read-only guard, waterfall math, the verifier (including OCR spacing noise) and signing.

## Host it (GitHub Pages + Hugging Face Space)

GitHub Pages serves only static files, so the frontend goes on Pages and the Python backend runs on a free
Hugging Face Space (Docker). The Space URL alone also works: it serves the full app.

1. **Backend:** `HF_TOKEN=hf_xxx APP_PASSWORD=<team password> python scripts/deploy_space.py`. This creates
   `<you>/clearcase` (public Space; code only, never `.env`, keys, the database or PDFs), sets the secrets from your
   `.env` plus `APP_PASSWORD`, your firm signing key and `HF_TOKEN`, and a **private** dataset `<you>/clearcase-state`
   that keeps the database across restarts. The first boot syncs from Clio by itself (about 15 minutes on Groq's free tier).
2. **Frontend:** push this repo to GitHub, then in the repo: Settings → Pages → Source: **GitHub Actions**, and
   Settings → Secrets and variables → Actions → Variables → `CLEARCASE_API_BASE` = the Space URL printed by step 1.
   The workflow `.github/workflows/pages.yml` publishes `frontend/` on every push to `main`.
3. Open `https://<github-user>.github.io/<repo>/`, enter the team password. Provider links look like
   `https://<github-user>.github.io/<repo>/#/p/<token>` and need no password.

**Security when hosted:** with `APP_PASSWORD` set, every attorney route requires a signed session token
(`POST /api/login`); provider links, the firm public key and the Clio OAuth callback stay public. Leave
`APP_PASSWORD` empty only for local use.

**Live provider links:** after every sync (and when the attorney saves or resets the settlement scenario) every live
link is refreshed: changed items are re-signed, items that no longer apply are withdrawn, and new items flow in
for categories the attorney already shared (status, what the firm needs, visits, the office's own bill). The provider
page checks for updates every 30 seconds and shows each change in its "Case movement" feed.

## Honest limits

- **This is signed selective disclosure, not zero-knowledge.** A provider can verify that each shared claim came from the firm unaltered (Ed25519) and was cut from a specific source (`source_hash`, so the firm can later reveal the source and anyone can check it). That gives the practical benefit of ZK sharing: verify a claim without seeing the file. It is not a ZK-SNARK. Range proofs (for example "coverage ≥ your bill") and Merkle inclusion proofs are on the roadmap.
- Fee %, lien reductions and payment order are not in the data, so they are adjustable assumptions. Provider bills may overlap with amounts already paid by no-fault or Medicaid; the waterfall lets the attorney untick lines.
- OCR on low-quality scans can miss text. When the exact quote cannot be located, the viewer opens the right page without a box and says so.
- See [NOTES_FOR_JUDGES.md](NOTES_FOR_JUDGES.md) and [DATA_NOTES.md](DATA_NOTES.md).

## Where data lives

Clio is input only. Everything ClearCase stores lives in its own SQLite file (`clearcase.db`, gitignored): raw Clio responses with fetch timestamps, normalized sources, document pages, facts, digests, share links, signed claims, access log and change events. Downloaded documents and OCR results live in `backend/data/` (gitignored). The firm's signing key lives in `secrets/` (gitignored).

## Repo map

```
backend/app/        main.py (API), clio_client.py (GET-only), clio_auth.py, source.py (live + mirror),
                    ingest.py, documents.py (OCR + highlight locator), llm.py (routing, failover, cache),
                    digest.py (pipeline + cache), waterfall.py, signing.py, sharing.py
backend/app/agents/ extraction, verifier, kpi, stage, priority, timeline (+ injuries), share_policy, code_agents
backend/app/xray/   Case X-Ray: common, contradictions, gaps, evidence_quality (+ injury map), graph, stress_test, service, routes
backend/tests/      read-only guard, waterfall, verifier, signing
frontend/src/       pages (Dashboard, ShareBuilder, ProviderPortal) and components (Snapshot, KpiCards,
                    Waterfall, Tracker, Timeline with time travel, Top10, Attention, ChangesFeed, Injuries,
                    Heatmap, DigDeep, SourceViewer with pdf.js highlight overlay, ProviderView)
scripts/            sync.py, run_digest.py, ocr_documents.py
```
