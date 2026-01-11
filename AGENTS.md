# Agent guidelines (git-analysis)

## Core expectations
- Follow TDD: write failing pytest tests first, then implement.
- Prefer non-mocking tests (real temporary git repos, real HTTP server for uploads) unless truly impractical.
- Run the full test suite (`.venv/bin/python -m pytest`) before finishing any change.
- Keep documentation current: update `README.md` and relevant files under `docs/` when behavior or interfaces change.
- Record updats in CHANGELOG.md

## Repo conventions
- Keep changes minimal and focused.
- Avoid introducing new dependencies unless necessary.
- Keep output deterministic where possible (stable JSON encoding, stable ordering).

## Useful commands
- Install dev deps: `uv sync --group dev`
- Run tests: `.venv/bin/python -m pytest`

## Virtualenv (`.venv`)
- This repo uses a project-local virtualenv at `.venv/` (created/managed via `uv`).
- Use `.venv/bin/python` (and `.venv/bin/pytest`, if needed) to avoid ambiguity with system Python.
- If `.venv/` is missing or stale, recreate it with `uv sync --group dev` (then re-run tests with `.venv/bin/python -m pytest`).
