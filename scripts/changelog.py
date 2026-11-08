"""Print one version's section of CHANGELOG.md: the release notes for that version.

    python scripts/changelog.py 0.2.7 > release-notes.md

The release workflow publishes the output as the GitHub release's notes,
which HACS shows when it offers the update. A version with no section is an
error, so a release cannot go out without notes. GitHub's generated notes
list merged pull requests only, and most changes here are committed
directly, so they said almost nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(text: str, version: str) -> str | None:
    """The body under `## <version>` up to the next `## ` heading, or None."""
    heading = re.compile(rf"^## {re.escape(version)}(?:\s|$)")
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if heading.match(line):
            body: list[str] = []
            for following in lines[start + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following)
            return "\n".join(body).strip() or None
    return None


def main(argv: list[str]) -> int:
    """Print the section for the version in argv; 1 when there is none."""
    if len(argv) != 1:
        print("usage: changelog.py VERSION", file=sys.stderr)
        return 2
    version = argv[0].removeprefix("v")
    notes = section(CHANGELOG.read_text(encoding="utf-8"), version)
    if notes is None:
        print(f"CHANGELOG.md has no section for {version}", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
