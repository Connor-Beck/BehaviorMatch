from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .schema import Event, Session


def _sanitize(value: Any) -> Any:
    if value is None:
        return np.array([])
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if not value:
            return np.array([])
        if all(isinstance(item, dict) for item in value):
            return _rows_to_columns(list(value))
        return [_sanitize(item) for item in value]
    return value


def _rows_to_columns(rows: list[dict[str, Any]]) -> dict[str, Any] | np.ndarray:
    if not rows:
        return np.array([])

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)

    return {
        column: [_sanitize(row.get(column)) for row in rows]
        for column in columns
    }


def _event_dict(events: list[Event]) -> dict[str, list[Any]]:
    return {
        "t_session_s": [event.t_session_s for event in events],
        "pc_ts": [event.pc_ts for event in events],
        "kind": [event.kind for event in events],
        "mega_us": [event.mega_us for event in events],
        "tag": [event.tag for event in events],
        "value": [event.value for event in events],
        "raw_text": [event.raw_text for event in events],
        "source": [event.source for event in events],
    }


def _trial_struct(trial) -> dict[str, Any]:
    """One trial as a struct (becomes one element of the trials struct array)."""
    data = dict(trial.attrs())
    data["events"] = _event_dict(trial.events)
    data["sensor_events"] = _rows_to_columns(trial.sensor_events)
    data["mkv_frames"] = _rows_to_columns(trial.frames.mkv_frames)
    data["mini2p_frames"] = _rows_to_columns(trial.frames.mini2p_frames)
    return _sanitize(data)


def _trials_struct_array(session: Session) -> np.ndarray:
    """Pack trials into a 1xN object array of dicts, which scipy.io.savemat
    serialises as a MATLAB struct array.
    """
    trial_dicts = [_trial_struct(trial) for trial in session.trials]
    if not trial_dicts:
        return np.empty((0,), dtype=object)
    out = np.empty((len(trial_dicts),), dtype=object)
    for i, td in enumerate(trial_dicts):
        out[i] = td
    return out


def session_to_mat_dict(session: Session) -> dict[str, Any]:
    session_root: dict[str, Any] = dict(session.attrs())
    session_root["parse_errors"] = list(session.parse_errors)
    session_root["corrections_applied"] = list(session.corrections_applied)
    session_root["events"] = _event_dict(session.events)
    session_root["timing"] = {
        "hardware_frames": _rows_to_columns(session.timing.hardware_frames or []),
        "behavior_frames_mkv": _rows_to_columns(session.timing.behavior_frames_mkv or []),
        "mini2p_frames": _rows_to_columns(session.timing.mini2p_frames or []),
        "mega_sync": _rows_to_columns(session.timing.mega_sync or []),
        "clock_corrections": session.timing.clock_corrections.attrs(),
    }
    session_root["trials"] = _trials_struct_array(session)
    return _sanitize({"session": session_root})


def write_mat(session: Session, output_path: str | Path) -> Path:
    try:
        from scipy.io import savemat
    except Exception as exc:
        raise RuntimeError("scipy is required for .mat export") from exc

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    savemat(tmp_path, session_to_mat_dict(session), do_compression=True)
    tmp_path.replace(output_path)
    return output_path
