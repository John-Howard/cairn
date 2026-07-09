# Cairn — Non-Functional Requirements

**Status:** NFRs v0.1 — the Phase 1.5 deliverable (Project Plan §4). Targets are sized for what Cairn is — a small-population, integrity-critical internal register — not for imagined scale. Verified in Phase 3 (performance & resilience testing); operationalised in Phase 1.6 (runbooks, CI/CD).
**Derives from:** Solution Architecture v0.1 (topology), Security Architecture v0.1 (integrity posture, audit), Integration Architecture v0.1 (interfaces).

---

## 1. Sizing assumptions

| Dimension | Assumption |
|---|---|
| Users | Tens of named users; < 20 concurrent in practice (IG team + distributed contributors during review cycles) |
| Data | Hundreds of processing activities; low thousands of junction rows; version/audit rows grow steadily but the database stays small (< 1 GB for years) |
| Traffic | Interactive CRUD; bursts around review cycles and questionnaire imports; no batch or compute workloads |

**Priority order: integrity > confidentiality > availability.** A day's outage is an inconvenience; a corrupted or unattributable record undermines the product's purpose. Targets below reflect that.

## 2. Performance

| Requirement | Target |
|---|---|
| Interactive page render (server-side) | < 1 s typical, < 3 s 95th percentile |
| Full-register export (any view, Spec §10) | < 30 s generated on demand |
| Import validation + preview (questionnaire/asset/migration files) | < 30 s for typical files (hundreds of rows) |
| Rule evaluation on save | Inline (< 200 ms per activity) — rules are in-process checks, not jobs |

No caching layer is warranted; if an export ever exceeds target, the answer is a background worker (Solution Architecture §2), not architecture change.

## 3. Availability & continuity

| Requirement | Target |
|---|---|
| Service availability | 99.5% during business hours (Mon–Fri 08:00–18:00); best-effort outside. Single app replica is acceptable |
| Planned maintenance | Outside business hours; announced in-app |
| **RPO** (max data loss) | ≤ 24 h from daily backups; ≤ 15 min where the estate provides PostgreSQL PITR/WAL archiving (use it when available) |
| **RTO** (max restore time) | ≤ 1 business day: redeploy container + restore backup, per runbook (1.6) |

Degraded mode is acceptable and simple: if Cairn is down, nothing downstream breaks — exports are point-in-time files and the register is not in any operational path.

## 4. Backup & disaster recovery

- **Daily automated database backups**, encrypted with the estate's at-rest discipline; retained **35 days rolling + monthly for 12 months**.
- Backups cover everything — records, versions, audit events, seeds and configuration are all in PostgreSQL by design (Solution Architecture §2); the container image is rebuildable from the repo.
- **Restore is tested quarterly** (and before go-live) by restoring to the staging environment; an untested backup is not a backup.
- DR = redeploy the image on any estate + restore the latest backup. No standby infrastructure is required at this scale.

## 5. Retention of Cairn's own data

Cairn documents retention for the organisation; it must also practise it. These are defaults, configurable per organisation, and recorded in **Cairn's own DPIA** (cross-cutting workstream):

| Data | Default retention |
|---|---|
| Processing records & linked registers | Life of the processing + org's corporate-records schedule after `retired`; never deleted while any live record references them |
| Version history & audit events | **At least as long as the records they evidence** (Security Architecture §4); review at record disposal, not before |
| APDs | Until 6 months after processing ends — statutory, already modelled (`retain_until`, Spec §6.4) |
| Complaints records | 2 years after closure (default; contains complainant personal data) |
| Breach records | 6 years (ICO expectation of demonstrable breach history) |
| User accounts | **Deactivate on leaving, never delete** — audit attribution (`created_by`/`changed_by`) must survive; display names may be retained as directory data |
| Application logs | 90 days; authentication/security events 12 months (in `AuditEvent`, so governed by the audit row above) |

## 6. Logging & monitoring

- **Structured JSON logs to stdout**, collected by the estate's aggregation — no log files in the container, no bespoke stack.
- **No personal data in logs**: log record IDs and event types, never field contents; exception messages scrubbed. (The audit trail in the database, not the log stream, is the forensic record.)
- **`/healthz`** endpoint (app up + DB reachable) for the estate's probes.
- Estate-level alerts on: service down, sustained 5xx rate, backup job failure, disk/storage thresholds. Application-level signals (overdue reviews, trial expiry, complaint acknowledgement due) are **dashboards and notifications for users, not ops alerts** (Integration Architecture #8).

## 7. Capacity & scalability posture

The stateless app scales horizontally and PostgreSQL vertically, but the honest statement is that **nothing in the sizing assumptions requires either**. The scalability requirement is organisational instead: the single-tenant model scales by *instances* (one per organisation), which is a packaging and release-process concern (1.6), not a runtime one.

## 8. Client environment

- Evergreen browsers (latest Chrome/Edge/Firefox/Safari) plus the organisation's managed-desktop standard.
- Server-rendered pages with progressive enhancement (htmx): core journeys work without JavaScript — an accessibility and resilience property together (WCAG 2.2 AA, Phase 3).

---

*NFRs v0.1. Verified by Phase 3 performance/resilience testing; backup, restore-test and alerting mechanics land with Phase 1.6.*
