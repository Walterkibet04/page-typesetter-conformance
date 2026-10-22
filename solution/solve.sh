#!/bin/bash
set -e
cp "$(dirname "$0")/folio.py" /app/folio.py
python3 /app/tools/check_samples.py
