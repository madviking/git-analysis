# Development

## Test-driven development (TDD)
Expected workflow for changes:
1) Add/extend a failing pytest test first (prefer non-mocking/integration tests when feasible).
2) Implement the smallest change to make the test pass.
3) Run the full test suite before finishing.

## Setup
```bash
uv sync --group dev
```

## Run tests
```bash
.venv/bin/python -m pytest
```

## Notes on tests
- Prefer creating real temporary git repos in tests (via `git init` + commits) over mocking subprocess output.
- For upload tests, use an in-process `http.server.HTTPServer` bound to `127.0.0.1` and assert on the received request.

