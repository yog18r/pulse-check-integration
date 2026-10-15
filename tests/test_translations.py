"""Translations: every language has every string, with the same placeholders."""

from __future__ import annotations

import json
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.pulse_check.messages import (
    MESSAGES_DIR,
    Catalog,
    load_messages,
    pick_language,
    plural_category,
)
from tests.test_notify import BATTERY, _local, _messages, _ready, _set_up, _tick

INTEGRATION = Path(__file__).parent.parent / "custom_components" / "pulse_check"
STRINGS = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
LANGUAGES = ("de", "fr", "es", "nl", "it", "pt-BR", "pl", "zh-Hans", "cs")


def _flatten(value: Any, path: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        flat: dict[str, str] = {}
        for key, child in value.items():
            flat.update(_flatten(child, f"{path}.{key}" if path else key))
        return flat
    return {path: value}


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _forms(template: str | dict[str, str]) -> dict[str, str]:
    return template if isinstance(template, dict) else {"": template}


# -- Home Assistant's own translation files -----------------------------------


def test_english_is_strings_json() -> None:
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    assert english == STRINGS


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_has_every_dialog_and_entity_string(language: str) -> None:
    path = INTEGRATION / "translations" / f"{language}.json"
    translated = _flatten(json.loads(path.read_text(encoding="utf-8")))
    english = _flatten(STRINGS)
    assert translated.keys() == english.keys()
    for key, text in english.items():
        assert translated[key].strip(), key
        assert _placeholders(translated[key]) == _placeholders(text), key


# -- the notification catalogs ------------------------------------------------


def test_languages_fall_back_sensibly() -> None:
    available = ["en", "de", "pt-BR", "zh-Hans"]
    assert pick_language("de", available) == "de"
    assert pick_language("de-CH", available) == "de"
    assert pick_language("pt", available) == "pt-BR"
    assert pick_language("PT-br", available) == "pt-BR"
    assert pick_language("zh-Hant", available) == "zh-Hans"
    assert pick_language("ja", available) == "en"


def test_plural_categories_follow_cldr() -> None:
    assert [plural_category("en", n) for n in (0, 1, 2)] == ["other", "one", "other"]
    assert [plural_category("fr", n) for n in (0, 1, 2)] == ["one", "one", "other"]
    assert [plural_category("pl", n) for n in (1, 2, 5, 12, 22, 25)] == [
        "one",
        "few",
        "many",
        "many",
        "few",
        "many",
    ]
    assert [plural_category("cs", n) for n in (1, 3, 5)] == ["one", "few", "other"]
    assert plural_category("zh-Hans", 1) == "other"


def test_every_language_has_every_message() -> None:
    messages = load_messages()
    english: dict[str, Any] = json.loads((MESSAGES_DIR / "en.json").read_text(encoding="utf-8"))
    assert set(messages.languages) == {"en", *LANGUAGES}
    for language in LANGUAGES:
        catalog = json.loads((MESSAGES_DIR / f"{language}.json").read_text(encoding="utf-8"))
        assert catalog.keys() == english.keys(), language
        for key, template in english.items():
            wanted = set().union(*map(_placeholders, _forms(template).values()))
            forms = _forms(catalog[key])
            if isinstance(template, dict):
                # Every category the language uses for whole numbers is there.
                needed = {plural_category(language, n) for n in range(200)}
                assert needed <= forms.keys(), (language, key)
            for text in forms.values():
                assert text.strip(), (language, key)
                assert _placeholders(text) - {"count"} == wanted - {"count"}, (language, key)


def test_a_missing_key_reads_english() -> None:
    english = json.loads((MESSAGES_DIR / "en.json").read_text(encoding="utf-8"))
    half_finished = Catalog("pl", {"level_low": "zgłasza niski"}, english)
    assert half_finished("issue_offline", name="Lock") == "Lock: offline"
    assert half_finished("level_low") == "zgłasza niski"
    # English has no "few" form: a missing category falls back to "other".
    assert half_finished("reminder", count=3, message="x") == "Still unresolved after 3 days. x"


# -- the language actually used -------------------------------------------------


async def test_messages_follow_the_language_setting(
    hass: HomeAssistant,
    fixture_snapshot: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    fixed_now: datetime,
) -> None:
    """Changing the language needs no restart: each message is worded as it is sent."""
    await hass.config.async_update(language="de")
    _, _, calls = await _set_up(hass, fixture_snapshot, freezer, fixed_now)
    await _ready(hass, freezer)
    german = load_messages().catalog("de")

    hass.states.async_set("sensor.kitchen_ht_battery", "5", BATTERY)
    await _tick(hass, freezer, timedelta(seconds=11))
    level = german("level_percent", level=5)
    assert _messages(calls) == [german("issue_battery_critical", name="Kitchen H&T", level=level)]
    assert calls[0].data["data"]["actions"][0]["title"] == german("action_mark_replaced")

    await hass.config.async_update(language="pl")
    await _tick(hass, freezer, _local(15, 9, 1) - fixed_now)
    polish = load_messages().catalog("pl")
    weekly = [m for m in _messages(calls) if m.startswith(polish("digest_weekly"))]
    assert len(weekly) == 1, _messages(calls)  # Thursday is the weekly digest day
