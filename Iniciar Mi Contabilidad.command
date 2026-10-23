#!/bin/zsh
cd -- "$(dirname -- "$0")"
./.venv/bin/python scripts/open_app.py
if [[ $? -ne 0 ]]; then
  echo 'Presiona Enter para cerrar.'
  read
fi
