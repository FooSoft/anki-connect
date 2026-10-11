#!/usr/bin/env python3
"""Package source files without modifying or cleaning the checkout."""
import runpy
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
runpy.run_path(str(root / 'tools/build_api_contract.py'), run_name='__main__')
with zipfile.ZipFile(root / 'AnkiConnect.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((root / 'plugin').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            archive.write(path, path.relative_to(root))
