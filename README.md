# cairn
System for managing a Register of Processing Activity (ROPA) to meet the requirements of the UK ICO

Design documents live in `docs/` — see `CLAUDE.md` for how they fit together.

## Development setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                # create .venv and install dev dependencies
uv run alembic upgrade head            # create/upgrade the dev database (SQLite)
uv run uvicorn cairn.web:app --reload  # run on http://127.0.0.1:8000 (first visit runs /setup)
uv run pytest                          # run tests
uv run ruff check .
```

Start/stop/deploy for all environments: `docs/admin-reference.md`.
