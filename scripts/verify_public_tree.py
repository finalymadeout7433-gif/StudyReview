"""Check publishable source or a source ZIP without displaying matching values."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

IGNORED = {'.git', '.venv', 'venv', '__pycache__', 'staticfiles', 'build', 'dist', '.pytest_cache'}
PRIVATE_DIRS = {'private', 'backups', 'uploads', 'media', 'logs', 'webview-profile', 'upload-temp'}
PRIVATE_NAMES = {'database-credentials.json', 'runtime.json', 'schema-plan.json',
                 'development-environment.json', 'django-secret.key', '.env'}
FORBIDDEN_SUFFIXES = {'.dpapi', '.log', '.sqlite', '.sqlite3', '.exe', '.msi', '.whl', '.zip', '.rar', '.7z', '.bak', '.dump', '.pyc'}
RULES = {
    'GitHub token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    'API key literal': re.compile(r'(?<![A-Za-z0-9_-])(?:sk-[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{30,})'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'personal Windows user directory': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+(?!Public(?:[\\/]|\b))[^\\/\s"\'<>]+', re.I),
    'original private data path': re.compile('拾习' + r'本机私有数据|数据库大作业[\\/]+拾习-v2|Documents[\\/]+Codex[\\/]+2026-10-03', re.I),
}
TEXT_SUFFIXES = {'.py', '.md', '.json', '.html', '.js', '.css', '.sql', '.yml', '.yaml', '.ps1', '.cmd', '.txt', '.spec', '.toml', '.ini', '.cfg', '.svg'}


def inspect(name: str, data: bytes) -> list[str]:
    path = Path(name)
    failures: list[str] = []
    if any(part.lower() in PRIVATE_DIRS for part in path.parts):
        failures.append(f'{name}: private directory')
    if path.name.lower() in PRIVATE_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        failures.append(f'{name}: forbidden published file')
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {'.gitignore', '.gitattributes', 'COPYRIGHT', 'LICENSE'}:
        return failures
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        try:
            text = data.decode('utf-16')
        except UnicodeError:
            return failures + [f'{name}: unrecognised text encoding']
    for label, pattern in RULES.items():
        for match in pattern.finditer(text):
            # Pattern declarations in this scanner have no actual credentials.
            failures.append(f'{name}:{text.count(chr(10), 0, match.start()) + 1}: {label}')
    if path.suffix.lower() == '.sql':
        if re.search(r'^\s*(?:INSERT\s+INTO|REPLACE\s+INTO|DROP\s+TABLE)\b', text, re.I | re.M):
            failures.append(f'{name}: SQL contains data or destructive table statement')
        if re.search(r'\bDEFINER\s*=|\bAUTO_INCREMENT\s*=\s*\d+', text, re.I):
            failures.append(f'{name}: SQL contains local definer or record counter')
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--git-history', action='store_true')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    failures: list[str] = []
    count = 0
    if args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            if archive.testzip():
                failures.append('ZIP CRC verification failed')
            names = archive.namelist()
            if len(names) != len(set(names)):
                failures.append('ZIP has duplicate entry names')
            for item in archive.infolist():
                if item.is_dir():
                    continue
                if '..' in Path(item.filename).parts or item.filename.startswith(('/', '\\')):
                    failures.append('ZIP contains unsafe entry path')
                    continue
                failures.extend(inspect(item.filename, archive.read(item)))
                count += 1
    else:
        root = args.root.resolve()
        for item in sorted(root.rglob('*')):
            relative = item.relative_to(root)
            if any(part in IGNORED for part in relative.parts) or not item.is_file():
                continue
            if item.is_symlink():
                failures.append(f'{relative.as_posix()}: symbolic link')
                continue
            failures.extend(inspect(relative.as_posix(), item.read_bytes()))
            count += 1
        if args.git_history:
            entries = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=root).decode('utf-8').splitlines()
            for entry in entries:
                oid, separator, name = entry.partition(' ')
                kind = subprocess.check_output(['git', 'cat-file', '-t', oid], cwd=root).strip()
                if kind == b'blob' and separator:
                    failures.extend(inspect('history/' + name, subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=root)))
                    count += 1
    if failures:
        for failure in sorted(set(failures)):
            print(failure)
        print(f'FAIL: {len(set(failures))} findings; matching contents were not printed.')
        return 1
    print(f'PASS: {count} files/blobs inspected; no configured publication blocker found.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
