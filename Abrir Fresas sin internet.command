#!/bin/zsh
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python scripts/local_app.py open
