# Contributing

## Development setup

- Install development dependencies: `make install-dev`
- (Optional) Install git hooks: `make precommit`

Optional but recommended tooling:

- `ripgrep` (binary `rg`) for fast codebase search.

Installation examples:

- macOS (Homebrew): `brew install ripgrep`
- Ubuntu/Debian: `sudo apt-get update && sudo apt-get install -y ripgrep`

## Common tasks

- Lint: `make lint`
- Format: `make format`
- Test: `make test`

## Pull requests

- Keep PRs small and focused.
- Ensure lint and tests pass before requesting review.
