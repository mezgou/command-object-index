# Project Guidelines

## Purpose

This repository is a prototype for a smart-home command system that accepts a natural-language text command and suggests the closest known command variants. The current MVP is intentionally simple and deterministic: there is no LLM inference, no command execution, and no multimodal understanding.

The goal is to keep the system easy to reason about, easy to test, and easy to extend.

## Architecture

### 1. Frontend

- Static UI served by nginx in `frontend/`
- `frontend/index.html` and `frontend/app.js` handle user interaction
- The browser calls the backend through `/api/` routes
- Keep the UI thin: presentation and user interaction only

### 2. Backend

- Python HTTP server in `backend/app/main.py`
- SQLite-backed storage lives under `/data/commands.db` in Docker volume
- API responsibilities are limited to:
  - list commands
  - add new commands
  - load example commands
  - delete commands
  - search and rank commands by similarity

### 3. Ranking logic

- The ranking algorithm lives in `backend/app/search.py`
- The current implementation is deterministic and transparent:
  - normalize whitespace and case
  - compute string distance
  - compute similarity as relative closeness
  - sort by similarity, then command text, then id
- This should remain human-auditable. Avoid introducing hidden heuristics or black-box ranking.

## Design principles

- Keep the MVP simple and explainable
- Prefer explicit, layered responsibilities over clever abstractions
- Favor standard-library Python and minimal external dependencies
- Treat the UI and backend as separate concerns even in early development
- Keep command matching understandable for a human reviewer
- The project is a human-in-the-loop system, not an autonomous command executor

## Coding conventions

- Use UTF-8 strings and Russian-language user-facing messages where appropriate
- Keep API payloads JSON-based and consistent
- Validate input strictly at the HTTP boundary
- Preserve normalization rules when changing search behavior
- Add or update tests when changing ranking logic or command validation
- Prefer small, deterministic functions over broad, stateful logic

## Testing and validation

Run the algorithm tests with:

```bash
python3 -m unittest discover -s backend/tests
```

For full app startup in Docker:

```bash
docker compose up --build
```

The app is then available at http://localhost:8080.

## Scope of the MVP

This prototype should stay focused on:

- command catalog management
- textual similarity search
- manual review of likely matches
- operational simplicity

Avoid adding production-grade features before the core behavior is stable, including:

- dynamic execution of real home devices
- heavy LLM orchestration
- multimodal ambiguity resolution
- complex authentication or multi-user systems

## Extension direction

If the project grows, keep the architecture layered:

1. Input handling and validation
2. Command storage and persistence
3. Ranking and intent extraction
4. Human review / confirmation layer
5. Device execution layer

That ordering keeps the system expandable without mixing concerns too early.

## Important constraints

- Do not replace the current deterministic ranking with opaque model-based behavior without a clear architecture split
- Do not couple frontend logic directly to search implementation details
- Do not add hidden global state in the search layer
- Do not broaden the scope beyond command normalization and candidate ranking in the MVP
