# Cairn — Retrospective, Known Gaps & Future Enhancements

**Status:** v0.1, 2026-07-17. Written at the completion of the pre-deployment build (intake, gaps curation, OIDC SSO) as the forward-looking record: what stands, what is knowingly missing, and what should come next. Review and re-prioritise at the P5 pilot retrospective and again before go-live.
**Relates to:** Project Plan v0.2 (phase framing), `admin-reference.md` §7 (operational gaps), Intake & Pilot Plan (pilot stages).

---

## 1. Where we are

Phases 1–2 complete and extended: the full application (2a–2f) plus the pulled-forward pilot enablers. Delivered in the July 2026 build cycle (PRs #2–#10):

| Delivered | Substance |
|---|---|
| Intake wizard | Information-audit question set (51 questions, B–K) as seeded configuration; each run creates a draft activity with junction links; propose-and-approve at source; "don't know" → gap records; Section K conditional on enforcement functions |
| Gaps curation | `/intake/gaps` queue; audited resolve (note required) / reopen |
| OIDC SSO | Authorization Code + PKCE against Entra ID; deny-by-default mapping (email first login → audited subject binding); startup config validation; secure cookies |
| Pilot runway | P1 seeding checklist, P2 dry-run script, communications pack — each linked from the pilot plan's stage table |
| Documentation | All architecture docs, admin reference (incl. §5 SSO runbook), product descriptions and doc indexes audited current |
| Security hardening (added post-retrospective, PRs #12–#14) | Session lifetime enforcement (12h absolute / 60m idle), JSON structured logging with security events, RBAC denial + logout auditing, healthz DB-reachability check, RP-initiated logout to the IdP |

Test suite 294 passing; CI green throughout. **Remaining work before go-live is operational (staging stand-up, pilot execution) and assurance (Phase 3) — plus the items below.**

**Addendum (2026-07-27):** the Information Asset Register slices **2g (IAR core) and 2h (ROPA coupling, CSV import, IAR export)** from the IAR plan (`Cairn-iar-plan.md`) are built — `SystemAsset` promoted to `InformationAsset` (migration `538c7c1b29ab`), the `/assets` module, rules 22–23, dashboard asset KPIs, the asset CSV import and the filtered IAR export. Suite 337 passing. Slice **2i (asset intake wizard)** is deferred — see item 25.

## 2. Gaps to close before or during staging *(ordered by risk)*

1. ~~**Session lifetime not enforced.**~~ **Done (2026-07-17):** idle timeout via rolling cookie `max_age` (`SESSION_IDLE_SECONDS`, default 60m); absolute lifetime via `auth_at` stamp checked in `current_user` (`SESSION_ABSOLUTE_SECONDS`, default 12h). Pre-existing sessions are invalidated on deploy (one-off re-login).
2. ~~**No RP-initiated logout.**~~ **Done (2026-07-17):** sign-out clears Cairn's session then redirects to the IdP's end-session endpoint (discovery-derived, with Entra `logout_hint`) and back to `/login`; local-only fallback if the IdP is unreachable. Requires the post-logout redirect URI in the app registration (admin ref §5.1).
3. ~~**RBAC denials are not audited.**~~ **Done (2026-07-17):** `require_role` failures write an `authorisation_denied` AuditEvent (path, required/actual roles) plus a structured security-log line; logout is audited too.
4. ~~**JSON structured logging.**~~ **Done (2026-07-17):** `src/cairn/logs.py` — JSON lines to stdout including uvicorn's loggers (`LOG_FORMAT`, default json outside dev); security events (`cairn.security`) carry structured fields, no personal data.
5. **Real Entra round-trip untested.** Everything up to the token exchange is exercised with a mocked IdP; the first staging deployment must include an explicit SSO verification step (admin ref §5.2.4) before users are invited.
6. **Cairn's own DPIA needs updating before real data.** The tool now processes more personal data than when the DPIA was scoped: user emails and IdP subjects, intake respondent contact details, free-text intake answers (which will contain incidental personal information). Phase 3 cross-cutting item; the delta is known and small — do it deliberately.
7. **Environments seeded before the intake wizard existed are missing `intake_question` rows.** `seed_frs_pack` only runs once, from the org setup wizard (`src/cairn/setup.py`) — it is not re-run on deploy. Any database seeded before the 2d intake-wizard slice (PR #2) has business functions, vocabularies etc. but an empty `intake_question` table, so intake sections render with no fields to answer (found 2026-07-21 against a pre-2d dev database, confirmed via `select count(*) from intake_question`). Fix is a one-off `seed_intake_questions(session)` call against the affected database — safe and additive, it no-ops if rows already exist. Check this explicitly before staging/UAT and before the pilot goes live: run the count check and backfill if zero, rather than assuming setup covered it.

## 3. Items to hold until pilot evidence (P2–P5)

8. **Question-set admin screen.** Wording lives as configuration (`intake_question` rows) precisely so P2/P5 can iterate it — but there is no UI; edits need DB access. If P2 produces more than a handful of wording fixes, build a vocabularies-style admin editor; if not, a curated migration per revision is acceptable.
9. **Reopen-after-submit for intake.** Submissions are immutable once submitted. The pilot will show whether respondents need a correction flow ("reopen my intake") or whether curation absorbs it. Don't build speculatively.
10. **Gap workflow depth.** Gaps are open/resolved with a note. An organisation-wide audit (P6, hundreds of gaps) may need assignment, due dates, and interview batching. Let P3/P4 volumes decide.
11. **Curation assists.** Three places intake hands curators free text that the model wants structured: retention answers (H3–H6 → `activity_retention` links), per-subject data scoping (E4 → `data_subject_scope`), per-category retention (H5). A "convert answer to link" affordance would cut curation time — measure it in P4 first (curation time per activity is already a pilot success measure).
12. **Surface the intake submission from the activity.** A draft created by intake links back only via the intake list; the activity detail page should show "created from intake" with the answers and open gaps. Cheap, high value for curators — a good first post-pilot slice.
13. **Multi-activity flow.** One wizard run = one activity (by design), but B1 asks respondents to list several. A "start next activity for this department" shortcut carrying forward section A/B context would reduce friction for multi-activity respondents. P3 observation will show if it matters.
14. **B4 discovery answers go nowhere.** The "anything not written down?" answers are stored on the submission but not surfaced as leads. Consider adding them to the gaps queue or a discovery list for IG follow-up.

## 4. Future enhancements (post-pilot / Phase 5–6 horizon)

15. **Notifications** (Integration Architecture #8): overdue-review, trial-expiry and complaint-acknowledgement emails via estate SMTP. Currently the dashboard is authoritative and nothing sends; acceptable for pilot, expected for BAU.
16. **Entra group → role mapping.** Roles are assigned manually in `/users`; mapping IdP group claims to Cairn roles would remove a manual step and an offboarding risk. Needs a design decision (who owns role truth — Cairn or the directory?).
17. **Client certificate instead of client secret** for the Entra app registration (removes the secret-expiry failure mode flagged in admin ref §5.1).
18. **Export formats**: XLSX and PDF renderings of the Art 30/s61 views; read-only JSON API for BI tooling (Integration Architecture #7 future options).
19. **Complaints intake endpoint** (Integration Architecture §3.2 future option): the narrow public submission surface, if the org decides Cairn should receive complaints directly.
20. **Privacy-notice link checker** (Integration Architecture #4 future option).
21. **Legacy ROPA reconciliation view** (Phase 4): the CSV import creates drafts; a side-by-side reconcile of legacy rows against audit-derived records would make the Phase 4 "migration as reconciliation" concrete. Decide when the legacy register's condition is known.
22. **Automated backup verification**: the quarterly restore test is a manual runbook; scripting restore + smoke into CI-adjacent automation would make it routinely cheap.
23. **Further sector packs** (Phase 6): police / ambulance / local authority / generic — the seams (Organisation Profile, pack seeds, profile-conditioned rules, per-pack question sets) are proven; each new pack is content work plus a legislation review.
24. **Question Set v0.2** (planned): P5 retrospective output, folding in dry-run and pilot findings; becomes the periodic-review questionnaire (Plan §5). One candidate is already known: **merge C4/C5 into a single choice** ("our own activity / for another organisation / jointly with another organisation"), eliminating the processor-and-joint contradiction *structurally* rather than by validation (the conditional-logic slice rejects the combination with an error today, which works with v0.1 as signed off). A wording/structure change to signed content, so it takes the v0.2 route with IG sign-off — the `single_choice` kind, `depends_on` config and the C4/C5 apply mapping already support it, so the build cost is a seed edit, a data migration for the changed rows, and test updates.
25. **IAR slice 2i — asset intake wizard** (IAR plan §5.3/§7, added 2026-07-27): the guided, jargon-free asset question set for asset owners, producing proposed assets and gap records. Prerequisite is the `question_set` discriminator (`activity` | `asset`) on the intake tables — the same generalisation that serves item 8 (question-set admin) and the reseed mechanics in item 7 — plus a new *Cairn IAR Question Set v0.1* document. Sequence during pilot rollout waves; 2g–2h already give the pilot its inventory step (CSV import of the ICT application list at P1) without it.

## 5. Standing assurance items (Phase 3, unchanged but restated)

- **Penetration test** — now more urgent than when scoped: the attack surface grew (OIDC endpoints, intake forms).
- **Accessibility (WCAG 2.2 AA)** — the intake wizard and gaps queue are new user-facing surfaces built on GOV.UK components but not yet formally tested; respondents include the whole organisation, so intake is the highest-traffic screen Cairn has.
- **Rules-engine test formalisation** and UAT per Project Plan §6 — evidence packs, not new engineering.

---

## 6. Suggested order of attack

| When | Items |
|---|---|
| Before staging holds real data | 6 DPIA delta *(1, 3, 4 done 2026-07-17)* · 7 intake-question reseed check |
| At first staging deployment | 5 Entra round-trip verification *(2 done 2026-07-17)* |
| During pilot (as evidence arrives) | 8–14 · 25 IAR asset intake (rollout waves) |
| Before go-live | Phase 3 items (§5) · 15 notifications |
| Post go-live / roadmap | 16–24 |

---

*Backlog v0.1 — owner: IG lead + development. Re-baseline at the P5 retrospective; anything promoted from here into a build slice gets its own plan-and-spec treatment per the established pattern.*
