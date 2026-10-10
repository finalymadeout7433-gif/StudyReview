"""One nonsecret path resolver shared by settings and local initialization tools."""
import json
import os
from pathlib import Path


def resolve_credentials_file(project_root):
    root = Path(project_root)
    environment_path = os.environ.get('STUDY_CREDENTIALS_FILE')
    if environment_path:
        return Path(environment_path)
    runtime_file = root / 'private' / 'runtime.json'
    if runtime_file.exists():
        runtime = json.loads(runtime_file.read_text(encoding='utf-8-sig'))
        if runtime.get('credentials_file'):
            return Path(runtime['credentials_file'])
    return root / 'private' / 'database-credentials.json'
