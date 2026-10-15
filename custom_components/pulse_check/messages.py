"""Notification and digest text in the user's language.

Home Assistant translates an integration's dialogs, entity names and
services from `translations/<language>.json`, but only the categories it
knows about: hassfest validates those files against a fixed schema, and
`async_get_translations` loads a fixed set of categories. Text the
integration composes itself, such as "Kitchen H&T: battery low (28 %)" or
a digest heading, has no place there.

So those messages live beside them in `messages/<language>.json`, one flat
mapping of keys to `str.format` templates per language. They are read once
at setup (file I/O, so in the executor), and each message is made in
`hass.config.language` at the moment it is sent, so changing the language
in the user profile settings takes effect without a restart. A language
without a catalog falls back to its base language, then to a regional
variant of it (`pt` to `pt-BR`), then to English; a key missing from a
catalog falls back to English too.

A template whose wording depends on a number is a mapping of plural
categories (`one`, `few`, `many`, `other`, as in CLDR) instead of a string.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MESSAGES_DIR = Path(__file__).parent / "messages"
FALLBACK = "en"

type Template = str | dict[str, str]


def plural_category(language: str, n: int) -> str:
    """The CLDR plural category of a whole number, for the shipped languages.

    Only the integer rules are needed (counts of days). Languages not
    listed here use the English rule.
    """
    base = language.split("-", maxsplit=1)[0].lower()
    if base == "zh":
        return "other"
    if base in ("fr", "pt"):
        return "one" if n in (0, 1) else "other"
    if base == "pl":
        if n == 1:
            return "one"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if base == "cs":
        if n == 1:
            return "one"
        return "few" if n in (2, 3, 4) else "other"
    return "one" if n == 1 else "other"


def pick_language(language: str, available: Iterable[str]) -> str:
    """The best catalog for a Home Assistant language code such as `de` or `pt-BR`."""
    codes = {code.lower(): code for code in available}
    wanted = language.lower()
    if wanted in codes:
        return codes[wanted]
    base = wanted.split("-")[0]
    if base in codes:
        return codes[base]
    for lowered, code in sorted(codes.items()):
        if lowered.split("-")[0] == base:
            return code
    return FALLBACK


class Catalog:
    """The messages of one language, with English behind them."""

    def __init__(
        self, language: str, templates: Mapping[str, Template], fallback: Mapping[str, Template]
    ) -> None:
        """Keep both catalogs; nothing is formatted until asked."""
        self.language = language
        self._templates = templates
        self._fallback = fallback

    def __call__(self, key: str, /, count: int | None = None, **values: object) -> str:
        """Format one message. `count` picks the plural form and is also `{count}`."""
        template = self._templates.get(key) or self._fallback[key]
        if isinstance(template, dict):
            category = plural_category(self.language, count or 0)
            template = template.get(category) or template["other"]
        if count is not None:
            values.setdefault("count", count)
        return template.format(**values)


class Messages:
    """Every shipped catalog, loaded once."""

    def __init__(self, catalogs: Mapping[str, Mapping[str, Template]]) -> None:
        """Keep the catalogs by language code."""
        self._catalogs = catalogs

    def catalog(self, language: str) -> Catalog:
        """The messages for a Home Assistant language code."""
        code = pick_language(language, self._catalogs)
        return Catalog(code, self._catalogs[code], self._catalogs[FALLBACK])

    @property
    def languages(self) -> list[str]:
        """The language codes there is a catalog for."""
        return sorted(self._catalogs)


def load_messages(directory: Path = MESSAGES_DIR) -> Messages:
    """Read every `<language>.json` in the directory. Blocking: run in the executor."""
    catalogs: dict[str, dict[str, Template]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            catalogs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            _LOGGER.warning("Could not read the message catalog %s", path.name, exc_info=True)
    if FALLBACK not in catalogs:
        raise FileNotFoundError(f"{directory / (FALLBACK + '.json')} is missing")
    return Messages(catalogs)


async def async_load_messages(hass: HomeAssistant) -> Messages:
    """Load the catalogs without blocking the event loop."""
    return await hass.async_add_executor_job(load_messages)
