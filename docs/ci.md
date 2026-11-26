# CI pipeline

Workflow: `.github/workflows/ci.yml`. Branch flow: feature branch → PR into `develop` → release PR `develop` → `main` (squash) → tag `vX.Y.Z`.

## What runs where

| Job | PR → `develop` | PR → `main` (release) | push `develop` | push `main` / tag `v*` |
|---|---|---|---|---|
| Lint, format and tests | always | always | always | always |
| Migrations | only if `alembic/`, `alembic.ini`, `app/models/`, `requirements.txt` or `ci.yml` changed | always | – | – |
| UI contract | only if `app/` or `ci.yml` changed | always | – | – |
| Docker image | – | – | – | always |

The `Detect changes` job compares the PR merge commit with its first parent, so the filter sees exactly what the PR changes. Release PRs skip the filter on purpose: everything that ships to `main` gets the full check.

## Jobs

**Migrations** (PostgreSQL 15 service):
1. `alembic upgrade head` on an empty database.
2. `alembic check`: the SQLAlchemy models must match the schema the migrations build.
3. The default system roles must be seeded (at least 5).
4. `alembic downgrade base` then `alembic upgrade head`: every downgrade must work and leave nothing behind.

**UI contract**: generates this branch's OpenAPI spec, checks out `tm-portal-ui@develop` and runs its `scripts/check-api-contract.mjs`, which fails if any UI call (method + path) no longer exists in the API. The UI repo runs the same check the other way round.

Run the migration steps locally against a scratch database:

```bash
export DATABASE_URL=postgresql+asyncpg://taskmanager:taskmanager_dev@127.0.0.1:5432/scratch
alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head
```

## Why these checks exist

Issues found on 2026-11-26 while setting up a fresh local environment, and what each one led to:

| # | Issue | Check added |
|---|---|---|
| 1 | In the GitLab copy of this repo, migration `eab3482e0963` dropped tables and indexes that a fresh database does not have, so `alembic upgrade head` failed. | Upgrade an empty database |
| 2 | In the same copy, the `User` model had `failed_login_count` / `locked_until` but no migration created them; creating the admin crashed on a fresh database. | `alembic check` |
| 3 | A fresh database had no system roles, so project members (even owners) got no project permissions. Fixed by migration `c7d1e2f3a4b5`. | Default roles are seeded |
| 4 | Building this job, `alembic check` found drift on `develop`: the `ai_metrics.created_at` index was missing from the model, and the `id` indexes of `ai_metrics` / `pipeline_executions` were missing from the migrations. Fixed by migration `402e7a61059c` and the model. | `alembic check` |
| 5 | Building this job, `alembic downgrade base` failed: five migrations dropped foreign keys with `op.drop_constraint(None, ...)`. Fixed by naming them. | Downgrade and upgrade again |
| 6 | The API and the UI live in separate repos and are released separately; nothing stopped an endpoint the UI calls from being renamed, removed or changing method. First run: all 94 UI calls match. | UI contract (both repos) |

A full-stack smoke test (all services + browser, e.g. the Kanban drag offset bug fixed in tm-portal-ui v1.0.3) was considered and deferred: it costs much more to build and run than these checks.
