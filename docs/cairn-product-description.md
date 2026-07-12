# Cairn

### The Record of Processing Activities, built for accountability — not spreadsheets.

**Cairn** is a web application for compiling and maintaining a **Record of Processing Activities (ROPA)** that meets UK GDPR **Article 30** and the accountability principle. A cairn is a stack of stones that marks the safe path across difficult ground; the tool does the same for data protection — a durable, well-kept marker of exactly how an organisation processes personal data, and why it is lawful.

Cairn is a **single-tenant, configurable product**: each organisation runs its own instance, so there is no shared store and no cross-tenant isolation to worry about. One configurable core is tailored at setup by an **Organisation Profile** and a **sector pack** of ready-made vocabularies and rules. The first pack ships for the **Fire and Rescue Service (FRS)**; the same core supports police, health, local authority or generic controller/processor profiles.

---

## What it does

Article 30 is not met by a spreadsheet row per activity. Cairn models processing **relationally** — a central Processing Activity record linked, at the right level of granularity, to the data subjects, data categories, recipients, systems, retention rules and lawful bases that actually apply. That structure is what lets it hold real-world complexity: where adults, vulnerable adults and children diverge within a single activity, Cairn keeps them straight.

It is a **full integrated accountability record**, not just a register — ROPA, lawful-basis records, DPIA, LIA/RLI, contracts/DSAs, transfers, privacy notices, automated-decision safeguards and complaints, all linked and cross-checked.

## Key features

- **Complete Article 30 register** — controller (Art 30(1)) and processor (Art 30(2)) records, with a guided authoring wizard and junction editors for full granularity.
- **Dual-regime by design** — handles both general processing (UK GDPR / DPA 2018 Part 2) and law-enforcement processing (Part 3, s61/s62). A per-organisation **Regime Policy** decides how the enforcement boundary is treated; activities switch regime **without ever losing the inactive mapping**, and every switch is audited.
- **Lawful basis, done properly** — Article 6 and special-category / Schedule 1 & 8 conditions seeded from current legislation, with consent, Legitimate Interests and Appropriate Policy Document records where the basis requires them.
- **Linked accountability registers** — DPIAs, contracts/DSAs, international transfers, privacy notices and automated decision-making (Art 22A–22D safeguards) all connected to the activities they support.
- **Built-in validation** — a rule engine checks records against 21 rules as you author, surfacing gaps and warnings (unapproved references, children's higher protection, further-processing, ADM safeguards) before they become findings.
- **Hybrid authoring workflow** — a central IG/DP team curates the register while departments contribute through questionnaires and CSV import; propose-and-approve keeps vocabularies clean; review cycles keep records current.
- **Export mapping layer** — Art 30(1), Art 30(2), s61 and combined ROPA views generated on demand as CSV. The stored model stays clean and normalised; exports never dictate the shape of the data.
- **Dashboard & KPIs** — a live view of register health, records due for review, and outstanding rule findings.
- **DUAA-aligned** — updated for the Data (Use and Access) Act 2025: statutory complaints (s164A), children's higher-protection and further-processing fields, and a commencement watch for provisions still coming into force.

## Why Cairn

- **Relational, not flat** — granularity lives in the model, so the register survives contact with reality instead of collapsing into an unmaintainable sheet.
- **Reversible and audited** — versioning, change notes and an append-only audit posture mean every change is recoverable and every decision is evidenced.
- **Configurable, not bespoke** — one codebase, tailored by profile. Adopting Cairn for a new sector means seeding a pack, not rebuilding the tool.
- **Cloud-agnostic and self-hosted** — FastAPI, the GOV.UK Design System and PostgreSQL, deployed as a container in your own estate, with OIDC single sign-on and deny-by-default role-based access.
- **Legally grounded** — vocabularies and rules trace back to specific legislation and ICO guidance, and are maintained against amendments as the law changes.

---

*Cairn — a clear, defensible record of how you process personal data.*
*Built to UK ICO / UK GDPR Article 30 and DPA 2018 Parts 2 & 3, aligned with the Data (Use and Access) Act 2025.*
