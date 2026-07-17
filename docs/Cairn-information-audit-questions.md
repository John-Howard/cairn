# Cairn — Information Audit Question Set

**Status:** v0.1 — for iteration. **Implementation decision:** this question set is built into **Cairn as its intake screen** (questions held as configuration), and the audit runs through Cairn as the pilot — see *Cairn — Intake & Information Audit Pilot Plan*. The "Populates" column per question is the intake-screen field mapping.
**Purpose:** A jargon-free question set for the information audit / data-mapping exercise across all departments and teams, feeding the initial population of Cairn.
**Relates to:** *Cairn — Project Plan* (Phase 0/4), *Plan v0.12* §5 (workflow, hybrid authoring), *Spec v0.3* (fields the answers populate).

---

## 1. How to use this

**Method (per ICO guidance):** distribute a questionnaire to each area that processes personal information; then **meet directly** with key business functions to fill gaps; then **review policies, procedures, contracts and agreements** to confirm what you were told. The questionnaire alone is never enough — it starts the conversation.

**Structure — broad to narrow.** Questions follow the ICO's recommended flow, which is also Cairn's data model:

> **Department → Activity → who the people are → what data → why → who it's shared with → where it lives → how long → how it's protected**

**Two golden rules:**
1. **One response per *activity*, not per department.** A department will usually complete Section B–J several times — once for each distinct thing it does with personal information. This is what produces the granular, linked record the ICO requires; a single generic list per department will not meet Article 30.
2. **"Don't know" is a valid answer.** It's more useful than a guess. The IG team will follow up.

**Language note:** "personal information" means anything that could identify a living person — a name, an address, a photo, a phone number, a case reference, even a note about someone. If in doubt, include it.

**Roles:** each department nominates a named respondent (the activity owner). The IG/DP team curates the answers into Cairn; the DPO signs off.

---

## Section A — About you and your department
*(Answered once per department)*

| # | Question | Populates |
|---|----------|-----------|
| A1 | Which department/team are you completing this for? | Business Function |
| A2 | Who is completing this, and what is your role? | Activity owner / respondent |
| A3 | Who should we contact with follow-up questions? | Owner contact |
| A4 | Roughly how many people work in your team? | Context |
| A5 | Is there anyone else in your team we should also speak to? | Coverage check |

---

## Section B — Identifying the activities
*(Answered once per department; each activity identified here then gets its own C–J response)*

| # | Question | Populates |
|---|----------|-----------|
| B1 | List the main things your team does that involve information about people. Think about your regular duties, not IT systems. | Processing Activity (list) |
| B2 | For each one, give it a short name (e.g. "recruiting new staff", "carrying out home fire safety visits", "investigating a fire"). | `name` |
| B3 | Is any of this work new, a trial or a pilot? If so, when did it start and when does it end? | `lifecycle_stage`, `trial_start/end` |
| B4 | Is your team doing anything with people's information that you think isn't written down anywhere? | Gap discovery |

> **Prompt list if the team is stuck** — do you: recruit or manage staff? handle complaints? run community or school programmes? visit people's homes? respond to incidents? carry out inspections or enforcement? manage contracts or suppliers? run surveys? use CCTV, body-worn video or drones? handle referrals from other agencies? maintain a mailing list?

---

## Section C — What the activity is for
*(Repeat Sections C–J for each activity from B)*

| # | Question | Populates |
|---|----------|-----------|
| C1 | In plain English, what is this activity and why do you do it? | `purpose`, `description` |
| C2 | What would happen if you didn't collect this information? | Necessity / minimisation |
| C3 | Is there a law, statutory duty or policy that requires or allows you to do this? Which one, if you know? | Lawful basis (Art 6(1)(e) evidence) |
| C4 | Are you doing this work **for another organisation**, under their instructions? If so, which one? | `controller_or_processor` = processor |
| C5 | Are you doing this **jointly** with another organisation, where you both decide how it works? | `controller_or_processor` = joint |

---

## Section D — Whose information is it?

| # | Question | Populates |
|---|----------|-----------|
| D1 | Whose information do you handle in this activity? (e.g. members of the public, people at incidents, employees, applicants, cadets, business owners, partner-agency staff) | Data Subject Categories |
| D2 | Does this activity involve information about **children or young people**? | `children_flag` |
| D3 | Does it involve **vulnerable people**, or people at risk? | `vulnerable_or_safeguarding_flag` |
| D4 | Roughly how many people's records are involved — a handful, hundreds, thousands? | Scale (DPIA trigger) |

---

## Section E — What information do you hold?

| # | Question | Populates |
|---|----------|-----------|
| E1 | What information do you record about them? (e.g. name, address, phone, date of birth, case notes, photos) | Personal Data Categories |
| E2 | Do you record any of the following? *(tick all)* — health or medical information · disability or care needs · safeguarding concerns · race or ethnicity · religion · sexual orientation · trade union membership · biometric data (e.g. fingerprints, facial recognition) · genetic data | Special category → Art 9 route |
| E3 | Do you record anything about **criminal offences, convictions, cautions, or suspected offences** (including vetting/DBS)? | `criminal_offence_flag` → Art 10 |
| E4 | **If the people involved are different types** (e.g. adults and children, or staff and public) — do you hold *different information* about each? Please say which. | `activity_datacategory.data_subject_scope` **(the ICO's "meaningful links" requirement)** |

---

## Section F — Where does the information come from?

| # | Question | Populates |
|---|----------|-----------|
| F1 | Where do you get it from? *(tick all)* — directly from the person · from a colleague or another team · from another organisation · from a publicly available source · purchased or licensed from a supplier | `personal_data_source` (Art 13 vs 14) |
| F2 | If it comes from another organisation or a supplier, **which one**, and is there an agreement or contract in place? | External Data Source, Contract/DSA |
| F3 | Do you **combine** information from different places to build a picture of someone, or to score/rank/prioritise them? | `external_data_use_mode` |
| F4 | If so, is that done **by a person** reviewing it, or **automatically by a system or model**? | manual vs automated |
| F5 | If automatic — does the system **make the decision**, or does it only suggest/prioritise and a person decides? | Art 22A–22D assessment |
| F6 | Are people told their information comes from these sources? | Privacy notice / Art 14 |

---

## Section G — Who else sees it?

| # | Question | Populates |
|---|----------|-----------|
| G1 | Who do you share this information with, outside your team? *(internal teams, other organisations, suppliers)* | Recipients |
| G2 | For each one — why do you share it, and is there an agreement, contract or information-sharing agreement in place? | Contract/DSA |
| G3 | Do you share it with any organisation **outside the UK**, or use any system that stores data outside the UK (including cloud services)? | Transfer |
| G4 | Does anyone else handle this information **on your behalf** (e.g. a supplier, contractor or IT provider)? | Processor relationship |

---

## Section H — Where is it kept, and for how long?

| # | Question | Populates |
|---|----------|-----------|
| H1 | Which systems, applications or databases hold this information? | System/Asset |
| H2 | Is any of it kept **outside** those systems — spreadsheets, shared drives, email, paper files, notebooks, mobile devices? | Shadow-data discovery |
| H3 | How long do you keep it, and what happens at the end? | Retention Rule |
| H4 | Is that retention period written down anywhere, or based on a legal requirement? | `legal_driver` |
| H5 | **If you hold different types of information in this activity, do they have different retention periods?** Please say which. | Per-category retention (**meaningful links**) |
| H6 | How is it destroyed or deleted when no longer needed? | `disposal_method` |

---

## Section I — How is it protected?

| # | Question | Populates |
|---|----------|-----------|
| I1 | Who in your team can access this information — everyone, or specific roles? | Access control |
| I2 | Is access restricted by log-in, permissions, or physical security (e.g. locked cabinets)? | Security Measures |
| I3 | Is it ever taken out of the office — on laptops, mobiles, tablets or appliance terminals? | Mobile/endpoint risk |
| I4 | Have you had any near-misses, losses or incidents involving this information? | Breach record / risk |

> *Note: the IG/IT team will complete the technical detail for each system centrally — you don't need to know encryption or backup specifics. Just tell us where the information is and who can get to it.*

---

## Section J — Rights, consent and risk

| # | Question | Populates |
|---|----------|-----------|
| J1 | Do you ask people for their **consent** for this activity? If so, how is it recorded, and how can they withdraw it? | Consent Record |
| J2 | If children are involved and you rely on consent — how do you check age, and do you get parental consent? | Age check / parental consent |
| J3 | Are people told what you do with their information (e.g. a privacy notice, a leaflet, a form, verbally)? | Privacy Notice |
| J4 | If someone asked to see everything you hold about them, could you find it? | SAR readiness (gap indicator) |
| J5 | Has a Data Protection Impact Assessment (DPIA) ever been done for this activity? | DPIA link |
| J6 | What's the **worst thing** that could happen if this information was lost, leaked or wrong? | Risk / DPIA trigger |
| J7 | Is there anything about this activity that worries you, or that you think we should look at? | Open risk capture |

---

## Section K — For enforcement and investigation teams only
*(Protection / Fire Investigation / Youth & Early Intervention)*

| # | Question | Populates |
|---|----------|-----------|
| K1 | Does this activity involve investigating or prosecuting a possible **offence**? | Regime routing (Plan §1.6) |
| K2 | Do you record whether someone is a **suspect, witness, victim, or convicted**? | `le_data_subject_classification` |
| K3 | Do you distinguish between **facts** and your **professional assessment or opinion** in case records? | `le_fact_vs_assessment_noted` |
| K4 | Does your case system record **who accessed or disclosed** a record, and when? | s62 logging scope |

> *Whether this work is treated as "law enforcement processing" is a decision for the DPO — these answers inform it, and Cairn supports either outcome.*

---

## 2. After the questionnaire

Per ICO guidance, the questionnaire is step one of three:

1. **Questionnaire** — this document, distributed to every department.
2. **Interviews** — the IG/DP team meets each key business function to probe gaps, resolve "don't knows", and catch activities people forgot to mention (B4 is deliberately designed to surface these).
3. **Document review** — check the answers against policies, procedures, contracts, information-sharing agreements and system documentation. **Would the record match what people are actually doing?** That is the test the ICO applies.

**Then:** the IG team curates responses into Cairn — creating activities, linking them to the controlled vocabularies, and proposing any new reference values for approval (Plan §5.1). Contributors validate their own records before DPO sign-off.

---

## 3. Practical notes

- **Keep it conversational.** Departments will resist a compliance form. Frame it as "help us record what you do so we can protect it properly," not an audit of them.
- **Pre-fill what you can.** The IG team should pre-populate obvious activities from existing knowledge and ask people to *correct* rather than *create* — a much lower barrier.
- **Expect the shadow data (H2) to be the most valuable answer.** Spreadsheets, inboxes and paper files are where undocumented processing hides.
- **Senior sponsorship matters.** ICO guidance stresses management buy-in; without it, response rates collapse.
- **This is not a one-off.** The same question set becomes Cairn's periodic review questionnaire (Plan §5), so design it once and reuse it at each review cycle.

---

*Cairn — Information Audit Question Set v0.1. Derived from ICO documentation guidance (information audit, data mapping, questionnaire method) and mapped to Spec v0.3 fields.*
