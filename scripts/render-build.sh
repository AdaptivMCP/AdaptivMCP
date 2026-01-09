#!/usr/bin/env sh
set -eu

# Verify vendored rg works
./vendor/rg/linux-x64/rg --version

python -m pip install --upgrade pip
pip install -r dev-requirements.txt
