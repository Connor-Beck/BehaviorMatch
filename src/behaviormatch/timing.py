from __future__ import annotations

import bisect
import csv
from pathlib import Path
from typing import Any

from .schema import (
    ClockCorrections,
    Event,
    Session,
    SessionFileGroup,
    TimingData,
    canonicalize_sensor,
    parse_sensor_text,
)


TTL_DEBOUNCE_GUARD_US = 1000   # 1 ms; spurious double-edges are ~10 µs apart, real frames are ≥15 ms apart
DEFAULT_UNO_PC_SLOPE = 1e-6     # 1 µs UNO ≈ 1e-6 s PC, used when the fit can't run
DEFAULT_MEGA_UNO_SLOPE = 1.0    # both clocks tick in µs; nominal slope is 1.0


def _float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float((row.get(key) or "").strip())
    except Exception:
        return default


def _int(row: dict[str, str], key: str, default: int = -1) -> int:
    try:
        return int(float((row.get(key) or "").strip()))
    except Exception:
        return default


def _dropped(value: Any) -> int:
    return 0 if value in (None, "", "0", "false", "False") else 1


def _read_dict_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        return list(csv.DictReader(f))


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least-squares fit y = slope*x + intercept. Returns (slope, intercept, residual_stdev)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den == 0:
        return 0.0, mean_y, 0.0
    slope = num / den
    intercept = mean_y - slope * mean_x
    sq = 0.0
    for x, y in zip(xs, ys):
        residual = y - (slope * x + intercept)
        sq += residual * residual
    residual_stdev = (sq / (n - 1)) ** 0.5 if n > 1 else 0.0
    return slope, intercept, residual_stdev


def fit_uno_pc(rows: list[dict[str, Any]]) -> tuple[float, float, float, int]:
    """Fit pc_ts ≈ slope·uno_edge_us + intercept over rows that aren't debounced."""
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        if row.get("debounced"):
            continue
        uno_us = row.get("uno_edge_us", -1)
        pc_ts = row.get("pc_ts", 0.0)
        if uno_us is None or uno_us < 0 or pc_ts <= 0:
            continue
        xs.append(float(uno_us))
        ys.append(float(pc_ts))
    if len(xs) < 2:
        return DEFAULT_UNO_PC_SLOPE, 0.0, 0.0, len(xs)
    slope, intercept, residual = _linear_fit(xs, ys)
    return slope, intercept, residual * 1000.0, len(xs)


def fit_mega_uno(rows: list[dict[str, Any]]) -> tuple[float, float, float, int]:
    """Fit uno_edge_us ≈ slope·mega_evt_us + intercept over mega_sync rows."""
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        mega_us = row.get("mega_evt_us", -1)
        uno_us = row.get("uno_edge_us", -1)
        if mega_us is None or mega_us < 0 or uno_us is None or uno_us < 0:
            continue
        xs.append(float(mega_us))
        ys.append(float(uno_us))
    if len(xs) < 2:
        return DEFAULT_MEGA_UNO_SLOPE, 0.0, 0.0, len(xs)
    slope, intercept, residual = _linear_fit(xs, ys)
    return slope, intercept, residual, len(xs)


def debounce_hardware_frames(rows: list[dict[str, Any]]) -> int:
    """Mark rows whose uno_edge_us is < TTL_DEBOUNCE_GUARD_US after the previous kept edge.

    Returns the count of debounced rows. Rows are mutated in place with `debounced=1`.
    """
    last_kept_us: int | None = None
    n_debounced = 0
    for row in rows:
        row.setdefault("debounced", 0)
        uno_us = row.get("uno_edge_us", -1)
        if uno_us is None or uno_us < 0:
            continue
        if last_kept_us is not None and (uno_us - last_kept_us) < TTL_DEBOUNCE_GUARD_US:
            row["debounced"] = 1
            n_debounced += 1
            continue
        last_kept_us = uno_us
    return n_debounced


def read_frame_sidecar(path: Path) -> list[dict[str, Any]]:
    """Read a TTL sidecar (hardware_frames or mini2P_frames) into raw row dicts.

    Time-correction is applied later in `apply_corrections`.
    """
    rows: list[dict[str, Any]] = []
    for frame_number, row in enumerate(_read_dict_rows(path), start=1):
        rows.append(
            {
                "frame_number": frame_number,
                "t_session_s": 0.0,
                "pc_ts": _float(row, "pc_time_sec"),
                "uno_edge_us": _int(row, "uno_edge_us"),
                "dropped_reported": _dropped(row.get("dropped_reported")),
                "debounced": 0,
            }
        )
    return rows


def read_mkv_frames(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_dict_rows(path):
        rows.append(
            {
                "mkv_frame_i": _int(row, "frame_i"),
                "t_session_s": 0.0,
                "pc_ts": _float(row, "pc_ts"),
                "rel_ms": _float(row, "rel_ms"),
                "hardware_frame_number": -1,
                "is_orphan": 0,
            }
        )
    return rows


def read_mega_sync(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_dict_rows(path):
        uno_pc = _float(row, "uno_pc_time_sec")
        mega_pc = _float(row, "mega_evt_pc_time_sec")
        rows.append(
            {
                "uno_edge_us": _int(row, "uno_edge_us"),
                "mega_evt_us": _int(row, "mega_evt_us"),
                "mega_tag": (row.get("tag") or "").strip(),
                "mega_value": (row.get("value") or "").strip(),
                "uno_pc_time_sec": uno_pc,
                "mega_evt_pc_time_sec": mega_pc,
                "t_session_s": 0.0,
                "pc_skew_s": mega_pc - uno_pc,
                "dropped_reported": _dropped(row.get("dropped_reported")),
            }
        )
    return rows


def reconcile_ffv1_with_hardware(
    mkv_rows: list[dict[str, Any]],
    hw_rows: list[dict[str, Any]],
) -> int:
    """Pair encoder frames to hardware-clock frames; flag the startup-window orphans.

    Strategy: drop the leading rows from whichever stream has more entries,
    flagging them as `is_orphan=1` (mkv side) when the encoder ran longer.
    Then 1:1 pair the remaining rows and stamp `hardware_frame_number`.
    """
    if not mkv_rows or not hw_rows:
        return 0

    n_orphan = max(0, len(mkv_rows) - len(hw_rows))
    for i in range(n_orphan):
        mkv_rows[i]["is_orphan"] = 1
        mkv_rows[i]["hardware_frame_number"] = -1

    # If the UNO ran longer than the encoder, leading hardware rows have no encoder pair.
    # We don't write `hardware_frame_number` from hw side; just leave unpaired hardware rows alone.
    hw_offset = max(0, len(hw_rows) - len(mkv_rows))

    paired = min(len(mkv_rows) - n_orphan, len(hw_rows) - hw_offset)
    for i in range(paired):
        mkv_idx = n_orphan + i
        hw_idx = hw_offset + i
        mkv_rows[mkv_idx]["hardware_frame_number"] = hw_rows[hw_idx]["frame_number"]
        mkv_rows[mkv_idx]["is_orphan"] = 0

    return n_orphan


def estimate_blackfly_fps(hw_rows: list[dict[str, Any]]) -> float:
    diffs = []
    last_us: int | None = None
    for row in hw_rows:
        if row.get("debounced"):
            continue
        uno_us = row.get("uno_edge_us", -1)
        if uno_us is None or uno_us < 0:
            continue
        if last_us is not None:
            diffs.append(uno_us - last_us)
        last_us = uno_us
    if not diffs:
        return 0.0
    diffs.sort()
    median_us = diffs[len(diffs) // 2]
    if median_us <= 0:
        return 0.0
    return 1_000_000.0 / median_us


def estimate_mini2p_per_plane_hz(rows: list[dict[str, Any]]) -> float:
    """Estimate the per-plane TTL rate from interval medians.

    The TTL fires once per imaging plane, so this is the *plane* rate.
    Volume rate = per_plane_hz / planes_per_volume must be derived externally
    (from ScanImage config), since a steady single-plane stream is
    indistinguishable from a multi-plane stream with no inter-volume gap.
    """
    diffs = []
    last_us: int | None = None
    for row in rows:
        uno_us = row.get("uno_edge_us", -1)
        if uno_us is None or uno_us < 0:
            continue
        if last_us is not None:
            diffs.append(uno_us - last_us)
        last_us = uno_us
    if not diffs:
        return 0.0
    diffs.sort()
    median_us = diffs[len(diffs) // 2]
    if median_us <= 0:
        return 0.0
    return 1_000_000.0 / median_us


def apply_corrections(
    timing: TimingData,
    corrections: ClockCorrections,
    session_t0: float,
    session: Session,
) -> list[str]:
    """Mutate timing tables in place to fill in `t_session_s` using corrected clocks.

    Returns the list of correction tags applied (for `corrections_applied`).
    """
    applied: list[str] = []

    # 1) Debounce
    if timing.hardware_frames is not None:
        n_debounced = debounce_hardware_frames(timing.hardware_frames)
        corrections.n_ttl_debounced = n_debounced
        if n_debounced > 0:
            applied.append("ttl_debounce_1ms")

    # 2) UNO ↔ PC linear fit (hardware_frames is the dense anchor stream)
    if timing.hardware_frames:
        slope, intercept, residual_ms, n_anchors = fit_uno_pc(timing.hardware_frames)
        corrections.uno_pc_slope = slope
        corrections.uno_pc_intercept = intercept
        corrections.uno_pc_residual_ms = residual_ms
        corrections.n_uno_pc_anchors = n_anchors
        if n_anchors >= 2:
            applied.append("uno_pc_drift_lin")
        for row in timing.hardware_frames:
            uno_us = row.get("uno_edge_us", -1)
            if uno_us is not None and uno_us >= 0 and n_anchors >= 2:
                corrected_pc = slope * float(uno_us) + intercept
                row["t_session_s"] = corrected_pc - session_t0
            else:
                row["t_session_s"] = row.get("pc_ts", 0.0) - session_t0
        corrections.blackfly_fps = estimate_blackfly_fps(timing.hardware_frames)

    # 3) mini2P uses the same UNO clock; reuse the UNO↔PC fit if available
    if timing.mini2p_frames:
        slope = corrections.uno_pc_slope
        intercept = corrections.uno_pc_intercept
        if corrections.n_uno_pc_anchors < 2:
            # Self-fit if hardware_frames was missing (unusual but possible)
            slope, intercept, residual_ms, n_anchors = fit_uno_pc(timing.mini2p_frames)
            corrections.uno_pc_slope = slope
            corrections.uno_pc_intercept = intercept
            corrections.uno_pc_residual_ms = residual_ms
            corrections.n_uno_pc_anchors = n_anchors
            if n_anchors >= 2 and "uno_pc_drift_lin" not in applied:
                applied.append("uno_pc_drift_lin")
        for row in timing.mini2p_frames:
            uno_us = row.get("uno_edge_us", -1)
            if uno_us is not None and uno_us >= 0 and corrections.n_uno_pc_anchors >= 2:
                row["t_session_s"] = slope * float(uno_us) + intercept - session_t0
            else:
                row["t_session_s"] = row.get("pc_ts", 0.0) - session_t0
        corrections.mini2p_per_plane_hz = estimate_mini2p_per_plane_hz(timing.mini2p_frames)
        # planes_per_volume stays 0 (unknown) — supply externally if needed.

    # 4) Mega ↔ UNO linear fit
    if timing.mega_sync:
        m_slope, m_intercept, m_residual, m_n = fit_mega_uno(timing.mega_sync)
        corrections.mega_uno_slope = m_slope
        corrections.mega_uno_intercept = m_intercept
        corrections.mega_uno_residual_us = m_residual
        corrections.n_mega_uno_anchors = m_n
        if m_n >= 2:
            applied.append("mega_uno_lin")
        u_slope = corrections.uno_pc_slope
        u_intercept = corrections.uno_pc_intercept
        for row in timing.mega_sync:
            uno_us = row.get("uno_edge_us", -1)
            if uno_us is not None and uno_us >= 0 and corrections.n_uno_pc_anchors >= 2:
                row["t_session_s"] = u_slope * float(uno_us) + u_intercept - session_t0
            else:
                row["t_session_s"] = row.get("uno_pc_time_sec", 0.0) - session_t0

    # 5) FFV1 ↔ hardware reconciliation
    if timing.behavior_frames_mkv and timing.hardware_frames:
        n_orphan = reconcile_ffv1_with_hardware(timing.behavior_frames_mkv, timing.hardware_frames)
        corrections.n_ffv1_orphan = n_orphan
        if n_orphan > 0:
            applied.append("ffv1_startup_reconcile")
        # Encoder frames carry a PC timestamp directly (no UNO clock involved)
        for row in timing.behavior_frames_mkv:
            row["t_session_s"] = row["pc_ts"] - session_t0

    # 6) Drift sanity-check warnings
    if corrections.blackfly_fps and (corrections.blackfly_fps < 50 or corrections.blackfly_fps > 100):
        session.parse_errors.append(
            f"blackfly_fps={corrections.blackfly_fps:.2f} outside expected 50-100 Hz"
        )
    if corrections.mini2p_per_plane_hz and (corrections.mini2p_per_plane_hz < 1 or corrections.mini2p_per_plane_hz > 60):
        session.parse_errors.append(
            f"mini2p_per_plane_hz={corrections.mini2p_per_plane_hz:.3f} outside expected 1-60 Hz"
        )

    return applied


def load_timing_data(group: SessionFileGroup) -> TimingData:
    hardware = read_frame_sidecar(group.hardware_frames) if group.hardware_frames else None
    mini2p = read_frame_sidecar(group.mini2p_frames) if group.mini2p_frames else None
    mega_sync = read_mega_sync(group.mega_sync) if group.mega_sync else None
    mkv = read_mkv_frames(group.ffv1_frames) if group.ffv1_frames else None
    return TimingData(
        hardware_frames=hardware,
        behavior_frames_mkv=mkv,
        mini2p_frames=mini2p,
        mega_sync=mega_sync,
    )


def _correct_event_times(
    events: list[Event],
    corrections: ClockCorrections,
    session_t0: float,
) -> None:
    """Replace t_session_s for Mega-clock events using the Mega→UNO→PC chain.

    PC-side events (those with a real pc_ts and source != arduino on a Mega line)
    keep their pc_ts-derived time. We re-derive only when mega_us is present.
    """
    if corrections.n_uno_pc_anchors < 2:
        return
    if corrections.n_mega_uno_anchors < 2:
        return
    u_slope = corrections.uno_pc_slope
    u_intercept = corrections.uno_pc_intercept
    m_slope = corrections.mega_uno_slope
    m_intercept = corrections.mega_uno_intercept
    for event in events:
        if event.mega_us is None or event.mega_us < 0:
            continue
        uno_us = m_slope * float(event.mega_us) + m_intercept
        pc_s = u_slope * uno_us + u_intercept
        event.t_session_s = pc_s - session_t0


def _build_sensor_events(trial, session_t0: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    t_start = trial.t_start_s if trial.t_start_s is not None else 0.0
    for event in trial.events:
        sensor_name = ""
        mega_us = -1
        if event.tag == "SENSOR" and event.kind == "MEGA_EVT":
            sensor_name = canonicalize_sensor(event.value)
            mega_us = event.mega_us
        elif event.kind == "SENSOR_TXT":
            sensor_name = canonicalize_sensor(event.value)
        else:
            parsed = parse_sensor_text(event.raw_text)
            if parsed:
                sensor_name = canonicalize_sensor(parsed[1])
        if not sensor_name:
            continue
        out.append(
            {
                "t_session_s": event.t_session_s,
                "t_trial_s": event.t_session_s - t_start,
                "sensor": sensor_name,
                "mega_us": mega_us,
            }
        )
    return out


def attach_timing(session: Session, group: SessionFileGroup) -> Session:
    timing = load_timing_data(group)
    corrections = ClockCorrections()
    applied = apply_corrections(timing, corrections, session.session_t0_unix, session)
    timing.clock_corrections = corrections
    session.timing = timing
    session.corrections_applied = applied

    # Re-derive Mega-clock event times now that corrections are known
    _correct_event_times(session.events, corrections, session.session_t0_unix)
    for trial in session.trials:
        _correct_event_times(trial.events, corrections, session.session_t0_unix)

    # Slice frames per trial; build sensor_events
    for trial in session.trials:
        if trial.t_start_s is None or trial.t_end_s is None:
            trial.sensor_events = _build_sensor_events(trial, session.session_t0_unix)
            continue
        if timing.behavior_frames_mkv:
            trial.frames.mkv_frames = [
                {
                    "mkv_frame_i": row["mkv_frame_i"],
                    "t_session_s": row["t_session_s"],
                    "hardware_frame_number": row["hardware_frame_number"],
                }
                for row in timing.behavior_frames_mkv
                if not row.get("is_orphan") and trial.t_start_s <= row["t_session_s"] <= trial.t_end_s
            ]
        if timing.mini2p_frames:
            trial.frames.mini2p_frames = [
                {
                    "frame_number": row["frame_number"],
                    "t_session_s": row["t_session_s"],
                }
                for row in timing.mini2p_frames
                if trial.t_start_s <= row["t_session_s"] <= trial.t_end_s
            ]
        trial.sensor_events = _build_sensor_events(trial, session.session_t0_unix)

    return session


def nearest_hardware_frame(pc_ts: float, hardware_pc_ts: list[float]) -> int:
    """Legacy helper kept for tests; prefer reconcile_ffv1_with_hardware in new code."""
    if not hardware_pc_ts:
        return -1
    idx = bisect.bisect_left(hardware_pc_ts, pc_ts)
    if idx <= 0:
        return 1
    if idx >= len(hardware_pc_ts):
        return len(hardware_pc_ts)
    before = hardware_pc_ts[idx - 1]
    after = hardware_pc_ts[idx]
    return idx if abs(pc_ts - before) <= abs(after - pc_ts) else idx + 1
