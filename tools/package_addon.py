#!/usr/bin/env python3
"""Package source files without modifying or cleaning the checkout."""
import subprocess
import sys
import zipfile
from pathlib import Path


def build(source, target):
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            # A linked development add-on writes per-installation metadata and
            # user files into this directory. Never distribute that local state.
            if (path.is_file() and path.suffix != '.pyc'
                    and not any(part in ('__pycache__', 'user_files', 'meta.json') or part.startswith('.')
                                for part in relative.parts)):
                archive.write(path, relative)


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / 'tools/build_api_contract.py'), '--check'], check=True)
    build(root / 'plugin', root / 'AnkiConnect.zip')


if __name__ == '__main__':
    main()
