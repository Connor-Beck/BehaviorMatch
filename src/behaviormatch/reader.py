"""Read parsed MouseMaze sessions.

Implements the reader API in docs/storage-spec.md §9 (parent repo).
Both standalone apps consume sessions via this module; no other reader
of <base>.h5 should exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd


MIN_PARSER_VERSION = "0.2.0"


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------

def _decode_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.ndarray) and value.dtype.kind in {"S", "O"}:
        return [v.decode("utf-8") if isinstance(v, bytes) else v for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _attrs_to_dict(attrs: h5py.AttributeManager) -> dict[str, Any]:
    return {k: _decode_attr(v) for k, v in attrs.items()}


def _compound_to_df(dataset: h5py.Dataset) -> pd.DataFrame:
    """Read an h5py compound dataset into a DataFrame, decoding bytes columns."""
    arr = dataset[:]
    if arr.dtype.names is None:
        return pd.DataFrame(arr)
    cols: dict[str, Any] = {}
    for name in arr.dtype.names:
        col = arr[name]
        if col.dtype.kind == "O":
            cols[name] = [v.decode("utf-8") if isinstance(v, bytes) else v for v in col]
        else:
            cols[name] = col
    return pd.DataFrame(cols)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(version).split("."):
        leading = ""
        for ch in piece:
            if ch.isdigit():
                leading += ch
            else:
                break
        if leading:
            parts.append(int(leading))
    return tuple(parts)


def _check_parser_version(parser_version: str, h5_path: Path) -> None:
    if _version_tuple(parser_version) < _version_tuple(MIN_PARSER_VERSION):
        raise ValueError(
            f"{h5_path}: parser_version {parser_version!r} is older than required "
            f"{MIN_PARSER_VERSION!r}; re-parse the session with the current parser."
        )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """In-memory view of one parsed session.

    Eager fields (trials, events, timing, clock_corrections, curation) are
    populated at load time; underlying H5 file handles are closed before this
    object is returned. Per-trial calcium / DLC / events tables are read on
    demand via the get_trial_*() methods.
    """

    session_dir: Path
    base_name: str
    h5_path: Path
    curation_h5_path: Path | None

    attrs: dict[str, Any]
    trials: pd.DataFrame
    events: pd.DataFrame
    timing: dict[str, pd.DataFrame]
    clock_corrections: dict[str, Any]
    parse_errors: list[str]

    curation: pd.DataFrame | None = None
    curation_attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def mouse_id(self) -> str:
        return str(self.attrs.get("mouse_id", ""))

    @property
    def task(self) -> str:
        return str(self.attrs.get("task", ""))

    @property
    def firmware(self) -> str:
        return str(self.attrs.get("firmware", ""))

    @property
    def parser_version(self) -> str:
        return str(self.attrs.get("parser_version", ""))

    @property
    def session_t0_unix(self) -> float:
        return float(self.attrs.get("session_t0_unix", 0.0))

    @property
    def session_iso(self) -> str:
        return str(self.attrs.get("session_iso", ""))

    @property
    def n_trials(self) -> int:
        return int(self.attrs.get("n_trials", 0))

    @property
    def has_blackfly(self) -> bool:
        return bool(self.attrs.get("has_blackfly", False))

    @property
    def has_mini2p(self) -> bool:
        return bool(self.attrs.get("has_mini2p", False))

    @property
    def has_hardware_frames(self) -> bool:
        return bool(self.attrs.get("has_hardware_frames", False))

    @property
    def has_mega_sync(self) -> bool:
        return bool(self.attrs.get("has_mega_sync", False))

    @property
    def parse_status(self) -> str:
        return str(self.attrs.get("parse_status", ""))

    # ---- Per-trial readers (open file briefly, then close) ----

    def _read_trial_dataset(self, trial_index: int, name: str) -> pd.DataFrame:
        group_name = f"{int(trial_index):04d}"
        with h5py.File(self.h5_path, "r") as h5:
            trials = h5.get("trials")
            if trials is None or group_name not in trials:
                return pd.DataFrame()
            grp = trials[group_name]
            if name not in grp:
                return pd.DataFrame()
            return _compound_to_df(grp[name])

    def get_trial_events(self, trial_index: int) -> pd.DataFrame:
        return self._read_trial_dataset(trial_index, "events")

    def get_trial_sensor_events(self, trial_index: int) -> pd.DataFrame:
        return self._read_trial_dataset(trial_index, "sensor_events")

    def get_trial_mkv_frames(self, trial_index: int) -> pd.DataFrame:
        return self._read_trial_dataset(trial_index, "mkv_frames")

    def get_trial_mini2p_frames(self, trial_index: int) -> pd.DataFrame:
        return self._read_trial_dataset(trial_index, "mini2p_frames")

    def get_trial_calcium(self, trial_index: int) -> dict[str, Any] | None:
        if self.curation_h5_path is None or not self.curation_h5_path.exists():
            return None
        group_name = f"{int(trial_index):04d}"
        with h5py.File(self.curation_h5_path, "r") as h5:
            path = f"trials/{group_name}/calcium"
            if path not in h5:
                return None
            grp = h5[path]
            return {
                "F": grp["F"][:] if "F" in grp else None,
                "dff": grp["dff"][:] if "dff" in grp else None,
                "events": _compound_to_df(grp["events"]) if "events" in grp else pd.DataFrame(),
                "t_volume_s": grp["t_volume_s"][:] if "t_volume_s" in grp else None,
                "attrs": _attrs_to_dict(grp.attrs),
            }

    def get_trial_dlc(self, trial_index: int) -> dict[str, Any] | None:
        if self.curation_h5_path is None or not self.curation_h5_path.exists():
            return None
        group_name = f"{int(trial_index):04d}"
        with h5py.File(self.curation_h5_path, "r") as h5:
            path = f"trials/{group_name}/dlc"
            if path not in h5:
                return None
            grp = h5[path]
            return {
                "x": grp["x"][:] if "x" in grp else None,
                "y": grp["y"][:] if "y" in grp else None,
                "likelihood": grp["likelihood"][:] if "likelihood" in grp else None,
                "t_mkv_s": grp["t_mkv_s"][:] if "t_mkv_s" in grp else None,
                "attrs": _attrs_to_dict(grp.attrs),
            }


# ---------------------------------------------------------------------------
# load_session
# ---------------------------------------------------------------------------

def _read_trials_table(h5: h5py.File) -> pd.DataFrame:
    trials_group = h5.get("trials")
    if trials_group is None:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for name in sorted(trials_group.keys()):
        attrs = _attrs_to_dict(trials_group[name].attrs)
        attrs["_group_name"] = name
        rows.append(attrs)
    df = pd.DataFrame(rows)
    if "trial_index" in df.columns:
        df = df.sort_values("trial_index").reset_index(drop=True)
    return df


def _read_timing(h5: h5py.File) -> dict[str, pd.DataFrame]:
    timing_group = h5.get("session/timing")
    if timing_group is None:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for name, dataset in timing_group.items():
        if isinstance(dataset, h5py.Dataset):
            out[name] = _compound_to_df(dataset)
    return out


def _read_clock_corrections(h5: h5py.File) -> dict[str, Any]:
    grp = h5.get("session/timing/clock_corrections")
    if grp is None:
        return {}
    return _attrs_to_dict(grp.attrs)


def _read_curation(curation_path: Path) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Read /curation from <base>_curation.h5 if present.

    Tolerates two on-disk layouts:
      - flat compound dataset at /curation/rows
      - per-column 1D datasets directly under /curation/
    """
    with h5py.File(curation_path, "r") as h5:
        cur_grp = h5.get("curation")
        if cur_grp is None:
            return None, {}
        attrs = _attrs_to_dict(cur_grp.attrs)
        if "rows" in cur_grp and isinstance(cur_grp["rows"], h5py.Dataset):
            return _compound_to_df(cur_grp["rows"]), attrs
        cols: dict[str, Any] = {}
        for k, v in cur_grp.items():
            if not isinstance(v, h5py.Dataset):
                continue
            data = v[:]
            if data.dtype.kind == "O":
                data = [b.decode("utf-8") if isinstance(b, bytes) else b for b in data]
            cols[k] = data
        return (pd.DataFrame(cols) if cols else None), attrs


def _resolve_session_paths(session_dir: Path) -> tuple[str, Path, Path]:
    base_name = session_dir.name
    h5_path = session_dir / f"{base_name}.h5"
    if not h5_path.exists():
        raise FileNotFoundError(
            f"Parser output not found at {h5_path}. "
            f"Run the MouseMaze parser on {session_dir} first."
        )
    curation_path = session_dir / f"{base_name}_curation.h5"
    return base_name, h5_path, curation_path


def load_session(session_dir: Path | str, *, with_curation: bool = True) -> Session:
    """Load a parsed MouseMaze session from session_dir.

    Reads <base>.h5. If with_curation is True and a sibling
    <base>_curation.h5 exists, reads /curation as well. Per-trial calcium
    and DLC are read on demand via Session.get_trial_*() methods.

    Raises:
        FileNotFoundError: if session_dir does not contain <base>.h5.
        ValueError: if parser_version is older than MIN_PARSER_VERSION.
    """
    session_dir = Path(session_dir).expanduser()
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {session_dir}")
    base_name, h5_path, curation_path = _resolve_session_paths(session_dir)

    with h5py.File(h5_path, "r") as h5:
        session_grp = h5.get("session")
        if session_grp is None:
            raise ValueError(f"{h5_path}: missing /session group")
        attrs = _attrs_to_dict(session_grp.attrs)
        _check_parser_version(str(attrs.get("parser_version", "")), h5_path)

        events = (
            _compound_to_df(session_grp["events"])
            if "events" in session_grp
            else pd.DataFrame()
        )
        timing = _read_timing(h5)
        clock_corrections = _read_clock_corrections(h5)
        trials = _read_trials_table(h5)

    parse_errors_raw = attrs.pop("parse_errors", []) or []
    if isinstance(parse_errors_raw, str):
        parse_errors = [parse_errors_raw]
    else:
        parse_errors = list(parse_errors_raw)

    curation: pd.DataFrame | None = None
    curation_attrs: dict[str, Any] = {}
    curation_h5_for_session: Path | None = None
    if with_curation and curation_path.exists():
        curation_h5_for_session = curation_path
        curation, curation_attrs = _read_curation(curation_path)

    return Session(
        session_dir=session_dir,
        base_name=base_name,
        h5_path=h5_path,
        curation_h5_path=curation_h5_for_session,
        attrs=attrs,
        trials=trials,
        events=events,
        timing=timing,
        clock_corrections=clock_corrections,
        parse_errors=parse_errors,
        curation=curation,
        curation_attrs=curation_attrs,
    )


# ---------------------------------------------------------------------------
# discover_data_root
# ---------------------------------------------------------------------------

def discover_data_root(data_root: Path | str) -> dict[str, list[Path]]:
    """Scan <data_root>/<mouse_id>/<session>/ and return {mouse_id: [session_dir,...]}.

    A session_dir is included only if it contains a <session_dir.name>.h5.
    Mice with no parsed sessions are listed with an empty list.
    """
    data_root = Path(data_root).expanduser()
    if not data_root.is_dir():
        raise FileNotFoundError(f"Data root not found: {data_root}")
    out: dict[str, list[Path]] = {}
    for mouse_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        sessions: list[Path] = []
        for session_dir in sorted(p for p in mouse_dir.iterdir() if p.is_dir()):
            if (session_dir / f"{session_dir.name}.h5").exists():
                sessions.append(session_dir)
        out[mouse_dir.name] = sessions
    return out
