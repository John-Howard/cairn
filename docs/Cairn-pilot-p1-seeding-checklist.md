# Cairn — Pilot Stage P1: Seeding Checklist

**Status:** v0.1. Operationalises stage **P1** of the *Intake & Information Audit Pilot Plan* §5 ("Seed vocabularies + Organisation Profile; load question set as config → **intake-ready instance**"), against the system as built. Work through it top to bottom; the sign-off block at the end defines "intake-ready".
**Owners:** DPO (decisions, sign-off) · IG lead (content, users) · ICT (instance, systems).
**References:** `admin-reference.md` (deploy §2–§4, SSO §5) · Spec §7 (seed vocabularies) · `Cairn-information-audit-questions.md` (activity question set) · `Cairn-iar-questions.md` (asset question set) · `Cairn-intake-pilot-plan.md` (pipeline and pilot stages).

Much of P1 is automated: first-run `/setup` seeds the legal vocabularies, the FRS pack and **both** intake question sets — activity and asset — in one step. The human work is **verifying content, making the decisions the seeds can't make, and pre-creating what the pack deliberately leaves empty.**

---

## A. Decisions and verification before the instance (DPO / IG lead)

- [ ] **A1 — Legislation currency check (Spec §11).** The seed vocabularies are marked *draft — verify against latest revised legislation before production seeding*. Confirm against the current revised texts, including DUAA commencement state: Art 6 bases (7 seeded), Art 9 conditions (10), Schedule 1 conditions (36), s35 bases (2), Schedule 8 conditions (9), transfer mechanisms (5). Record the check as a file note; this is the Phase 0 carry-over.
- [ ] **A2 — FRS pack content review.** Review the pack lists in `src/cairn/seeds/frs.py` against the service's actual structure: 16 business functions, 19 data-subject categories, 16 personal-data categories, 17 recipients, 18 security measures. Confirm the two pilot functions exist under the names respondents will recognise (**Prevention & Community Safety**, **HR**). Wording changes are cheap now and expensive after activities link to them.
- [ ] **A3 — Question-set version.** The intake wizard seeds **two** question sets at setup: the activity Question Set v0.1 (51 questions, sections B–K) and the asset *IAR Question Set v0.1* (15 questions, sections A–F, `Cairn-iar-questions.md`). Confirm the wording the IG team signed off is what's going in for both; post-setup edits are configuration (database), not code, but P2's dry-run is the intended wording-fix point. **The asset set is not signed off yet:** its AS-B2 wording ("the senior person responsible for it", the plain-English rendering of Information Asset Owner) is provisional pending SIRO/IG confirmation of house terminology — settle it here, before respondents see it.
- [ ] **A4 — Organisation Profile values.** Agree before setup (they are entered once): organisation name; org type **public authority** (guards on); legal-entity topology; applicable regimes — include **law enforcement** so Part 3 machinery is available; active modules (recommend all: DPIA, contracts, assets, external data, complaints is always on).
- [ ] **A5 — Part 3 boundary decision (Plan §1.6).** Decide, with written rationale, the regime treatment per enforcement domain: fire safety enforcement, fire investigation, firesetter intervention → Part 3 law-enforcement or Part 2 + Art 10. This is the DPO's call; it is entered in B4 and is reversible per activity without data loss, but the default should be deliberate.

## B. Standing up and configuring the instance (ICT, then DPO in-app)

- [ ] **B1 — Deploy and migrate.** Pilot instance per `admin-reference.md` §3 (compose stack) — or §2 dev instance for the P2 dry-run only. `alembic upgrade head`, then `GET /healthz` returns the expected version.
- [ ] **B2 — Authentication.** Staging: SSO per `admin-reference.md` §5 (app registration, `AUTH_MODE=oidc`, emails provisioned — do the DPO first). A dev-auth instance must stay on a trusted network.
- [ ] **B3 — Run `/setup`** with the A4 values, DPO name **and email**. This single step creates the Organisation Profile, seeds legal + FRS vocabularies and both question sets, and signs the DPO in.
- [ ] **B4 — Regime Policy.** At `/regime-policy`, enter the A5 decisions with their rationale (each is an audited event).
- [ ] **B5 — Users.** At `/users`: IG curators (curator role), any second approver, and the pilot contributors for Prevention & Community Safety and HR — each contributor with their **business function** (it scopes their intake) and **email** (it is their SSO identity).

## C. Pre-creating what the pack leaves empty (IG lead / ICT)

The FRS pack deliberately ships no systems, retention rules, legal entities or external-data sources — they are organisation-specific. Pre-creating the obvious ones keeps pilot proposals manageable and makes security inheritance work from the first intake.

- [ ] **C1 — Information assets.** Assets have their own register and **three** capture routes: manual entry, CSV bulk import (`/imports/assets/new`, Excel-ready template — the natural route for a known list like the ICT application register), and the asset intake wizard (`/intake/assets/new`, §D below). Load the systems the two pilot functions actually use (case-management, HR/payroll, HFSV mobile app, shared drives if they are de-facto systems) at `/assets`, each with an Information Asset Owner, custodian, classification and **security measures** — activity intake links to these assets and inherits security from them (rule 15).
- [ ] **C2 — Retention rules.** Create the service's standard retention schedule entries for the pilot functions (period, trigger, legal driver, disposal method). Retention answers arrive as free text in intake (H3–H6); curators need real rules to link during curation.
- [ ] **C3 — Legal entities.** Create at minimum the own-organisation entity (fire authority / CFO as controller) and the DPO; add known partner agencies and processors as encountered.
- [ ] **C4 — External data sources.** Pre-create the known ones (CACI Acorn, County Council Adult Care) so F2 answers match instead of proposing duplicates.
- [ ] **C5 — (Optional, recommended) pre-fill known activities.** Question Set §3: create draft activities for the processing IG already knows about in the two pilot functions, so respondents *correct* rather than *create*. Lower barrier, better data.

## D. Verify intake-readiness (IG lead)

- [ ] **D1 — Vocabulary spot-check.** `/vocabularies` shows the A2 counts (16/19/16/17/18) plus the C2–C4 entries (retention rules, legal entities, external data sources); `/assets` shows the C1 pre-created assets; nothing in *proposed* state yet.
- [ ] **D2 — Both question sets seeded.** `intake_question` has rows for **both** sets: activity (51 questions, sections B–K) and asset (15 questions, sections A–F, per *Cairn IAR Question Set v0.1* / `Cairn-iar-questions.md`). `seed_frs_pack` now seeds both at `/setup`, but it only runs once — any instance seeded **before slice 2i.2** will show activity rows and zero asset rows. Check `select count(*) from intake_question where question_set = 'asset'`; if zero, backfill with a one-off `seed_asset_questions(session)` call (safe and additive, a no-op if rows already exist — backlog item 7).
- [ ] **D3 — Activity wizard walk-through (mechanical, not the P2 dry-run).** Start an intake as a Prevention contributor: sections B–J render, **no section K**; as a Protection/Fire Investigation user: **section K renders**. Vocabulary questions (D1, E1/E2, F2, G1, H1) list the seeded and pre-created entries; a "don't know" survives to the review page.
- [ ] **D4 — Asset wizard walk-through.** Start an asset intake at `/intake/assets/new`: sections A–F render, no further sections; the security-measures question (AS-E1) lists the seeded and C1 pre-created measures; a "don't know" survives to the review page.
- [ ] **D5 — Activity pipeline round-trip.** Submit one throwaway intake with a "don't know" and a proposed value: draft activity appears with junction links; the proposal sits in `/vocabularies` for approval; the gap appears at `/intake/gaps`; resolve it with a note; then retire/delete the throwaway before P3.
- [ ] **D6 — Asset pipeline round-trip.** Submit one throwaway asset intake with a "don't know" and a proposed security measure: a proposed `InformationAsset` appears at `/assets`, the new measure sits in `/vocabularies` for approval, and the gap appears at `/intake/gaps`; resolve it with a note; then reject/discard the throwaway asset before P3.
- [ ] **D7 — Baseline backup.** Take the first backup of the seeded instance (`admin-reference.md` §6) — the clean restore point for the pilot.

## Sign-off — "intake-ready instance"

| Check | Owner | Date | Initials |
|---|---|---|---|
| A1 legislation currency confirmed | DPO | | |
| A2–A3 pack + question set content confirmed | IG lead | | |
| A4–A5 profile values and regime rationale agreed | DPO | | |
| B1–B5 instance up, auth working, policy + users entered | ICT / DPO | | |
| C1–C4 assets, retention, entities, sources pre-created | IG lead / ICT | | |
| D1–D2 vocabulary spot-check and both question sets confirmed seeded | IG lead | | |
| D3–D4 activity and asset wizard walk-throughs passed | IG lead | | |
| D5–D6 activity and asset pipeline round-trips passed | IG lead | | |
| D7 baseline backup taken | IG lead | | |

When every row is signed, P1 is complete → proceed to **P2** (IG team dry-run as respondents, wording/flow fixes) per the Intake & Pilot Plan.

---

*P1 Seeding Checklist v0.1 — will iterate with the question set after the P5 retrospective.*
