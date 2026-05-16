from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Type

from .schema import SessionFileGroup, parse_key_values


LEGACY_STAGE_RE = re.compile(
    r"^Freelymoving_(?P<mouse>.+?)_tr(?P<stage>\d)_(?P<mmdd>\d{4})_.*$",
    re.IGNORECASE,
)
TASK_NAME_RE = re.compile(
    r"^Freelymoving_(?P<mouse>.+?)_(?P<task>habituation|cue_wm|alternation_wm|discrimination|wm_behavior)_(?P<mmdd>\d{4})_.*$",
    re.IGNORECASE,
)


def _message_from_row(row: list[str]) -> str:
    if not row:
        return ""
    if row[0].strip().lower() == "pc_ts":
        return ""
    if len(row) >= 3:
        return ",".join(row[2:]).strip()
    if len(row) >= 2:
        return ",".join(row[1:]).strip()
    return row[-1].strip()


def _read_messages(path: Path, limit: int = 200) -> list[str]:
    messages: list[str] = []
    with path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        for row in reader:
            msg = _message_from_row(row)
            if msg:
                messages.append(msg)
            if len(messages) >= limit:
                break
    return messages


def identify(group: SessionFileGroup) -> tuple[str, str, Type]:
    """Return `(firmware, firmware_version, extractor_class)` for a session."""
    from .extractors.codev4_4 import CodeV44Extractor
    from .extractors.codev4_5 import CodeV45Extractor
    from .extractors.mega_sync import MegaSyncExtractor
    from .extractors.wm_behavior import WMBehaviorExtractor

    if group.primary_log == group.mega_sync and group.console_log is None and group.behavior_log is None:
        return "MegaSync", "mega_sync", MegaSyncExtractor

    messages = _read_messages(group.primary_log)

    for line in messages:
        if line.startswith("WM_META"):
            values = parse_key_values(line)
            version = values.get("firmware_version", "wm_behavior")
            return "WM_behavior", version, WMBehaviorExtractor

    if TASK_NAME_RE.match(group.base_name):
        return "WM_behavior", "wm_behavior", WMBehaviorExtractor

    if LEGACY_STAGE_RE.match(group.base_name):
        # The v0.2.6 filenames are the only definitive signal for CodeV4_4.
        return "CodeV4_4", "v0.2.6", CodeV44Extractor

    fingerprint = "\n".join(messages[:80])
    if "WM_TRIAL_START" in fingerprint:
        return "WM_behavior", "wm_behavior", WMBehaviorExtractor
    if "TRIAL_START_INDEX" in fingerprint:
        return "CodeV4_5", "codev4_5", CodeV45Extractor
    if ">>> RANDOM CUE TRIAL" in fingerprint or ("Cue1:" in fingerprint and "Total trial" in fingerprint):
        return "CodeV4_4", "v0.2.6", CodeV44Extractor

    return "WM_behavior", "unknown", WMBehaviorExtractor
