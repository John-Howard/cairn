# Cairn — Information Asset Register (IAR) Plan

**Status:** v0.1 — for iteration. Durations and resourcing deferred, consistent with Project Plan v0.3.
**Build status (2026-07-30): all three slices (§7) are built** — 2g/2h (2026-07-27): migration `538c7c1b29ab`, the `/assets` module, activity-from-asset, rules 22–23, dashboard KPIs, asset CSV import and filtered IAR export. 2i (2026-07-30): the `question_set` generalisation, the `/intake/assets` wizard producing proposed `InformationAsset` records against the *IAR Question Set v0.1* (`Cairn-iar-questions.md`), and gaps-queue/asset-detail curation surfacing — closing backlog item 25 (`Cairn-2i-asset-intake-plan.md`). All three information-asset capture routes (manual, CSV import, intake) are now complete.
**Origin:** pre-beta discussions (2026-07) identified the need for an Information Asset Register — physical and digital assets, databases, software and paper files — alongside the ROPA, linked to ROPA records, with IAR data feeding and populating the ROPA, and with its own presentation and data-capture interface.
**Decisions recorded (2026-07):**

1. The IAR is a **module inside Cairn** — its own navigation section, register views and forms in the same application and database. Not a separate application; no sync layer.
2. Scope is **all information assets**, not only those holding personal data. Assets holding personal data link to ROPA activities; others stand alone, serving wider information-governance and records-management duties.
3. The organisation follows the **SIRO / Information Asset Owner model**: each asset carries a named IAO and optional custodian, with IAO-facing views and review responsibilities.
4. Capture is by **all three routes**: manual entry screens (IG/ICT curators), CSV bulk import (existing spreadsheets / CMDB extracts via the shared import pattern), and a guided intake-style wizard for asset owners.

**Derives from:** *Spec v0.4* §4 (System/Asset), §5 (`activity_system`), §8 rule 15; *Plan v0.12* §3.9 (security/retention split); *Integration Architecture v0.1* interface 3 (asset register / CMDB inbound); *Intake & Pilot Plan v0.1* (intake-in-Cairn precedent).

---

## 1. Core design decision: promote System/Asset, don't parallel it

Cairn already has the seed of an IAR. `SystemAsset` (`src/cairn/models/vocab.py`) is the entity ROPA activities link to via `activity_system`; security measures **inherit** from it into activities (`src/cairn/inheritance.py`, spec rule 15); it carries a default retention suggestion, hosting country and the s62 logging flag. The Integration Architecture already designates it the landing point for asset-register/CMDB imports (interface 3).

**The IAR is therefore built by promoting `SystemAsset` into a first-class `InformationAsset` entity** — richer fields, its own module and screens — *not* by creating a parallel register that would need reconciling with it. One record is both the IAR entry and the thing ROPA links to, so "IAR data feeds and populates the ROPA" holds structurally:

- security measures recorded on the asset flow into linked activities automatically (existing inheritance);
- the asset's default retention pre-fills activity retention (existing);
- hosting country informs transfer prompting (existing field, coupling built in §5);
- new activities can be started *from* an asset, pre-linked and pre-populated (§5).

This mirrors the intake decision: no intermediate capture tool, no capture-then-migrate. The register *is* the model.

**What changes physically:** the `system_asset` table is renamed `information_asset` (and `activity_system` → `activity_asset`, `system_securitymeasure` → `asset_securitymeasure`) in one forward-only Alembic migration, before beta data accumulates. Existing rows, FKs and seeded FRS systems are preserved; they become assets of type `system`.

---

## 2. The Information Asset entity

Extends the current six fields. New enums in `models/enums.py`; entity stays `Proposable` (intake and imports create `proposed` entries for curator approval, as today).

| Field | Type | Notes |
|-------|------|-------|
| `label` | text, required | *(existing)* |
| `asset_type` | enum, required | `system` (digital system/service), `database`, `software` (application), `paper` (paper files/records), `physical` (information-bearing physical media/equipment) |
| `description` | textarea | what the asset is and what information it holds, in plain English |
| `iao_user_id` | fk → User | Information Asset Owner (decision 3). Nullable — "no IAO" is a surfaced gap, not a blocked save |
| `custodian` | text | day-to-day custodian (person/team); free text, not forced to a user account |
| `business_functions` | fk[] junction | owning functions — one or more (multi-function requirement recorded 2026-07-28); drives function-scoped views |
| `classification` | enum | Government Security Classifications: `official`, `official_sensitive` (+ `not_classified`). Values seeded, extensible per pack |
| `contains_personal_data` | bool, default false | the ROPA coupling switch — drives rules 22/23 (§5) |
| `status` | enum | `in_use`, `retiring`, `disposed` — asset lifecycle, distinct from any linked activity's `lifecycle_stage` (same separation principle as `record_status` vs `lifecycle_stage`) |
| `next_review_date` | date | IAO review cadence; overdue surfaces on the dashboard |
| `supplier_entity_id` | fk → LegalEntity | supplier/hosting provider where externally provided |
| `owner` | text | *(existing — kept for migration; superseded by `iao_user_id`, retired in a later cleanup once IAOs are assigned)* |
| `location` | text | *(existing)* physical location or hosting description |
| `hosting_country` | text | *(existing)* |
| `default_retention_id` | fk → RetentionRule | *(existing)* |
| `s62_logging_in_scope` | bool | *(existing)* |
| `security_measures` | fk[] junction | *(existing)* — the source of activity security inheritance |
| `notes` | textarea | |

Standard implicit fields (id, audit, `version`, `change_note`) apply per Spec §1.2. Versioning and audit events cover asset edits exactly as for other audited entities.

**Deliberately deferred (revisit after pilot):** asset hierarchy (`parent_asset_id`, e.g. database-on-system, file-series-in-location); volume/record-count metrics; a distinct IAO role in RBAC (v1 maps IAOs to existing accounts — see §4).

---

## 3. Presentation: the IAR module

New module `src/cairn/assets.py` + `templates/assets/`, following the register/CRUD conventions of `registers.py`. **System/Asset moves out of the generic vocabulary admin** (`systems` key removed from `VOCABULARIES`; vocabulary index links across to the IAR) — the generic vocab form can't carry the junction editor, linked-activity view or filters the IAR needs.

- **`/assets` — the register.** Filterable list: asset type, business function, IAO, classification, `contains_personal_data`, status, review-overdue. Column set kept scannable; CSV export of the filtered view (§6).
- **`/assets/{id}` — asset detail.** Full record plus: linked security measures (junction editor, as activity junction editors), linked ROPA activities (reverse of `activity_asset`) with each activity's status, gap flags (no IAO, personal data but no linked activity, review overdue), and a **"Document processing on this asset"** action (§5).
- **Create/edit forms** with the standard validation/error-summary pattern; propose-and-approve retained — contributor-created or intake-created assets arrive `proposed`, curators approve.
- **"My assets" view** for IAOs: assets where `iao_user_id` is the signed-in user, with review-due prompts — the IAO-facing slice of decision 3.
- **RBAC:** reuse the existing four-role matrix — curators/DPO author and approve; contributors propose and see; IAO views work through the contributor role. No new role in v1; noted as an open question (§9).

---

## 4. Feeding the ROPA (the coupling layer)

Existing machinery already carries asset→activity flow (inheritance, retention default). Added on top:

- **Activity-from-asset.** From an asset's detail page, start a draft Processing Activity pre-linked via `activity_asset`, with security inherited, retention defaulted from the asset, and function pre-set from the asset's business function. This is the audit-workflow bridge: inventory first, then document the processing on each personal-data asset.
- **New engine rules** (continuing ids after 21, `[cairn governance]` tier):
  - **Rule 22 (WARN):** asset has `contains_personal_data` and is approved/in use, but no linked activity — undocumented processing candidate; the IAR-driven audit signal.
  - **Rule 23 (WARN):** active activity has data categories but no linked asset — the ROPA-side converse; every documented processing should name where the information lives.
  - **Rule 24 (BLOCK, added 2026-07-31):** asset references reference data that is not approved — its supplier Legal Entity or a linked Security Measure sitting at `proposed`/`rejected`. The asset-side analogue of rule 18, enforced on asset approval; the CSV import evaluates the same rule per row and creates a row referencing unapproved reference data as `proposed` rather than approved, so it goes through the asset approval queue instead of bypassing it. The gap-flag surfacing applies to an asset that became unapproved-referencing after it was already approved.
- **Dashboard KPIs:** assets by type; personal-data assets without a linked activity (rule 22 count); assets without an IAO; reviews overdue.
- **Intake linkage:** the existing activity-intake wizard's systems question (H1) proposes into the same entity, so wizard-named systems and IAR records converge on one list — no change needed beyond renames.

---

## 5. Capture routes (decision 4)

1. **Manual entry** — the §3 forms; available from IAR-1.
2. **CSV bulk import** — extends the shared import pattern (`imports.py`: upload → analyse → preview → confirm, per-row reports, unmatched values become proposals). New import type `assets` with column mapping for the §2 fields; unmatched IAO names and business functions surface as row warnings rather than silent drops. This delivers Integration Architecture interface 3's v1 mechanism.
3. **Guided asset intake wizard** — an intake-style, jargon-free question set ("What information does your team keep? Where does it live? Who looks after it? Is anything on paper?") producing `proposed` assets and `IntakeGap` records for don't-knows, reusing the existing gaps queue. **Prerequisite:** the intake tables gain a `question_set` discriminator (`activity` | `asset`) on `IntakeQuestion`/`IntakeSubmission` — today the model assumes a single set. This generalisation also serves the backlog's question-reseed item and future Question Set v0.2. The asset question set becomes a new document (*Cairn IAR Question Set v0.1*) with per-question "Populates" mappings, mirroring the information-audit set.

---

## 6. Exports

IAR export follows the mapping-layer principle (Spec §10): a configurable CSV view over `information_asset` (filtered register download plus a full-register export from the exports screen). Art 30(1)/30(2)/s61 exports are unchanged — the IAR is not an ICO artefact and never shapes stored ROPA data.

---

## 7. Build slices

Sequenced as **sub-phases 2g–2i** (extending the Phase 2 convention; Project Plan v0.4 to record them). Each slice lands independently with migrations, tests and docs, per the established per-slice rhythm.

| Slice | Contents | Depends on |
|-------|----------|-----------|
| **2g — IAR core** | Migration (rename + new fields/enums); `assets.py` module: register, detail, CRUD, junction editor, filters, "my assets"; nav; removal from vocab admin; RBAC wiring; tests | — |
| **2h — ROPA coupling + import** | Activity-from-asset; rules 22–23; dashboard KPIs; asset CSV import; register/CSV exports | 2g |
| **2i — asset intake** | `question_set` generalisation; IAR question set doc + seed; asset intake wizard + gaps integration | 2g (2h independent) |

**Pilot fit:** 2g–2h before the beta gives pilot functions an asset inventory step ahead of (or alongside) activity intake — P1 seeding checklist gains an "load initial asset list" step (CSV import of the ICT application list is the natural first load). 2i can follow during rollout waves.

---

## 8. Impact on existing documents

| Document | Change |
|----------|--------|
| Spec (→ v0.5) | §4 System/Asset superseded by §2 here; junction renames; rules 22–23 |
| Project Plan (→ v0.4) | Sub-phases 2g–2i; Phase 4 audit gains the inventory-first step |
| Integration Architecture | Interface 3 delivered by 2h (CSV); scheduled CMDB sync remains future |
| Security Architecture | IAR screens under existing RBAC matrix; note IAO access route |
| Backlog | Add 2g–2i; link `question_set` work to the reseed item |
| Product description / admin reference | New module description; import type; seeding step |

---

## 9. Out of scope and open questions

**Out of scope for v1:** live CMDB synchronisation (file import only); ITAM/hardware inventory concerns (the IAR records information-bearing assets, not the device estate); asset-level risk scoring; document/records-management functions beyond the register itself.

**Open questions for the DPO/SIRO:**

1. Classification scheme — confirm Government Security Classifications tiers suffice (any legacy PROTECT/RESTRICTED data to map?).
2. Does the IAO community need its own RBAC role (distinct from contributor) once "my assets" is in use?
3. Asset hierarchy — did the pilot surface real parent/child needs (database-on-system, file-series), or does flat + description suffice?
4. Review cadence policy — single org-wide default for `next_review_date` prompting, or per-classification?
