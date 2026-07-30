# Cairn — IAR Question Set

**Status:** v0.1 — for iteration. **Implementation decision:** this question set is built into **Cairn as the asset-intake screen** (questions held as configuration, the same mechanism as the activity intake screen — see *Cairn — Information Audit Question Set*). The "Populates" column per question is the intake-screen field mapping onto `InformationAsset`.
**Purpose:** A jargon-free question set for describing one information asset — a system, database, application, or collection of paper or physical records — so that asset owners across the organisation can help populate the Information Asset Register (IAR) without IT or IG expertise.
**Relates to:** *Cairn IAR Plan* v0.1 (the register this feeds), *Cairn — Slice 2i Plan: Asset Intake Wizard* §4 (source of this content), *Cairn — Information Audit Question Set* v0.1 (the content and structural precedent this mirrors).

---

## 1. How to use this

**One response per *asset*, not per department.** A department will often hold or use several distinct assets — a case-management system, a shared drive, a set of paper files — each of which gets its own run through this question set. This mirrors the activity intake's "one response per activity" rule.

**"Don't know" is a valid answer on every question.** It's more useful than a guess — it is recorded as a gap for the IG team to follow up, exactly as in the activity intake.

**Not every gap is a "don't know".** Unlike the activity set, this one also raises a gap where the respondent *did* answer but only a curator can complete the work: the named senior owner in AS-B2 always raises one (the curator binds the person to a user account), and AS-B3, AS-D2_NAME and AS-F1 raise one when the name given matches no existing business function, legal entity or retention rule. Respondents are not asked to do anything more about these — they exist so the follow-up is not silently lost at curation.

**What the start screen collects, before Section A begins:**
- which department or team this asset belongs to (business function) — the respondent's own department, becoming the asset's first linked business function;
- who is completing this (the respondent);
- a short name for the asset (e.g. "the HR system", "station log books", "CCTV recordings") → `label`.

**What this screen deliberately does not ask:** the security **classification** of the asset, and whether it is in scope for **s62 access logging**, both require Information Governance judgement made at curation, not a respondent's opinion — so they are set when the curator reviews the proposed asset, not asked here.

**Roles:** the same as activity intake — a contributor describes the asset they know; the IG/DP team curates the answer into an approved register entry; the DPO's oversight continues through the existing `/assets` approval flow.

---

## Section A — What it is

| Code | Question (plain English) | Hint / options | Populates |
|---|---|---|---|
| AS-A1 | Which of these best describes it? | **Choose one:** A computer system or online service · A database or large collection of records · A software application · Paper files or records · Equipment, devices or media that hold information | `asset_type` |
| AS-A2 | In plain English, what is it and what is it used for? | | `description` |
| AS-A3 | Is it still in everyday use? | **Choose one:** Still used · Being phased out or replaced · No longer used at all | `status` |

> **Note on A1 and A3.** The source plan (§4) carried these option lists as *hint* text. They are the answer itself, not guidance about it, so both are built as single-choice questions whose options are exactly the values listed here — each mapping to one `AssetType` / `AssetStatus` value.

---

## Section B — Who looks after it

| Code | Question (plain English) | Hint | Populates |
|---|---|---|---|
| AS-B1 | Who looks after it day to day? | A person or team, e.g. "HR admin team" | `custodian` |
| AS-B2 | Who is the senior person responsible for it? | The person who would decide if it changed or was got rid of — its owner | `notes` + gap → curator binds `iao_user_id` |
| AS-B3 | Do any other teams or departments use or rely on it? Which ones? | Your own department is already recorded — list any others | business functions (label match; unmatched → `notes` + gap) |

> **Open point — AS-B2 wording.** "The senior person responsible for it" is the working plain-English rendering of **Information Asset Owner (IAO)** for this question set. It is provisional, pending confirmation from the SIRO / Information Governance team on whether the organisation has preferred house terminology for this role. Treat it as a draft wording to sign off, not a settled decision.

---

## Section C — The information it holds

| Code | Question (plain English) | Hint | Populates |
|---|---|---|---|
| AS-C1 | Does it hold information about people? | Staff, the public, anyone — however routine | `contains_personal_data` |
| AS-C2 | *(if AS-C1 = yes)* Roughly what information about people does it hold? | Names and contact details? Health information? Photographs or recordings? | `notes` (curation context) |

---

## Section D — Where it is

| Code | Question (plain English) | Hint | Populates |
|---|---|---|---|
| AS-D1 | Where is it kept? | A building or room for paper; a supplier, data centre or "the cloud" for systems | `location` |
| AS-D2 | Is it provided or hosted by an outside company? | | (gates AS-D2_NAME / AS-D3 below) |
| AS-D2_NAME | *(if AS-D2 = yes)* Which company? | | supplier match → `supplier_entity_id`, else `notes` + gap |
| AS-D3 | *(if AS-D2 = yes)* Is any of the information kept outside the UK? Where? | | `hosting_country` |

> **Note on the split.** The source plan (§4) posed this as two questions — "is it hosted by an outside company, which one" and "is it kept outside the UK" conditional on the first being answered. Cairn's `depends_on` configuration can only express "conditional on a specific answer value", not "conditional on any answer being given" — so the naming question is split out as its own code (AS-D2_NAME), both AS-D2_NAME and AS-D3 conditional on AS-D2 = yes. This is the same pattern already used for the activity question set's C3/C3_DETAIL pair.

---

## Section E — How it's protected

| Code | Question (plain English) | Hint | Populates |
|---|---|---|---|
| AS-E1 | How is it protected? | Locked rooms or cabinets, passwords, restricted access, encryption — pick all that apply or suggest new ones | security measures (+ proposals) |

---

## Section F — Keeping and disposing

| Code | Question (plain English) | Hint | Populates |
|---|---|---|---|
| AS-F1 | How long is the information kept, and is that written down anywhere? | | retention match → `default_retention_id`, else `notes` + gap |
| AS-F2 | When should this asset next be checked or reviewed? | Leave blank if you don't know | `next_review_date` |

---

## 2. After the questionnaire

As with activity intake, a completed run does not go straight onto the register: it creates a **proposed** `InformationAsset` for the IG/DP team to curate — deduplicating against existing entries, setting classification and s62 logging scope, binding the named senior owner (AS-B2) to an actual account as Information Asset Owner, resolving any recorded gaps, and approving through the existing `/assets` register. Rule 22 (approved personal-data assets with no linked activity) then carries the pipeline forward into activity documentation.

---

*Cairn — IAR Question Set v0.1. Derived from Slice 2i Plan §4 and mapped to `InformationAsset` fields (Spec-superseding IAR Plan §2).*
