#!/usr/bin/env python3
"""Select changed root-level components for the calling repository's CI."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('changed_files', type=Path)
    args = parser.parse_args()
    files = args.changed_files.read_text().splitlines()
    components = sorted({
        file.split('/')[0] for file in files
        if '/' in file and not file.startswith('.')
        and (Path(file.split('/')[0]).is_dir() or not Path(file.split('/')[0]).exists())
    })
    # Changes to discovery or its inputs can affect every component. SDK
    # versions are the caller workflow's idf_versions input, already covered
    # by the .github/workflows/ watch.
    full_run = any(
        file in {
            '.idf_build_apps.toml', '.build-test-rules.yml', 'pytest.ini', 'conftest.py',
        } or file.startswith(('.github/actions/', '.github/workflows/'))
        for file in files
    )
    outputs = {
        'modified_files': json.dumps([] if full_run else files),
        'modified_components': json.dumps([] if full_run else components),
        'has_changes': str(full_run or bool(components)).lower(),
    }
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for key, value in outputs.items():
            output.write(f'{key}={value}\n')


if __name__ == '__main__':
    main()
