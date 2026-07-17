# Cairn — Security Architecture

**Status:** Security Architecture v0.1 — the Phase 1.3 deliverable (Project Plan §4). Defines RBAC, authentication/SSO, encryption, the audit posture and standards alignment. Verified by security testing / pen-test in Phase 3.
**Derives from:** Solution Architecture v0.1 (`solution-architecture.md` — topology, stack, OIDC decision), Plan v0.12 §5.1 (roles), Spec v0.4 (audit fields, rule 17).

---

## 1. Security posture in one paragraph

Cairn is a single-tenant, internal-facing accountability record: a small user population, no public sign-up, no payment data, but records whose **integrity is the product** — a tampered ROPA is worse than no ROPA — plus pockets of real personal data (record owners, complainants, breach summaries). The architecture therefore prioritises (1) integrity and attributability of every change, (2) least-privilege access, (3) inheriting estate-grade controls (IdP, TLS, disk encryption) rather than inventing local ones.

## 2. Authentication (SSO)

- **OIDC Authorization Code + PKCE** against the organisation's IdP. **Decision (2026-07): Microsoft Entra ID is the confirmed IdP for staging and production**; the dev-login seam (`AUTH_MODE=dev`) remains for local development only and is disabled outside it. Cairn holds no passwords; **MFA is the IdP's responsibility** and is expected to be enforced there (Cyber Essentials). **Implemented (2026-07)** in `src/cairn/oidc.py` (`AUTH_MODE=oidc` + `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`, validated at startup).
- **Identity mapping is deny-by-default, no just-in-time provisioning.** A token signs in an existing active Cairn user or nobody: the email claim (`email`/`preferred_username`) matches the account on first login, the token's stable subject is then bound to the user (audited `oidc_subject_bound`) and later logins match by subject — an email change at the IdP cannot move the account, and a different subject presenting a bound email is refused. Successful logins are audited (`login_succeeded`); unknown/deactivated identities are refused and logged (subject only — no personal data in logs). In `oidc` mode the session cookie is `Secure`.
- **Server-side sessions** after login: cookie is `Secure`, `HttpOnly`, `SameSite=Lax`; absolute lifetime 12h, idle timeout 60m (configurable per org).
- **Bootstrap**: first-run setup creates the Organisation Profile and maps an initial `approver_dpo`; thereafter all access is via SSO. No standing local accounts.
- Login, logout, and failed/denied authorisations are recorded as `AuditEvent` rows — the same table that audits record changes.

## 3. Authorisation (RBAC — the four Plan §5.1 roles)

Roles are assigned from **IdP group claims** at login (group→role mapping is Organisation Profile configuration). Enforcement is **deny-by-default at the route layer** (FastAPI dependencies); template-level hiding of buttons is cosmetic only, never the control.

| Operation | contributor | curator | approver_dpo | viewer |
|---|---|---|---|---|
| Read records & dashboards | own function | ✓ | ✓ | ✓ |
| Create/edit **draft** activities | own function only (`User.business_function_id`) | ✓ | ✓ | — |
| Propose reference-data values | ✓ | ✓ | ✓ | — |
| Approve reference-data values | — | ✓ | ✓ | — |
| Edit reference libraries directly | — | ✓ | ✓ | — |
| Set `record_status = active` / sign-off | — | — | ✓ | — |
| Change Regime Policy / regime override | — | — | ✓ | — |
| Approve trial → live (rule 14) | — | — | ✓ | — |
| Manage users/role mapping, Organisation Profile | — | — | ✓ | — |

Separation of duties is preserved from Plan §5.1: **curators cannot sign off** — authoring/curation and approval are different roles by design. The regime switch and trial gates sit with `approver_dpo` because both are significant accountability decisions (Plan §1.6a, rule 14).

## 4. Integrity, audit trail & version history (rule 17)

Already enforced in the kernel and treated as a security control, not just a feature:

- **Every audited update requires an actor** (`versioning.py` raises without `session.info["actor_id"]`) and snapshots the prior state to `RecordVersion` — who, when, what, why (`change_note`).
- **Significant events** (regime changes, policy changes, sign-offs, auth events) additionally write `AuditEvent` rows with old/new values and reason.
- `AuditEvent` and `RecordVersion` are **append-only by policy**: no UI or service code path updates or deletes them; the application DB role is granted INSERT/SELECT but not UPDATE/DELETE on those tables in production (PostgreSQL grants — enforced at 2a).
- Audit/version data retention is set with the organisation's own schedule (Phase 1.5), never shorter than the records it evidences.

## 5. Encryption & secrets

| Concern | Control |
|---|---|
| In transit | TLS 1.2+ terminated at the estate proxy/load balancer; HSTS; app-to-DB TLS where the estate requires it |
| At rest | Database/volume encryption from the estate: managed-PostgreSQL encryption in cloud, LUKS/equivalent on-prem. Backups encrypted with the same discipline. No application-level field encryption at v1 — contents are processing metadata plus limited personal data, adequately covered at the storage layer |
| Secrets | OIDC client secret and DB credentials injected as environment variables/secret mounts from the estate's secret store (Key Vault / Secrets Manager / Vault). Nothing secret in the repo, image, or config files |

## 6. Application security (build-time discipline)

- **CSRF tokens** on every state-changing form (server-rendered + htmx makes this uniform); `SameSite` as defence in depth.
- Security headers: CSP (no third-party origins — GOV.UK Design System assets served locally), `X-Content-Type-Options`, `Referrer-Policy`, frame denial.
- Input handling: typed models and enum vocabularies do most validation; ORM parameterisation everywhere (no raw SQL); output escaping via Jinja2 autoescape.
- Supply chain: `uv.lock` pins dependencies; dependency and container-image scanning in CI (Phase 1.6); base-image updates via scheduled rebuilds.
- These are verified, not assumed: **pen-test and security review in Phase 3** before live data.

## 7. Standards alignment

| Standard | How Cairn aligns |
|---|---|
| **Cyber Essentials** | MFA & access control at the IdP; least-privilege RBAC; patching via image rebuilds + dependency updates; malware protection and boundary controls inherited from the estate |
| **NCSC Cloud Security Principles** | Data in transit (TLS), asset protection (estate encryption at rest), separation (single-tenant by design — principle 3 is trivially met), audit for users (§4), secure service administration (SSO + deny-by-default) |
| **UK GDPR Art 32** | The measures above are Cairn's own "appropriate technical and organisational measures"; Cairn's own DPIA (cross-cutting workstream) records the assessment |
| **OWASP Top 10 / ASVS-informed** | §6 controls; Phase 3 pen-test scoped against it |

## 8. Residual risks & later phases

- **Availability** is deliberately simple (stateless app + backed-up DB); DR/backup targets in Phase 1.5.
- **Monitoring/alerting** (auth anomalies, error rates) lands with Phase 1.5/1.6 logging design; audit tables give it the data.
- **s62 logging** (Part 3): Cairn flags in-scope systems and references where logs live — it does not itself produce s62 logs (Plan §1.6).

---

*Security Architecture v0.1. Detail is enforced in code from sub-phase 2a; assurance evidence lands in Phase 3.*
