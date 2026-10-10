"""Persist factual desktop test evidence, including explicit skips."""
from datetime import datetime, timezone
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.loadTestsFromName("desktop.test_runtime")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    versions = {}
    for package in ("waitress", "pywebview", "pythonnet", "whitenoise"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    report = {"checked_utc": datetime.now(timezone.utc).isoformat(),
              "status": "passed" if result.wasSuccessful() and not result.skipped else "passed_with_skips" if result.wasSuccessful() else "failed",
              "tests_run": result.testsRun,
              "failures": [{"test": str(test), "detail": detail} for test, detail in result.failures],
              "errors": [{"test": str(test), "detail": detail} for test, detail in result.errors],
              "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
              "python": platform.python_version(), "versions": versions,
              "business_database_opened": False, "real_ai_called": False,
              "real_gui_verified": False, "transcript": stream.getvalue()}
    output = Path(__file__).parent / "evidence" / "runtime-unit-tests.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "tests_run": result.testsRun,
                      "skipped": len(result.skipped), "output": str(output)}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
