from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .schema import Event, Session


STR_DTYPE = h5py.string_dtype(encoding="utf-8")


def _attr_value(value: Any) -> Any:
    if value is None:
        return "NA"
    if isinstance(value, Path):
        return str(value)
    return value


def _write_attrs(group: h5py.Group, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        group.attrs[key] = _attr_value(value)


def _event_array(events: list[Event]) -> np.ndarray:
    dtype = np.dtype(
        [
            ("t_session_s", "<f8"),
            ("pc_ts", "<f8"),
            ("kind", STR_DTYPE),
            ("mega_us", "<i8"),
            ("tag", STR_DTYPE),
            ("value", STR_DTYPE),
            ("raw_text", STR_DTYPE),
            ("source", STR_DTYPE),
        ]
    )
    arr = np.empty(len(events), dtype=dtype)
    for i, event in enumerate(events):
        arr[i] = (
            event.t_session_s,
            event.pc_ts,
            event.kind,
            event.mega_us,
            event.tag,
            event.value,
            event.raw_text,
            event.source,
        )
    return arr


def _create_dataset(group: h5py.Group, name: str, arr: np.ndarray) -> None:
    kwargs = {"compression": "gzip", "compression_opts": 4} if len(arr) else {}
    group.create_dataset(name, data=arr, **kwargs)


def _write_events(group: h5py.Group, name: str, events: list[Event]) -> None:
    _create_dataset(group, name, _event_array(events))


def _rows_array(rows: list[dict[str, Any]], dtype: np.dtype, columns: list[str]) -> np.ndarray:
    arr = np.empty(len(rows), dtype=dtype)
    for i, row in enumerate(rows):
        arr[i] = tuple(row.get(col, "" if dtype.fields[col][0].kind == "O" else -1) for col in columns)
    return arr


def _write_sensor_events(group: h5py.Group, rows: list[dict[str, Any]]) -> None:
    dtype = np.dtype(
        [
            ("t_session_s", "<f8"),
            ("t_trial_s", "<f8"),
            ("sensor", STR_DTYPE),
            ("mega_us", "<i8"),
        ]
    )
    arr = _rows_array(rows, dtype, ["t_session_s", "t_trial_s", "sensor", "mega_us"])
    _create_dataset(group, "sensor_events", arr)


def _write_timing(session_group: h5py.Group, session: Session) -> None:
    timing = session_group.create_group("timing")
    if session.timing.hardware_frames is not None:
        dtype = np.dtype(
            [
                ("frame_number", "<i8"),
                ("t_session_s", "<f8"),
                ("pc_ts", "<f8"),
                ("uno_edge_us", "<i8"),
                ("dropped_reported", "u1"),
                ("debounced", "u1"),
            ]
        )
        _create_dataset(
            timing,
            "hardware_frames",
            _rows_array(
                session.timing.hardware_frames,
                dtype,
                ["frame_number", "t_session_s", "pc_ts", "uno_edge_us", "dropped_reported", "debounced"],
            ),
        )

    if session.timing.behavior_frames_mkv is not None:
        dtype = np.dtype(
            [
                ("mkv_frame_i", "<i8"),
                ("t_session_s", "<f8"),
                ("pc_ts", "<f8"),
                ("rel_ms", "<f8"),
                ("hardware_frame_number", "<i8"),
                ("is_orphan", "u1"),
            ]
        )
        _create_dataset(
            timing,
            "behavior_frames_mkv",
            _rows_array(
                session.timing.behavior_frames_mkv,
                dtype,
                ["mkv_frame_i", "t_session_s", "pc_ts", "rel_ms", "hardware_frame_number", "is_orphan"],
            ),
        )

    if session.timing.mini2p_frames is not None:
        dtype = np.dtype(
            [
                ("frame_number", "<i8"),
                ("t_session_s", "<f8"),
                ("pc_ts", "<f8"),
                ("uno_edge_us", "<i8"),
                ("dropped_reported", "u1"),
            ]
        )
        _create_dataset(
            timing,
            "mini2p_frames",
            _rows_array(
                session.timing.mini2p_frames,
                dtype,
                ["frame_number", "t_session_s", "pc_ts", "uno_edge_us", "dropped_reported"],
            ),
        )

    if session.timing.mega_sync is not None:
        dtype = np.dtype(
            [
                ("uno_edge_us", "<i8"),
                ("mega_evt_us", "<i8"),
                ("mega_tag", STR_DTYPE),
                ("mega_value", STR_DTYPE),
                ("t_session_s", "<f8"),
                ("pc_skew_s", "<f8"),
                ("dropped_reported", "u1"),
            ]
        )
        _create_dataset(
            timing,
            "mega_sync",
            _rows_array(
                session.timing.mega_sync,
                dtype,
                ["uno_edge_us", "mega_evt_us", "mega_tag", "mega_value", "t_session_s", "pc_skew_s", "dropped_reported"],
            ),
        )

    corrections_group = timing.create_group("clock_corrections")
    _write_attrs(corrections_group, session.timing.clock_corrections.attrs())


def _write_trial_frames(trial_group: h5py.Group, trial) -> None:
    if trial.frames.mkv_frames:
        dtype = np.dtype(
            [
                ("mkv_frame_i", "<i8"),
                ("t_session_s", "<f8"),
                ("hardware_frame_number", "<i8"),
            ]
        )
        _create_dataset(
            trial_group,
            "mkv_frames",
            _rows_array(trial.frames.mkv_frames, dtype, ["mkv_frame_i", "t_session_s", "hardware_frame_number"]),
        )
    if trial.frames.mini2p_frames:
        dtype = np.dtype([("frame_number", "<i8"), ("t_session_s", "<f8")])
        _create_dataset(
            trial_group,
            "mini2p_frames",
            _rows_array(trial.frames.mini2p_frames, dtype, ["frame_number", "t_session_s"]),
        )


def write_h5(session: Session, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with h5py.File(tmp_path, "w") as h5:
        session_group = h5.create_group("session")
        _write_attrs(session_group, session.attrs())
        session_group.attrs["parse_errors"] = np.array(session.parse_errors, dtype=STR_DTYPE)
        session_group.attrs["corrections_applied"] = np.array(session.corrections_applied, dtype=STR_DTYPE)
        _write_events(session_group, "events", session.events)
        _write_timing(session_group, session)

        trials_group = h5.create_group("trials")
        for trial in session.trials:
            trial_group = trials_group.create_group(f"{trial.trial_index:04d}")
            _write_attrs(trial_group, trial.attrs())
            if trial.parse_errors:
                trial_group.attrs["parse_errors"] = np.array(trial.parse_errors, dtype=STR_DTYPE)
            _write_events(trial_group, "events", trial.events)
            _write_sensor_events(trial_group, trial.sensor_events)
            _write_trial_frames(trial_group, trial)

    tmp_path.replace(output_path)
    return output_path
