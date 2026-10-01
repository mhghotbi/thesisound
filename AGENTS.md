# Repository instructions

Thesisound is a Python 3.12+ project for building evidence-grounded Persian educational podcasts.

## Working in this repository

- Read `README.md` and the relevant product or design notes before changing user-facing behavior.
- Keep source code under `src/thesisound`; preserve Persian text and Unicode in prompts, fixtures, and documentation.
- Use `uv` for project commands. The web app starts with `uv run thesisound-web`.
- Run focused checks for the files changed, using the project configuration in `pyproject.toml`.
- Skills shared with Codex live under `.agents/skills/`; use their `SKILL.md` files when they apply.
