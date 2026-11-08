"""CHANGELOG.md: every release has notes, and the script finds the right ones."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog", ROOT / "scripts" / "changelog.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_manifest_version_has_release_notes() -> None:
    """Bump the version without writing its notes and this fails before any tag."""
    manifest = json.loads(
        (ROOT / "custom_components" / "pulse_check" / "manifest.json").read_text(encoding="utf-8")
    )
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _script().section(text, manifest["version"]), (
        f"CHANGELOG.md needs a '## {manifest['version']}' section"
    )


def test_a_section_runs_to_the_next_version_only() -> None:
    changelog = _script()
    text = "# Changelog\n\n## 1.2.0 - 2026-11-08\n\n- New\n\n## 1.1.0 - 2026-11-01\n\n- Old\n"
    assert changelog.section(text, "1.2.0") == "- New"
    assert changelog.section(text, "1.1.0") == "- Old"
    # 1.1 is not 1.1.0, and a missing version has no notes.
    assert changelog.section(text, "1.1") is None
    assert changelog.section(text, "9.9.9") is None
