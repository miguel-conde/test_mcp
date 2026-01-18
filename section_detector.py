"""Section detection helpers for markdown and structured text."""

from __future__ import annotations

import re
from typing import Any, Dict, List

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def detect_sections(text: str, *, max_level: int = 6) -> List[Dict[str, Any]]:
    """Detect markdown headings in text and return section metadata.

    Args:
        text: Source text to scan for headings.
        max_level: Maximum heading level to include (1-6).

    Returns:
        List of section dicts with level, title, start_offset, end_offset.

    Raises:
        ValueError: If max_level is not positive.
    """
    if max_level < 1:
        raise ValueError("max_level must be positive")

    sections: List[Dict[str, Any]] = []
    for match in HEADING_PATTERN.finditer(text):
        level = len(match.group(1))
        if level > max_level:
            continue
        sections.append(
            {
                "level": level,
                "title": match.group(2).strip(),
                "start_offset": match.start(),
            }
        )

    # Calculate end offsets (start of next section or end of text)
    for idx, section in enumerate(sections):
        section["end_offset"] = sections[idx + 1]["start_offset"] if idx + 1 < len(sections) else len(text)

    return sections
