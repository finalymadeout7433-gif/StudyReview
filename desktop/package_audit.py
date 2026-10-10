"""Read-only structural audit of an onedir folder. Never reads private contents.

The integrating agent owns the PyInstaller spec and release creation. This
helper checks the produced directory and records distribution boundaries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


PRIVATE_DIRECTORIES = {"private", ".venv", ".git", ".aws", ".codex", ".agents",
                       "webview-profile", "upload-temp", "ai-credentials"}
PRIVATE_FILENAMES = {"database-credentials.json", "django-secret.key", "desktop-state.json",
                     "runtime.json", ".env", "local.sqlite3", "desktop.lock"}


def inspect_package(directory: Path):
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError("程序包目录不存在。")
    forbidden = []
    manifest = []
    external_links = []
    stack = [directory]
    seen = {directory}
    candidates = []
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(directory)
                try:
                    resolved = path.resolve()
                    resolved.relative_to(directory)
                except ValueError:
                    external_links.append(relative.as_posix())
                    continue
                candidates.append(path)
                if entry.is_dir(follow_symlinks=False) and not path.is_junction():
                    # Refuse to descend private folders or an already-seen link.
                    if not {part.casefold() for part in relative.parts} & PRIVATE_DIRECTORIES and resolved not in seen:
                        seen.add(resolved)
                        stack.append(path)
                elif entry.is_dir():
                    external_links.append(relative.as_posix() + " (directory link not distributed)")
    for path in sorted(candidates):
        relative = path.relative_to(directory)
        pieces = {part.casefold() for part in relative.parts}
        is_private = (bool(pieces & PRIVATE_DIRECTORIES)
                      or path.name.casefold() in PRIVATE_FILENAMES
                      or path.name.casefold().endswith(".dpapi"))
        if is_private:
            forbidden.append(relative.as_posix())
            continue  # especially do not hash/read private file contents
        if path.is_file():
            with path.open("rb") as source:
                checksum = hashlib.file_digest(source, "sha256").hexdigest()
            manifest.append({"path": relative.as_posix(), "bytes": path.stat().st_size,
                             "sha256": checksum})
    executables = [item["path"] for item in manifest
                   if "/" not in item["path"] and item["path"].lower().endswith(".exe")]
    required_resources = {
        "templates": any(item["path"].endswith("templates/base.html") for item in manifest),
        "staticfiles": any("staticfiles/" in item["path"] for item in manifest),
        "licenses": any("license" in item["path"].lower() or "copying" in item["path"].lower()
                        for item in manifest),
        "root_executable": bool(executables),
    }
    return {"checked_utc": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if not forbidden and not external_links and all(required_resources.values()) else "failed",
            "audit_kind": "structure_and_file_hashes_only",
            "credentials_contents_read": False,
            "clean_other_computer_verified": False,
            "external_prerequisites": ["MySQL and configured database", "WebView2 Runtime", ".NET/VC++ runtime"],
            "forbidden_paths": forbidden, "outside_package_links": external_links,
            "required_resources": required_resources,
            "root_executables": executables, "files": manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读文件夹包结构核验，不读取私有文件内容")
    parser.add_argument("directory")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = inspect_package(Path(args.directory))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "files": len(report["files"]),
                      "forbidden": len(report["forbidden_paths"]),
                      "clean_other_computer_verified": False}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
