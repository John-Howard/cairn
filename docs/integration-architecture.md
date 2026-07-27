# Cairn — Integration Architecture

**Status:** Integration Architecture v0.1 — the Phase 1.4 deliverable (Project Plan §4). Defines how Cairn connects to the world around it: what integrates, in which direction, by what mechanism, and — as importantly — what deliberately does *not* integrate.
**Derives from:** Solution Architecture v0.1 (FastAPI gives a JSON surface when justified), Security Architecture v0.1 (every interface authenticated and audited), Plan v0.12 §3.6/§6.2, Spec v0.4 §10.

---

## 1. Governing principle

Cairn **documents processing; it does not process the documented data**. Most "integrations" are therefore records *about* arrangements, not data feeds — and the architecture resists turning an accountability register into a data hub. v1 interfaces are deliberately few and mostly file-based; machine interfaces are added per integration only when a real consumer exists.

Three rules apply to every interface, present or future:

1. **Imports create drafts, never active records** — everything lands in the propose-and-approve workflow (Plan §5.1), preserving reference-data governance.
2. **Machine interfaces are authenticated and audited** exactly like UI actions (same `AuditEvent` trail, same actor requirement).
3. **No system touches the database directly** — the application is the only client; other systems get exports or (later) read-only API views.

## 2. Integration inventory

| # | Integration | Direction | v1 mechanism | Future option | Sub-phase |
|---|-------------|-----------|--------------|---------------|-----------|
| 1 | Identity provider (SSO) | inbound auth | OIDC, Authorization Code + PKCE — implemented (`src/cairn/oidc.py`; Entra ID confirmed; Security Architecture §2, Admin Reference §5) | — | done |
| 2 | External Data Sources (Acorn, Adult Care, NHS…) | none — records only | Curated `ExternalDataSource` entries; the datasets themselves **never enter Cairn** | none intended | done (1.2) |
| 3 | Asset register / CMDB | inbound reference | IAR module (`/assets`, `InformationAsset`) — manual curation by IG/ICT plus **CSV import — implemented** (upload → preview → confirm; unmatched IAOs/functions become row warnings; `Cairn-iar-plan.md` §5) | scheduled sync if the estate has an authoritative CMDB | done (2h) |
| 4 | Privacy notices | outbound by reference | `PrivacyNotice` holds version/date/ref; notice text lives where published (org website) | link-checker on published URLs | 2c |
| 5 | Complaints intake (DUAA s164A) | inbound | Manual entry by IG team from the org's existing channels (web form, email); `received_at` starts the 30-day clock regardless of channel | minimal authenticated intake endpoint the org's public web form posts to | 2f |
| 6 | Questionnaire ingestion | inbound | **In-app intake wizard** (primary — the question set is seeded configuration; each run creates a draft activity with junction links, vocabulary proposals and "don't know" gap records worked through at `/intake/gaps`); **mapped CSV import** retained for bulk/offline capture | direct form integration if volume justifies it | 2d |
| 7 | ICO / assurance exports | outbound | On-demand generated files (CSV/XLSX) from the mapping layer — Art 30(1), Art 30(2), s61, combined views | PDF rendering; read-only JSON API for BI tooling | 2e |
| 8 | Notifications (overdue review, trial expiry, complaint acknowledgement due) | outbound | Estate SMTP relay; email is advisory — the dashboard is authoritative | Teams/webhook connector | 2e |
| 9 | ROPA migration (Phase 4) | one-off inbound | Spreadsheet → mapped import through #6's CSV path; reconciliation against audit-derived records (Project Plan v0.2 Phase 4) | — | Phase 4 |

## 3. The two integrations that need design care

### 3.1 Export / mapping layer (Plan §6.2, Spec §10)

The one interface that is core product, not plumbing. Confirmed shape:

- **Mappings are configuration, not schema** — each export view is a declarative mapping over the canonical model; an ICO template change is a mapping edit.
- **The active regime and `controller_or_processor` select view membership** (`export.py` already implements the filters); the mapping layer adds column composition and file rendering at 2e.
- Every export generation is an `AuditEvent` (who exported which view, when) — an assurance artefact in itself.

### 3.2 Complaints intake (statutory, 19 June 2026)

The DUAA requires an easy electronic complaints route, but **it does not require Cairn to be that route**. v1 keeps the public-facing form on the organisation's website (existing, accessible, already assured) with IG entering records; the 30-day acknowledgement clock is tracked from `received_at`. If the future intake endpoint is built (2f), it is: unauthenticated *submission* but rate-limited and estate-fronted, creating draft complaint records only, with no read access — the narrowest possible public surface.

## 4. Import pattern (shared by #3, #6, #9)

One implementation, reused: upload file → validate against vocabularies → **preview with per-row errors** → curator confirms → draft records created with `created_by` = importing user and a batch `AuditEvent`. Unmatched reference values become *proposals*, not silent new entries — the hybrid-model governance risk (Plan §5.1) is handled at the import boundary too.

## 5. Explicit non-integrations

- **No live feeds from external data suppliers** — recording the arrangement is the product; ingesting the data would put Cairn inside the processing it documents (scope, DPIA and security posture would all change).
- **No SAR/rights case management** — out of scope by design (Plan, *Scope boundary*).
- **No write access for any external system** — inbound is file-import or the narrow complaints endpoint only.

---

*Integration Architecture v0.1. Interface detail (import formats, export column mappings) is specified with the owning sub-phases (2c–2f).*
