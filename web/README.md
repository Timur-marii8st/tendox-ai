# S3 internal pilot UI

The operator can upload one PDF/DOCX/XLSX at a time at `/document-upload`.
Separate tender-document and supplier-quote slots bind the server-side document
role before sending the file to `POST /v1/documents`. The page displays the
stored source ID, SHA-256 and extraction status. It does not build a quote or
evaluate a case. The Next.js server action limit is 21 MB to accommodate the
API's 20 MiB file limit plus multipart overhead.

Next.js App Router renders saved procurement cases and calls FastAPI only from
server modules. The bearer token must stay in `PROCUREMENT_API_TOKEN`; never
rename it to a `NEXT_PUBLIC_*` variable.

The human OCR-label review workspace is available at `/ocr-review`. It reads the
AI review JSON and matching DOCX entirely in the browser, verifies both the
document and embedded-media SHA-256 values, and downloads a separate
`HUMAN_CONFIRMED` JSON. Neither source file is uploaded to Next.js or FastAPI.
The two files can be selected in either order; a DOCX selected first is retained
and checked automatically after the review JSON is loaded.

Tenant-scoped document discovery is available at `/document-search`. The route
calls `GET /v1/document-search` only from the server, keeps the bearer token out
of browser JavaScript and URLs, and labels title, filename, native-text, and
vision-tag matches separately. `UNKNOWN` vision suggestions remain visibly
unconfirmed and never become a compliance or participation decision.
Exact brand matches backed by the latest reviewed tenant catalog are labeled as
`MODEL_BRAND_CATALOG` and show the catalog, model-source, and official-source
provenance, including a persisted artifact ID and SHA-256 when available.
AI-suggested model evidence remains `UNKNOWN`.

`/completeness-review` is a separate server-rendered reviewer queue for persisted
document-completeness snapshots. It is deployed only in the internal reviewer
environment, where the existing server-only `PROCUREMENT_API_TOKEN` has the
`COMPLETENESS_REVIEWER` role. The browser never receives the API URL or bearer
token and cannot choose another credential. A terminal decision is immutable and
read-only after it is returned by the API. For `PASS`, the UI requires an explicit
disposition and rationale for every unmapped block; the FastAPI contract remains
authoritative for snapshot/digest binding and all completeness gates.

`/ai-requirement-review` is an isolated server-rendered queue for imported AI
requirement runs. It uses only the dedicated server-side
`PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN`; there is deliberately no fallback to
the operator token. The browser receives sanitized candidates and exact source
evidence, but never receives the bearer token, provider transcript, full extraction,
approval reference, import control, or model-run control. Every candidate needs a
terminal disposition and reason. Incomplete (`execution_status=UNKNOWN`) runs are
read-only. A COMPLETE run with no candidates may be reviewed with an empty decision,
but this never changes completeness from `UNKNOWN`.

```powershell
$env:PROCUREMENT_API_URL = "http://127.0.0.1:8000"
$env:PROCUREMENT_API_TOKEN = "<local bearer secret>"
$env:PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN = "<dedicated reviewer bearer secret>"
$env:PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN = "<dedicated completeness-reviewer bearer secret>"
$env:PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN = "<dedicated requirement-set reviewer bearer secret>"
$env:PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN = "<dedicated server-offer reviewer bearer secret>"
$env:PROCUREMENT_PARTICIPATION_APPROVER_TOKEN = "<dedicated participation approver bearer secret>"
$env:PROCUREMENT_APPLICATION_REVIEWER_TOKEN = "<dedicated application reviewer bearer secret>"
$env:PROCUREMENT_APPLICATION_SUBMISSION_APPROVER_TOKEN = "<dedicated submission approver bearer secret>"
$env:PROCUREMENT_APPLICATION_SUBMISSION_EXECUTOR_TOKEN = "<dedicated submission executor bearer secret>"
$env:PROCUREMENT_DEMO_MODE = "true"
npm install
npm run dev
```

Quality checks:

```powershell
npm run lint
npm run build
```

The pilot has one server-configured tenant and no user sessions. See
`../docs/operations/18-first-screen.md` for the complete boundary.

The `/supplier-discovery` page queries the public EAEU product/manufacturer
collections, one ServerMall HPE Gen12 category, and (for pump queries) the
first page of a public Yandex Market for Business pump category directly.
No search API key is needed. These category previews are narrow; zero matches
say nothing about the rest of either marketplace. Results are transient and
are not saved as case evidence.

## Document-set completeness review

`/document-set-review?manifest_id=<exact-manifest-id>` is a separate internal,
server-rendered reviewer surface. It calls only the exact-evidence endpoints for
that manifest, with the dedicated server-only
`PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN` carrying `COMPLETENESS_REVIEWER`.
There is no manifest list, latest/default selection, case ingestion, operator
token fallback, or browser access to the API URL/bearer credential.

The screen renders the immutable manifest scope/digest, every constituent source
and review/decision digest, source blocks/provenance, mapping facts, and
server-generated findings. A returned terminal decision is read-only.

For an undecided manifest, the UI submits all ordered exact constituent
attestations, inventory/cross-document assessments and rationales. It derives
`PASS` locally only when every displayed gate is closed and there are no server
findings; otherwise it submits `UNKNOWN`. FastAPI remains the authoritative
fail-closed validator. The UI supports `FAIL` only through the two domain-valid
paths: an existing constituent `FAIL`, or a reviewer-selected
`CONFIRMED_MATERIAL_OMISSION`/`CONFIRMED_MISSING_DOCUMENT` bound to one exact
source block from freshly loaded evidence. It never accepts free-text IDs,
mapping paths, server findings, or untyped failure claims.

## Reviewed requirement set: decision and binding

`/requirement-set-review?set_id=<exact-set-id>` is an isolated reviewer route.
It renders all proposal rows, source provenance, typed normalization, manual
scope and the exact proposal digest. It uses only the server-side
`PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN`; there is no operator-token fallback,
queue or latest selection. Assessments and `PASS | FAIL | UNKNOWN` start empty,
and the server action reloads the exact proposal before creating one immutable
decision.

`/requirement-set-binding?set_id=<exact-set-id>` is the operator route. It uses
`PROCUREMENT_API_TOKEN`, accepts an explicit case ID and version, and enables the
binding form only for a persisted terminal `PASS`. The action reloads the set and
compares both proposal and decision digests before calling the existing binding
endpoint. A `PASS` does not resolve `MANUAL_REVIEW_REQUIRED` rows or establish
product compliance.

## Exact server BOM and quote proposal

`/server-offer-proposal` is an operator-only BFF surface. It binds one explicit
case version, requirement-set binding, sourcing run/lead and uploaded
`SUPPLIER_QUOTE` document to an ordered BOM and commercial terms. The API reloads
all referenced resources and supplies the persisted lead identity; the browser
cannot submit a technical verdict or review status.

Every BOM line and the commercial terms require a locator in the exact quote
document. Money and quantities are sent as decimal strings. The result remains
`UNKNOWN / PENDING_REVIEW` and needs an independent proposal-digest review before
it can support product compliance or case economics.
## Independent server-offer review

`/server-offer-review?offer_id=<exact-offer-id>` is an isolated reviewer route
using only `PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN`. It renders the approved
requirement set, exact BOM, commercial terms and provenance together. Every
requirement row gets an explicit verdict, rationale and typed offer evidence;
the API derives the overall result and stores one immutable decision. There is
no queue, latest selection, caller-supplied overall status or operator-token
fallback.
## Exact server-offer economics

`/server-offer-economics?case_id=...&version=...&offer_id=...` uses the operator
token to load one PASS reviewed offer for the exact case version. The server
owns goods cost and VAT from the quote; the form requires all other cost fields
and assumptions for base, realistic and conservative. The immutable result is
complete economics evidence with recommendation still `UNKNOWN`.

Once the package exists, the same screen can create the next immutable case
version through the exact package identity. The API derives the quote, scenarios
and technical evidence; the browser cannot submit an assessment or
recommendation. The resulting case still needs the other five hard gates and
therefore remains `NEEDS_ANALYSIS`.

`/hard-gate-assessment?case_id=...&version=...` completes the next internal
snapshot. Technical evidence is read-only, DOCUMENT is derived from an exact
terminal document-set binding, and the operator supplies the four remaining
decisions with persisted document identities. This creates another immutable
case version; evaluation remains a separate action on the dashboard.

## Independent participation decision

`/participation-approval?evaluation_id=...` reviews one exact persisted
`PARTICIPATE` evaluation with only the server-side
`PROCUREMENT_PARTICIPATION_APPROVER_TOKEN`. The evaluator cannot approve their
own result. Before `APPROVED`, the API reloads the same immutable case and
recalculates it at the current timezone-aware instant. The terminal decision,
audit event, and idempotency receipt are atomic. Every decision stores
`external_action_authorized=false`; submission remains a separate exact-payload
approval workflow.

## Application package proposal

`/application-package?decision_id=...` uses the server-side operator token to
open one exact APPROVED participation decision. The operator enters the price,
ordered document requirements with tender-document provenance, and uploaded
`APPLICATION_ATTACHMENT` document IDs/SHA-256 mapped to those requirements.
Upload the files through `/document-upload` first. The server rechecks the
decision, current case recommendation, deadline, price floor, NMCK, tenant and
exact document roles/digests. The result is immutable and read-only on return,
with `PENDING_REVIEW / UNKNOWN` and no signing or submission authority.

## Independent application package review

`/application-package-review?package_id=...` uses the dedicated server-only
`PROCUREMENT_APPLICATION_REVIEWER_TOKEN` with `APPLICATION_REVIEWER`. It shows
the exact package, extracted source blocks and protected downloads of only
package-linked originals. The reviewer assesses every requirement and file,
the full inventory and the price. Nothing is preselected. The server derives
`PASS | FAIL | UNKNOWN` after recalculating deadline, recommendation and floor.
The terminal decision is read-only and never authorizes submission.

## Exact application submission approval

`/application-submission?package_id=...` uses the OPERATOR token to freeze the
reviewed price, exact attachment IDs/SHA-256 and HTTPS destination in one
immutable internal command. `/application-submission-approval?package_id=...`
uses the dedicated server-only `PROCUREMENT_APPLICATION_SUBMISSION_APPROVER_TOKEN`
with `APPLICATION_SUBMISSION_APPROVER`. It shows the full payload and stores one
independent decision tied to its SHA-256. A positive decision expires after at
most 15 minutes or until the tender deadline or selected quote expiry. These
screens do not sign or submit.

## One-time application admission

`/application-submission-execution?package_id=...` uses the dedicated
server-only `PROCUREMENT_APPLICATION_SUBMISSION_EXECUTOR_TOKEN` with
`APPLICATION_SUBMISSION_EXECUTOR`. It displays the approved exact command and
can permanently claim it once after the server rechecks current gates and
hashes every original attachment. The resulting `ADMITTED_NO_DISPATCH` record
is auditable and read-only. This action does not sign or send an application.

## Manufacturer search and independent review

`/manufacturer-search` saves a bounded EAEU PRODUCTS response and shows the
source-declared manufacturer with field provenance. A saved record links to
`/manufacturer-review?run=<run-id>&record=<record-id>` for an operator's PDF
evidence and proposed legal identity. The independent reviewer uses
`PROCUREMENT_MANUFACTURER_REVIEWER_TOKEN` with `MANUFACTURER_REVIEWER`; there is
no operator-token fallback. Configure this server-only token on the protected
reviewer deployment. Protect the deployment with authentication, as with the
other internal review surfaces; possession of a page URL is not authentication.

The reviewer must inspect the original PDF and claimed source metadata, select
the supported claims, confirm identity and the exact registry product, and set
a future expiry. The proposer and evidence uploader cannot approve their own
work. The terminal decision remains immutable. Its scope is identity and role;
technical fit, seller, availability, price and a valid quote remain unconfirmed.

`/manufacturer-search` also shows the exact identity groups for its retained
records. An eligible record links to `/manufacturer-rfq?proposal=<proposal-id>`.
The server rechecks current evidence before storing an immutable internal TXT
draft. Quantity, unit, requirements and delivery remain operator-entered facts
with provenance. Saved drafts use `/manufacturer-rfq?draft=<draft-id>` and a
protected server-side text download. A stale draft remains historical and
read-only, with current applicability shown separately. These routes do not
choose a contact, send a message or calculate quote economics.
