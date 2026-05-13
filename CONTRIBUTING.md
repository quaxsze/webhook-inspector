# Contributing to webhook-inspector

Thanks for considering a contribution. This is a learning-focused side-project — contributions are welcome but please read this first.

## Project status

This is a personal learning project to practice DevOps on GCP. The maintainer reserves the right to refuse contributions that don't align with the learning goals or the design philosophy in [`docs/specs/`](docs/specs/).

If you're unsure whether a change is welcome, **open an issue first** to discuss.

## Development setup

Requires:
- Python 3.13 (`pyenv install 3.13`)
- [uv](https://github.com/astral-sh/uv) for dependency management
- Docker + docker-compose (for running the stack locally)

```bash
git clone https://github.com/quaxsze/webhook-inspector.git
cd webhook-inspector
uv sync
uv run pre-commit install   # one-time, sets up git hooks
make up                      # starts the full stack on docker-compose
make test                    # runs unit + integration tests
```

## Branch strategy

- `main` is the deployment branch — every merge triggers a production deploy via GitHub Actions
- Open a PR from a feature branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`, etc.)
- Squash-merge into `main` once CI is green

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation changes
- `refactor:` code change that neither fixes a bug nor adds a feature
- `test:` adding or fixing tests
- `chore:` tooling, dependencies, CI
- `style:` formatting, no logic change
- `ci:` CI configuration

Scopes are encouraged: `feat(web):`, `fix(infra):`, `test(domain):`.

## Code quality

Before submitting a PR, ensure:

```bash
make lint        # ruff check + format
make type        # mypy strict
make test        # full test suite
```

The pre-commit hook will catch most issues automatically.

## Architecture

See [`docs/specs/`](docs/specs/) for the design rationale and [`docs/plans/`](docs/plans/) for past implementation plans. The architecture follows:

- Clean Architecture (domain / application / infrastructure / web layers)
- Test-Driven Development (write the failing test before the implementation)
- Conventional Commits

Look at existing tests (`tests/unit/`, `tests/integration/`) for patterns before adding new code.

## What we welcome

- Bug fixes with a regression test
- Documentation improvements
- New tests for under-tested areas
- DevOps improvements (CI speedups, infra hardening, observability)

## What we typically refuse

- Pure styling / refactor PRs without a clear benefit
- New features that aren't in the roadmap (open an issue first)
- Changes that break tests or weaken type safety

## Branch protection (maintainer)

The `main` branch should have the following rules configured (Settings → Branches in the GitHub UI):

- Require a pull request before merging
- Require status checks to pass before merging:
  - `lint`
  - `type`
  - `unit`
  - `integration`
- Require linear history (squash-merges only)
- Require conversation resolution before merging

These rules can't be enforced from the repo — they live in GitHub's repo settings. The settings are documented here so a new maintainer (or future-you on a new machine) knows what state is expected.

## Questions

Open a [discussion](https://github.com/quaxsze/webhook-inspector/discussions) or an issue tagged `question`.
