# Phase 1.7 Architecture Spike — Findings

**Status:** complete. Both spike questions answered **yes**. Code in `src/cairn/`, acceptance tests in `tests/test_spike_regime.py` and `tests/test_spike_rules.py` (SQLAlchemy 2 + SQLite — provisional stack, not a Phase 1.1 decision).

## Spike questions

**Q1 — Can an activity flip regime and back with both mappings intact, every change audited, and validation/export following the active regime?** Yes. `test_policy_flip_to_part2_switches_set_and_retains_part3` and `test_round_trip_flip_preserves_part3_mapping` walk the Spec §9.4 configurable-boundary scenario end-to-end: the Part 3 mapping survives a round trip field-for-field, each change writes an audit event with who/when/why, and both the fired rules and the export-view membership (s61 ↔ Art 30(1)) track the active regime.

**Q2 — Can rules be expressed as data so profile changes enable/disable them without code changes?** Yes. A rule is a frozen dataclass (id, severity, trigger name, requirement name, applicability) referencing named predicate functions in registries; the same rule set evaluated the same activity differently under `public_authority` vs `private_body` profiles and with the `external_data` module on/off, purely by changing profile data.

## What Phase 1.2 should adopt

1. **Dual mapping = `regime_scope` discriminator.** One `LawfulBasisRecord` row per regime per activity, `regime_scope enum(part2, part3)`, unique on `(activity_id, regime_scope)`. The active record is selected by `ProcessingActivity.regime`; a regime change touches no basis rows. Candidate `[spec clarification]` for Spec §6.1, which currently implies a single record with conditional fields.
2. **Unify the regime vocabulary.** Spec §2.2 uses `enum(part2, law_enforcement)` for `RegimePolicy.assigned_regime` while §3 uses `enum(general, law_enforcement)` on the activity — two names for one concept. The spike unified on `general | law_enforcement` and kept `part2 | part3` strictly as the *mapping-scope* enum. Candidate `[spec clarification]` for Spec §2.2.
3. **Cascade semantics confirmed.** A policy change cascades only to activities with `regime_source = policy` in that domain; `manual_override` (reason mandatory) pins an activity against later policy flips (`test_manual_override_requires_reason_and_pins_regime`). This is the Plan §1.6a behaviour and it fell out cleanly.
4. **Audit pattern: two generic tables.** `AuditEvent` (entity ref, event, actor, reason, old/new JSON) for significant events; `RecordVersion` (entity ref, version, full JSON snapshot, who/when/note) for rule-17 history. Both are entity-agnostic and need no per-entity schema.
5. **Derived flags as computed properties.** `special_category_flag` / `criminal_offence_flag` computed from linked data categories, not stored. Phase 1.2 should keep them derived (or a DB view) — a stored column needs sync triggers and can lie.

## Strain points / caveats for 1.2 and 2a

- **Version capture is caller-driven in the spike** (`capture_version` before mutating). Rule 17 says *every* record, *always* — production must hook snapshotting into the ORM event system (e.g. `before_update`) so it cannot be forgotten.
- **Regime-dependent requirements live inside the requirement function** (rule 1 branches general vs LE internally). Acceptable, but it means one rule id spans two legal routes; if rules move to DB rows, consider splitting per-regime variants so each row stays declarative.
- **Applicability axes implemented:** org type, active module, guards flag, active regime. Not yet needed but foreseeable: sector pack and `applicable_regimes` as axes.
- **Not exercised:** junction-scoped granularity (`activity_datacategory.data_subject_scope`), rules needing DPIA/Consent/Transfer entities (7, 9–11, 14), export *content* (only view membership), migrations, performance. None of these were in spike scope and nothing found suggests they threaten the two mechanisms.

## Verdict

Both load-bearing mechanisms are sound as designed. No changes to Plan v0.12 required; two field-level `[spec clarification]` candidates for Spec v0.3 (items 1–2 above). Phase 1.2 can proceed on this shape, and the spike code is a usable kernel for sub-phase 2a.
