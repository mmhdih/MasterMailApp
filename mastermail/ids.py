"""Turn whatever the user pastes into a clean, ordered list of seller ids."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import to_ascii_digits

_SPLIT_RE = re.compile(r"[\s,،;؛|/\\]+")
_VALID_RE = re.compile(r"^[A-Za-z0-9\-_]{1,40}$")


@dataclass
class ParsedIds:
    ids: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ids": self.ids, "duplicates": self.duplicates, "invalid": self.invalid}


def normalise_id(value: object) -> str:
    text = to_ascii_digits(str(value if value is not None else "")).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def parse_ids(text: str) -> ParsedIds:
    """Split on any common separator; drop blanks, keep first occurrence order."""
    result = ParsedIds()
    seen: set[str] = set()
    for token in _SPLIT_RE.split(to_ascii_digits(text or "")):
        token = normalise_id(token.strip("\"'`()[]{}<>"))
        if not token:
            continue
        if not _VALID_RE.match(token):
            result.invalid.append(token)
            continue
        if token in seen:
            result.duplicates.append(token)
            continue
        seen.add(token)
        result.ids.append(token)
    return result
