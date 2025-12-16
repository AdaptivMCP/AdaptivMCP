# DISTRIBUTION: Shipping Adaptiv Controller as a bundle (tarball/zip)

This document describes how to package and ship the Adaptiv Controller GitHub MCP server
codebase to a customer as a self-contained tarball or zip archive, without giving them
direct access to the private git repository.

The goal is:

- Keep this repository private and under your control.
- Ship versioned source drops (for example `adaptiv-controller-v0.1.0.tar.gz`) to buyers.
- Let buyers self-host the MCP server using the normal self-hosting docs.

## 1. Prepare a tagged release

1. Ensure `main` is in a good, releasable state and all tests are green.
2. Decide on a version number (for example `v0.1.0`).
3. Create an annotated tag locally or via GitHub:

   ```bash
   git tag -a v0.1.0 -m "Adaptiv Controller v0.1.0"
   git push origin v0.1.0
   ```

## 2. Create a source tarball and/or zip

From your local clone (or a CI job), you can create archives that contain only the
tracked files at a given tag, without the `.git` history:

```bash

# Create a tar.gz bundle

git archive \
  --format=tar.gz \
  --prefix=adaptiv-controller-v0.1.0/ \
  v0.1.0 > adaptiv-controller-v0.1.0.tar.gz

# Optionally, also create a zip bundle

git archive \
  --format=zip \
  --prefix=adaptiv-controller-v0.1.0/ \
  v0.1.0 > adaptiv-controller-v0.1.0.zip
```

You can attach these archives to a private GitHub Release, store them in a private
object store, or deliver them to the buyer by whatever secure channel you use.

## 3. What the buyer receives

Each archive contains a directory like `adaptiv-controller-v0.1.0/` with:

- `main.py`, `github_mcp/`, and other server code.
- `dev-requirements.txt` / `pyproject.toml` for Python dependencies.
- `.env.example` listing all environment variables.
- `docs/` with self-hosting and workflow documentation.
- `LICENSE` with your proprietary license terms.

They do **not** receive your git history or the private repository itself, only the
source snapshot at the tagged version.

## 4. Buyer quickstart from a bundle

When a buyer receives `adaptiv-controller-v0.1.0.tar.gz` or `.zip`, their setup looks
like this (from their perspective):

```bash

# Unpack the bundle

tar xzf adaptiv-controller-v0.1.0.tar.gz
cd adaptiv-controller-v0.1.0

# Copy and edit environment config

cp .env.example .env

# (edit .env with their GitHub token, controller repo, etc.)

# Install dependencies

pip install -r dev-requirements.txt

# Run the MCP server locally

uvicorn main:app --host 0.0.0.0 --port 8000
```

From here, they follow the normal self-hosting docs (`docs/SELF_HOSTED_SETUP.md`,
`docs/SELF_HOSTING_DOCKER.md`) to deploy to Render or another platform and connect the
MCP server to their controller.

## 5. Licensing and terms

- The `LICENSE` file in the repository root describes the proprietary license terms
  that apply to the code in the bundle.
- Make sure the buyer has a corresponding commercial agreement or purchase record
  before sending them a bundle.
- The LICENSE makes it explicit that they may use and run the code for their own
  internal purposes, but may not redistribute or publish it.

## 6. Optional: per-buyer customization

If you want to customize bundles for specific buyers (for example, pre-configured
controller prompts, branding, or default settings), you can:

- Maintain small per-buyer patches or config files in a private area of the repo.
- Apply those changes on a short-lived branch, tag a release from that branch, and
  build a bundle from that tag.
- Clearly note in your commercial agreement what is buyer-specific vs. common.

In all cases, the core distribution mechanism remains the same: you create a tagged
source snapshot and ship it as a tarball/zip under your proprietary LICENSE.
