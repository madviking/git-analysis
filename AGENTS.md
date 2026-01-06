# Agent guidelines (git-analysis)

## Core expectations
- Follow TDD: write failing pytest tests first, then implement.
- Prefer non-mocking tests (real temporary git repos, real HTTP server for uploads) unless truly impractical.
- Run the full test suite (`.venv/bin/python -m pytest`) before finishing any change.
- Keep documentation current: update `README.md` and relevant files under `docs/` when behavior or interfaces change.

## Repo conventions
- Keep changes minimal and focused.
- Avoid introducing new dependencies unless necessary.
- Keep output deterministic where possible (stable JSON encoding, stable ordering).

## Useful commands
- Install dev deps: `uv sync --group dev`
- Run tests: `.venv/bin/python -m pytest`

