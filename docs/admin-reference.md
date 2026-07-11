# Cairn — System Administration Reference

**Status:** Admin Reference v0.1. Operational companion to Environments & DevOps v0.1 (`environments-devops.md`) — that document holds the design decisions and runbook commitments; this one is the hands-on reference for starting, stopping and managing the application in each environment. Everything here describes what the repository actually does today.

---

## 1. Configuration

All behaviour differences between environments come from three environment variables (`src/cairn/settings.py`); there are no environment-specific builds or config files.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///cairn.db` | SQLAlchemy URL. Reference deployment uses `postgresql+psycopg://…` |
| `SESSION_SECRET` | `dev-secret-change-me` | Signs the session cookie. **Must be set to a strong random value outside dev.** Rotating it invalidates all active sessions (users are logged out; no data is lost) |
| `AUTH_MODE` | `dev` | `dev` enables the passwordless dev-login screen at `/login`. Any other value disables the login routes entirely — **OIDC SSO is not yet built** (planned before staging), so until that slice lands the application is only usable with `AUTH_MODE=dev` and must not be exposed beyond a trusted network |

## 2. Development

Prerequisites: Python 3.14 and [uv](https://docs.astral.sh/uv/). The dev database is SQLite (`cairn.db` at the repo root, gitignored); tests use in-memory SQLite and need no setup.

```sh
uv sync                                  # install (creates .venv from uv.lock)
uv run alembic upgrade head              # create/upgrade the dev database
uv run uvicorn cairn.web:app --reload    # start on http://127.0.0.1:8000
```

Stop with `Ctrl-C`. Quality gates (same as CI): `uv run ruff check .` and `uv run pytest -q`.

- **First run:** with an empty database, visiting `/` redirects to the `/setup` wizard, which creates the Organisation Profile, seeds the legal and FRS vocabularies, and creates the bootstrap `approver_dpo` user (logged in immediately). `/setup` returns 404 once a profile exists.
- **Logging in:** `/login` lists active users; pick one (no password — dev mode only). Create further users at `/users` (approver only).
- **Resetting dev:** stop the server, delete `cairn.db`, run `uv run alembic upgrade head`, restart and go through `/setup` again.

## 3. Staging / reference deployment (Docker Compose)

`docker-compose.yml` is the reference deployment: the application image plus PostgreSQL 17 with a healthcheck-gated startup and a named volume (`cairn-db-data`). This stack is also the quarterly restore-test target.

```sh
docker compose up -d --build             # build image, start app (:8000) + postgres
docker compose run --rm app alembic upgrade head    # apply migrations (not automatic)
curl http://localhost:8000/healthz       # {"status": "ok", "version": …}
```

| Task | Command |
|---|---|
| Start / start after reboot | `docker compose up -d` |
| Apply migrations | `docker compose run --rm app alembic upgrade head` — run after every image update, before relying on the app |
| Tail logs | `docker compose logs -f app` (logs go to stdout/stderr; collect with the estate's tooling) |
| Stop (data kept) | `docker compose down` |
| Stop **and destroy data** | `docker compose down -v` — deletes the `cairn-db-data` volume; only for disposable stacks or after a verified backup |
| Rebuild after code change | `docker compose up -d --build` |
| Database shell | `docker compose exec db psql -U cairn cairn` |
| Ad-hoc backup | `docker compose exec db pg_dump -U cairn cairn > backup.sql` |

The compose file sets `DATABASE_URL` for the app service; add `SESSION_SECRET` (and, once OIDC exists, the auth configuration) via an override file or estate secret store rather than editing the checked-in file.

## 4. Production

Production runs the **same image** on the organisation's estate; TLS termination, secrets, network controls and backups are supplied by the estate (Solution & Security Architecture). The container serves plain HTTP on port 8000 and must sit behind the estate's TLS proxy.

**Deploy** (per the release process in `environments-devops.md` §3):

1. Releases are git tags `vX.Y.Z` on `main`, built into `cairn:X.Y.Z`. Deploy only tagged images, never `latest` or branch builds.
2. Pull the new image and run migrations first:
   `docker run --rm -e DATABASE_URL=… cairn:X.Y.Z alembic upgrade head`
3. Replace the running container with the new image (estate orchestration or `docker stop`/`docker run`).
4. Verify `GET /healthz` returns `{"status": "ok", "version": "X.Y.Z"}` — the version in the response confirms the right image is live. The image also carries a Docker `HEALTHCHECK` polling `/healthz` every 30s.

**Rollback:** redeploy the previous tag. **Migrations are forward-only** — never downgrade the schema in staging or production; a bad release rolls the app back one version (migrations are written to be backwards-compatible by one version), and a schema fix goes forward as a new migration.

**Stop:** stop the container via the estate's orchestration. The application is stateless apart from the database — signed cookies mean no session store, so containers can be stopped/replaced freely; in-flight requests aside, there is no drain procedure.

## 5. Routine management

| Task | How |
|---|---|
| Health / liveness | `GET /healthz` (no auth) — status + running version |
| User admin | `/users` (approver_dpo only): create, edit roles/functions, deactivate/reactivate. Users are **deactivated, never deleted** (NFRs) — deactivation blocks login, ends live sessions and removes them from pickers |
| Locked out / no approver | If the only approver is deactivated by DB mishap: set `is_active` back to true directly in the database (`UPDATE "user" SET is_active = true WHERE id = …`) — the app deliberately prevents self-deactivation to avoid this |
| Backups | Daily `pg_dump` / managed-service backup; 35 days rolling + 12 monthly (NFRs §4). SQLite dev DB is disposable, never backed up |
| Restore test | Quarterly: restore latest backup into the compose stack, run the pytest smoke suite and a manual register export, record the result (`environments-devops.md` §4) |
| Disaster recovery | Redeploy the image on any estate + restore the latest backup; RTO ≤ 1 business day, RPO ≤ 24h |
| Audit trail | All record changes are versioned in-app (`RecordVersion`/`AuditEvent` tables); exports, status changes, role changes and imports write audit events. The audit trail outlives the records it describes — never truncate these tables |
| Seed / legislation updates | Ship as versioned migrations through the normal release process — never manual SQL against a live database |

## 6. Known gaps (deliberate, tracked)

- **No OIDC yet** — `AUTH_MODE=dev` is the only working auth; the OIDC slice is scheduled before any staging deployment. Do not expose an instance beyond a trusted network until then.
- **Migrations are manual** — neither the image entrypoint nor compose runs `alembic upgrade head` automatically; it is a deliberate deploy step (§3/§4).
- **JSON structured logging** (NFRs §5) is not yet implemented — logs are uvicorn's default text format on stdout.
- **Image registry / signed releases / estate IaC** — decided with the first real deployment (`environments-devops.md` §5).

---

*Admin Reference v0.1 — update this document whenever the start/stop/deploy mechanics change (new auth mode, entrypoint migrations, logging).*
