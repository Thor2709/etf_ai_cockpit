"""One label per stock sector (GICS sector names) and per country, so peer cohorts do not split."""

from __future__ import annotations

GICS_SECTORS = (
    "Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials", "Health Care",
    "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities",
)
# Yahoo sector names and stray config spellings (keys casefolded). Other labels, such as the bank
# exclusion label "Banks", are kept as given.
_SECTORS = {name.casefold(): name for name in GICS_SECTORS} | {
    "financial services": "Financials",
    "financial exchanges": "Financials",
    "basic materials": "Materials",
    "technology": "Information Technology",
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "healthcare": "Health Care",
    "communication": "Communication Services",
    "unknown": "",
}
_COUNTRY_ALIASES = {
    "korea (south)": "South Korea",
    "korea, republic of": "South Korea",
    "kr": "South Korea",
    "taiwan region": "Taiwan",
    "cayman island": "Cayman Islands",
    "hk": "Hong Kong",
    "gb": "United Kingdom",
}
# Each canonical name is a key too, so its other spellings ("south korea") give the same label.
_COUNTRIES = {name.casefold(): name for name in _COUNTRY_ALIASES.values()} | _COUNTRY_ALIASES


def sector_label(value: str | None) -> str:
    text = (value or "").strip()
    return _SECTORS.get(text.casefold(), text)


def country_label(value: str | None) -> str:
    text = (value or "").strip()
    return _COUNTRIES.get(text.casefold(), text)
