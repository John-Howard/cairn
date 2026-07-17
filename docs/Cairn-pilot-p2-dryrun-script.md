# Cairn — Pilot Stage P2: Dry-Run Script

**Status:** v0.1. Operationalises stage **P2** of the *Intake & Information Audit Pilot Plan* §5 ("walkthrough with IG team acting as respondents → wording/flow fixes before real users").
**Prerequisite:** P1 signed off (`Cairn-pilot-p1-seeding-checklist.md`) — an intake-ready instance. Run the dry-run on a **disposable copy** of that instance if possible; otherwise every record created below is throwaway and section 6 (cleanup) is mandatory.
**Participants (half a day):** two or three IG team members playing **respondents** (deliberately *not* reading ahead), one **scribe/observer** per respondent, one **curator**, DPO drops in for the debrief.

The point is to fail here, cheaply. Respondents should role-play honestly — answer as a busy watch manager or HR officer would, not as someone who knows the data model. The scribe never helps; where the respondent hesitates, that hesitation *is* the finding.

---

## 1. Ground rules

- Respondents role-play the personas below and **improvise beyond the script** — the script fixes the scenario, not the words they type.
- **"Don't know" is encouraged** where the persona plausibly wouldn't know. We are testing that the gap pipeline feels legitimate, not shameful (Question Set golden rule 2).
- The scribe records, per question: hesitation (>10s), re-reading, wrong first interpretation, hint text used or not noticed, anything typed then deleted, and verbatim "what does this mean?" remarks.
- Nobody fixes anything mid-run. Findings go in the log (§5); fixes come after.

## 2. Scenario A — Prevention & Community Safety: "Home fire safety visits"

*Respondent persona: watch manager who does HFSVs weekly and has never seen a ROPA. Exercises: special categories, children/vulnerable flags, external data, sharing, mobile working, don't-knows.*

| Step | Do | Watch for |
|---|---|---|
| A-1 | Start an intake named **"Home fire safety visits"** from a contributor account scoped to Prevention | Function is fixed and explained; start screen plain-English check |
| A-2 | Section B: business as usual (B3 = No); at B4 mention the paper referral forms kept in the watch office | Does B4's prompt list actually prompt? |
| A-3 | Section C: describe the visit in own words (C1); C3 Yes but **don't know which law** → answer C3, tick "don't know" on C3_DETAIL | Is answering yes-but-dk natural or confusing? |
| A-4 | Section D: pick *vulnerable persons* and *members of the public*; propose **"hoarders referred by partner agencies"** as new; D2 Yes, D3 Yes, D4 hundreds | Is the propose-new box discoverable without help? |
| A-5 | Section E: pick contact details + household data; in E2 tick health and safeguarding; E3 No; E4 describe extra detail held about children | Does E2's special-category list read as jargon? |
| A-6 | Section F: sources = person + another organisation; F2 pick **CACI Acorn** (pre-created in P1 C4); F3 Yes, F4 by a person; F6 don't know | F3→F4→F5 skip logic comprehensible? |
| A-7 | Section G: share with *adult social care* and *children's social care*; G2 "we refer safeguarding concerns"; G3 don't know | Is G3 (outside UK / cloud) understood by a non-IT respondent? |
| A-8 | Section H: pick the HFSV mobile app (P1 C1); H2 mention the paper forms again; H3 don't know | Shadow-data question (H2) pulling its weight? |
| A-9 | Sections I–J: honest answers; J6 in plain words | Does J read as blame-seeking? (It must not) |
| A-10 | Review page: check answers; confirm the don't-know count and the proposed value are visible; submit | Is "draft, nothing published" reassurance noticed? |

## 3. Scenario B — HR: "Recruiting new staff"

*Respondent persona: HR officer. Exercises: conventional processing, criminal-offence route, processor relationship, retention knowledge.*

- B-1 Start **"Recruiting new staff"** from the HR contributor account. B3 No.
- B-2 Section C: C1 own words; C4 **No** (we are not doing it for someone else — watch whether the C4/C5 distinction between *for* and *jointly with* lands); C5 No.
- B-3 Section D: *applicants / prospective employees*; D2 No, D3 No, D4 hundreds.
- B-4 Section E: employment data + identifiers; **E3 Yes** (DBS/vetting) — verify the respondent understands E3 covers vetting, not just convictions.
- B-5 Section F: from the person + third parties (references); F3 No — verify F4/F5 are comfortably skippable.
- B-6 Section G: name the recruitment platform provider under G4 (handles it on our behalf) — watch whether G1 vs G4 confuses.
- B-7 Section H: propose the recruitment platform as a new system; H3 give the real retention answer if known ("6 months unsuccessful applicants…").
- B-8 Section J: J1 don't know — consent for recruitment is a curation trap; note whether the respondent guesses.
- B-9 Review and submit.

## 4. Scenario C — Protection: "Investigating fire safety breaches" *(Section K check)*

*Respondent persona: fire safety inspector. Not a pilot function — this scenario exists to exercise the enforcement path end-to-end once.*

- C-1 Start from a Protection-scoped account. Confirm **Section K appears** (and did not for A/B — ask both earlier respondents).
- C-2 Answer B–J briskly (E3 Yes); the focus is K: K1 Yes; K2 tick suspect + witness; K3 Yes; K4 describe the case system's access logging in plain words.
- C-3 At review, confirm K answers display; submit; confirm the draft carries the K answers for the DPO's regime decision (the wizard must **not** have asked the respondent to classify the regime — that is the DPO's call).

## 5. Curation leg + findings log

With all three drafts submitted, the **curator** (timed, per activity — this is the pilot's curation-load measure):

1. `/vocabularies`: approve or reject the proposed values (hoarders…, recruitment platform). Note any that should have matched an existing entry — each is a **vocabulary finding**.
2. `/intake/gaps`: resolve one gap with a realistic note; leave the rest open (they are P4 interview material in the real pilot).
3. Open each draft activity: verify junction links, flags (children/vulnerable/special-category/criminal-offence), inherited security on the system-linked drafts.
4. Sanity-check `/register` and the dashboard: three drafts visible as drafts, none in exports.

**Findings log** (one row per observation, kept with the pilot records):

| # | Where (question code / screen) | Type: wording · flow · vocabulary · bug | What happened (verbatim where possible) | Severity: blocks pilot · fix before P3 · note for v0.2 | Proposed fix | Owner |
|---|---|---|---|---|---|---|

Debrief prompts for each respondent: which single question was hardest, and why; where did you most want a person to ask instead; did anything feel like an audit of *you*; would your colleagues finish this unaided?

## 6. After the dry-run

- [ ] Findings log dispositioned with the DPO: every row has a severity and owner.
- [ ] **Wording fixes applied as configuration** (`intake_question` rows — no release needed) and re-walked by one respondent.
- [ ] Vocabulary fixes applied (renames/additions per findings).
- [ ] Any *blocks pilot* bug fixed and released before P3.
- [ ] **Cleanup:** throwaway drafts retired/deleted, dry-run proposals rejected or kept deliberately, gaps closed, or the disposable instance destroyed. The P1 baseline backup is the restore point.
- [ ] Question-set change notes recorded for the eventual v0.2 (P5 retrospective input).

**Exit criterion → P3:** the IG team would hand this wizard to a real watch manager tomorrow without an apology.

---

*P2 Dry-Run Script v0.1 — findings feed Question Set v0.2 at the P5 retrospective.*
