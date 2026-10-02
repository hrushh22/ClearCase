# What the Sapini data actually looks like

Inspected 2026-10-02 from `Sapini Case Materials/` (read-only, never modified).

## sapini-clio-data.json

Not an export. It is the list of **Clio API v4 request bodies** the organizers' setup app sends to
build the matter (`about.request_shape`: every body goes inside `{"data": ...}`). Placeholders like
`{{contact:client}}`, `{{matter_id}}`, `{{field:Date of Incident}}` stand in for Clio ids that only
exist once the matter is created. Dates are resolved for Friday 2026-10-02.

Top-level sections and counts (they match the manual setup guide):

| Section | Count | Notes |
|---|---|---|
| matter_stages | 8 names | Intake, Treatment, Demand, Negotiation, Litigation, Trial, Disbursement, Closed. Created by hand in Clio (API refuses writes). Sapini is at **Litigation**. |
| custom_fields | 16 | Matter-level. Includes Estimated Case Value (currency 375,000), Medical Specials To Date (118,400), Policy Limits (text), Insurance Carrier, Health Insurance or Lien Holder, Prior Related Injuries, Treatment Status. |
| contacts | 10 | Client Justin Sapini, adverse driver Anthony Ferrara, Metro-North, Claims Service Bureau, Progressive, Montefiore Nyack, McCulloch Ortho, Dr. Capiola, Advanced Rockland Chiro, SportsCare PT. |
| matter | 1 | "Sapini, Justin - MVA (Cedar St & Garden St, New Rochelle)", open 2023-05-07, SOL 2026-04-22. No responsible attorney in the bodies (Clio fills the account owner). |
| relationships | 9 | Each contact's role ("Adverse party, self-insured public authority", "Treating provider, physical therapy", ...). |
| folders | 9 | 01 to 09. 07 Insurance and 09 Settlement are empty. |
| documents | 15 | Each has `local_path`, `bytes`, `sha256`, `received_at`. |
| notes | 42 | Not in date order. Rich narrative: coverage, mechanism contradictions, prior injury discrepancy, specials tally, lien, case evaluation. |
| communications | 69 | EmailCommunication / PhoneCommunication with senders/receivers (contact or firm user). |
| tasks | 14 | 7 pending, 7 complete; three are "By medical provider: ..." requests. SOL task flagged `statute_of_limitations: true`. |
| calendar_entries | 17 | Past events (surgery, IMEs) and upcoming (Oct 2026 treatment visits, calls, file review). |
| expenses | 5 | ExpenseEntry, total $1,410 (records copies, IME observer, filing fee). |

## Facts that matter for the build

* **Coverage is not a single number.** Metro-North is a *self-insured public authority* (no policy, no
  declarations page; folder 07 stays empty). The driver Ferrara personally carries $100,000 / $300,000,
  confirmed in writing by the adjuster on 2026-09-08 (note "Coverage confirmed in writing", emails 43 and 65).
  Client UM/UIM $25k/$50k adds nothing. No-fault $50,000 exhausted. The KPI must say exactly this.
* **Case value** $375,000 (custom field + note "Case evaluation" 2026-06-04) is above the $100,000 practical cap.
* **Medical specials** $118,400 broken down by 8 providers in note "Specials tally to date" (2024-02-17).
  Chiro and PT ledgers are unreconciled; two providers sent nothing.
* **Medicaid lien** $22,180 asserted (notes, email 69, task 14).
* **Wage loss** claimed $214,000.
* **Open problems**: right shoulder surgery recommended, no date despite three requests; discovery stuck on
  maintenance records; client gave three accounts of the mechanism; prior ankle injury contradicts his denial.
* **Last client contact**: phone call 2026-09-27 ("should he keep going to PT").

## Documents (15 PDFs, ~660 pages)

| Folder | File | Pages | Kind |
|---|---|---|---|
| 01 Intake | hipaa-authorization | 1 | text |
| 01 Intake | photo-id | 1 | **scan** (image only) - used for the client picture |
| 02 Pleadings | summons-complaint | 8 | **scan** |
| 02 Pleadings | verified-answer-demands | 27 | text layer over images |
| 02 Pleadings | bill-of-particulars | 14 | text |
| 02 Pleadings | bop-affirmative-defenses | 3 | text |
| 03 Discovery | response-discovery-demands, defendants-response-demand, subpoena | 10/11/2 | text |
| 04 Medical Records | records-bundle-part1-haggerty-imaging | **250** | **scan**, 42 MB |
| 05 Medical Bills | records-and-bills-part2-pt-ortho-er-operative | **262** | **scan**, 34 MB |
| 06 Correspondence | letter-to-judge | 1 | **scan** |
| 08 Experts | radiology-review, neuro expert exchange, ortho IME | 10/47/15 | text |

About 520 pages need OCR. RapidOCR (ONNX, local) takes ~3.5 s/page on this laptop; results are cached
by file SHA-256. OCR drops spaces ("Noevidenceofacutedisplaced"), so highlight matching compares
letters and digits only.

## LDG Hackathon slides

Rules: read Sapini live from our own Clio account, never write to Clio, no hardcoded features, own DB
outside Clio. Submission asks for models used and approximate cost per case.
