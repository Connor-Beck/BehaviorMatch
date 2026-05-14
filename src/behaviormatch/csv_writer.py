from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .schema import Event, Session


def write_csv_bundle(session: Session, output_dir: str | Path, stem: str | None = None) -> tuple[Path, ...]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = stem or session.base_name

    trials_path = output_dir / f"{prefix}_trials.csv"
    events_path = output_dir / f"{prefix}_events.csv"
    sensor_events_path = output_dir / f"{prefix}_sensor_events.csv"
    summary_path = output_dir / f"{prefix}_summary.json"

    _write_dict_rows(trials_path, [trial.attrs() for trial in session.trials])
    _write_dict_rows(
        events_path,
        [_event_dict(event) for event in session.events],
        fieldnames=["t_session_s", "pc_ts", "kind", "mega_us", "tag", "value", "raw_text", "source"],
    )
    _write_dict_rows(
        sensor_events_path,
        _sensor_event_rows(session),
        fieldnames=["trial_index", "t_session_s", "t_trial_s", "sensor", "mega_us"],
    )
    _write_json(summary_path, _summary_dict(session))

    return trials_path, events_path, sensor_events_path, summary_path


def _write_dict_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or _fieldnames(rows)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    tmp_path.replace(path)


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        "t_session_s": event.t_session_s,
        "pc_ts": event.pc_ts,
        "kind": event.kind,
        "mega_us": event.mega_us,
        "tag": event.tag,
        "value": event.value,
        "raw_text": event.raw_text,
        "source": event.source,
    }


def _sensor_event_rows(session: Session) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in session.trials:
        for row in trial.sensor_events:
            merged = {"trial_index": trial.trial_index}
            merged.update(row)
            rows.append(merged)
    return rows


def _summary_dict(session: Session) -> dict[str, Any]:
    return {
        "base_name": session.base_name,
        "source_log": str(session.source_log),
        "attrs": session.attrs(),
        "parse_errors": session.parse_errors,
        "corrections_applied": session.corrections_applied,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    tmp_path.replace(path)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(str(item) for item in value)
    return value
