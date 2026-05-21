from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import re


PARSER_VERSION = "0.2.0"
NA_STRING = "NA"


TRIAL_TYPE_STANDARD = "standard"
TRIAL_TYPE_CORRECTION = "correction"
TRIAL_TYPE_REPLAY = "replay"
TRIAL_TYPE_RANDOM_CUE = "random_cue"
TRIAL_TYPE_SYNTHETIC = "synthetic"

OUTCOME_VALUES = {"correct", "incorrect", "no_response", "aborted", "backward", "shaping_reward", "NA"}

SENSOR_TEXT_RE = re.compile(r"Time:\s*(?P<ms>\d+)\s*ms,\s*Sensor:\s*(?P<sensor>.+)$")
KV_PAIR_RE = re.compile(r"(?P<key>[A-Za-z0-9_]+)=(?P<value>[^, ]+)")

CANONICAL_SENSORS = {
    "WM1", "WM2", "Wait_sensor",
    "Decision_Left", "Decision_Right",
    "Return_Left", "Return_Right",
    "Lick_Left", "Lick_Right",
    "Reward_Left", "Reward_Right",
}


def canonicalize_sensor(name: str) -> str:
    if name is None:
        return ""
    cleaned = str(name).strip().replace(" ", "_")
    return cleaned


def is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == "" or value.strip().upper() in {"NA", "NAN", "NONE", "NULL"}
    return False


def clean_string(value: Any) -> str:
    if is_na(value):
        return NA_STRING
    return str(value)


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if is_na(value):
        return default
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if is_na(value):
        return default
    try:
        return float(str(value).strip())
    except Exception:
        return default


def to_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if is_na(value):
        return default
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    return default


def parse_key_values(text: str) -> dict[str, str]:
    return {m.group("key"): m.group("value") for m in KV_PAIR_RE.finditer(text)}


def parse_mega_event(text: str) -> tuple[int, str, str] | None:
    if not text.startswith("MEGA_EVT,"):
        return None
    parts = [part.strip() for part in text.split(",", 3)]
    if len(parts) < 3:
        return None
    mega_us = to_int(parts[1], -1)
    tag = parts[2]
    value = parts[3] if len(parts) >= 4 else ""
    return int(mega_us if mega_us is not None else -1), tag, value


def parse_sensor_text(text: str) -> tuple[int | None, str] | None:
    match = SENSOR_TEXT_RE.search(text)
    if not match:
        return None
    return to_int(match.group("ms")), match.group("sensor").strip()


@dataclass
class RawLogRow:
    row_index: int
    pc_ts: float
    time_str: str
    message: str
    path: Path

    @property
    def t_session_s(self) -> float:
        raise AttributeError("Use Event.t_session_s after session_t0 is known.")


@dataclass
class Event:
    t_session_s: float
    pc_ts: float
    kind: str
    mega_us: int = -1
    tag: str = ""
    value: str = ""
    raw_text: str = ""
    source: str = "host"


@dataclass
class FrameSlice:
    mkv_frames: list[dict[str, Any]] = field(default_factory=list)
    mini2p_frames: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Trial:
    trial_index: int
    standard_index: Optional[int] = None
    trial_type: str = TRIAL_TYPE_STANDARD

    level: Optional[int] = None
    delay_ms: Optional[int] = None
    cue1: str = NA_STRING
    cue2: str = NA_STRING
    correct_side: str = NA_STRING
    bias_left_count: Optional[int] = None
    p_right_correct: Optional[float] = None
    p_correction: Optional[float] = None

    chosen_side: str = NA_STRING
    outcome: str = NA_STRING
    latency_ms: Optional[int] = None
    replay_played: Optional[bool] = None
    consecutive_misses: Optional[int] = None
    punishment_delivered: Optional[bool] = None
    reward_delivered: Optional[bool] = None

    t_start_s: Optional[float] = None
    t_end_s: Optional[float] = None
    t_start_mega_us: Optional[int] = None
    t_end_mega_us: Optional[int] = None
    cue1_us: Optional[int] = None
    cue2_us: Optional[int] = None
    gate_open_us: Optional[int] = None
    wm2_us: Optional[int] = None
    lick_us: Optional[int] = None
    decision_us: Optional[int] = None
    return_us: Optional[int] = None

    events: list[Event] = field(default_factory=list)
    sensor_events: list[dict[str, Any]] = field(default_factory=list)
    frames: FrameSlice = field(default_factory=FrameSlice)
    parse_errors: list[str] = field(default_factory=list)

    def apply_values(self, values: dict[str, Any]) -> None:
        self.standard_index = to_int(values.get("standard_index"), self.standard_index)
        self.trial_type = clean_string(values.get("trial_type", self.trial_type))
        self.level = to_int(values.get("level"), self.level)
        self.delay_ms = to_int(values.get("delay_ms"), self.delay_ms)
        self.cue1 = clean_string(values.get("cue1", self.cue1))
        self.cue2 = clean_string(values.get("cue2", self.cue2))
        self.correct_side = clean_string(values.get("correct_side", self.correct_side)).lower()
        self.bias_left_count = to_int(values.get("bias_left_count"), self.bias_left_count)
        self.p_right_correct = to_float(values.get("p_right_correct"), self.p_right_correct)
        self.p_correction = to_float(values.get("p_correction"), self.p_correction)
        self.chosen_side = clean_string(values.get("chosen_side", self.chosen_side)).lower()
        self.outcome = clean_string(values.get("outcome", self.outcome)).lower()
        self.latency_ms = to_int(values.get("latency_ms"), self.latency_ms)
        self.replay_played = to_bool(values.get("replay_played"), self.replay_played)
        self.consecutive_misses = to_int(values.get("consecutive_misses"), self.consecutive_misses)

    def attrs(self) -> dict[str, Any]:
        return {
            "trial_index": self.trial_index,
            "standard_index": self.standard_index,
            "trial_type": self.trial_type,
            "level": self.level,
            "delay_ms": self.delay_ms,
            "cue1": self.cue1,
            "cue2": self.cue2,
            "correct_side": self.correct_side,
            "bias_left_count": self.bias_left_count,
            "p_right_correct": self.p_right_correct,
            "p_correction": self.p_correction,
            "chosen_side": self.chosen_side,
            "outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "replay_played": self.replay_played,
            "consecutive_misses": self.consecutive_misses,
            "punishment_delivered": self.punishment_delivered,
            "reward_delivered": self.reward_delivered,
            "t_start_s": self.t_start_s,
            "t_end_s": self.t_end_s,
            "t_start_mega_us": self.t_start_mega_us,
            "t_end_mega_us": self.t_end_mega_us,
            "cue1_us": self.cue1_us,
            "cue2_us": self.cue2_us,
            "gate_open_us": self.gate_open_us,
            "wm2_us": self.wm2_us,
            "lick_us": self.lick_us,
            "decision_us": self.decision_us,
            "return_us": self.return_us,
        }


@dataclass
class ClockCorrections:
    """Per-session clock-fit parameters, written to /session/timing/clock_corrections.attrs.

    Slopes/intercepts let consumers reconstruct the same correction the parser applied:
    `pc_s ≈ uno_pc_slope · uno_us + uno_pc_intercept` and
    `uno_us ≈ mega_uno_slope · mega_us + mega_uno_intercept`.
    """
    uno_pc_slope: float = 1e-6
    uno_pc_intercept: float = 0.0
    uno_pc_residual_ms: float = 0.0
    n_uno_pc_anchors: int = 0
    mega_uno_slope: float = 1.0
    mega_uno_intercept: float = 0.0
    mega_uno_residual_us: float = 0.0
    n_mega_uno_anchors: int = 0
    n_ttl_debounced: int = 0
    n_ffv1_orphan: int = 0
    blackfly_fps: float = 0.0
    mini2p_per_plane_hz: float = 0.0
    mini2p_planes_per_volume: int = 0   # 0 = unknown; supply externally to derive volume rate

    def attrs(self) -> dict[str, Any]:
        return {
            "uno_pc_slope": self.uno_pc_slope,
            "uno_pc_intercept": self.uno_pc_intercept,
            "uno_pc_residual_ms": self.uno_pc_residual_ms,
            "n_uno_pc_anchors": self.n_uno_pc_anchors,
            "mega_uno_slope": self.mega_uno_slope,
            "mega_uno_intercept": self.mega_uno_intercept,
            "mega_uno_residual_us": self.mega_uno_residual_us,
            "n_mega_uno_anchors": self.n_mega_uno_anchors,
            "n_ttl_debounced": self.n_ttl_debounced,
            "n_ffv1_orphan": self.n_ffv1_orphan,
            "blackfly_fps": self.blackfly_fps,
            "mini2p_per_plane_hz": self.mini2p_per_plane_hz,
            "mini2p_planes_per_volume": self.mini2p_planes_per_volume,
        }


@dataclass
class TimingData:
    hardware_frames: list[dict[str, Any]] | None = None
    behavior_frames_mkv: list[dict[str, Any]] | None = None
    mini2p_frames: list[dict[str, Any]] | None = None
    mega_sync: list[dict[str, Any]] | None = None
    clock_corrections: ClockCorrections = field(default_factory=ClockCorrections)


@dataclass
class Session:
    base_name: str
    source_log: Path
    session_t0_unix: float
    session_iso: str = NA_STRING
    mouse_id: str = NA_STRING
    task: str = NA_STRING
    firmware: str = NA_STRING
    firmware_version: str = NA_STRING
    parser_version: str = PARSER_VERSION
    corrections_applied: list[str] = field(default_factory=list)
    trials: list[Trial] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    timing: TimingData = field(default_factory=TimingData)
    parse_status: str = "clean"
    parse_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def n_trials(self) -> int:
        return len(self.trials)

    @property
    def n_standard_trials(self) -> int:
        return sum(1 for trial in self.trials if trial.trial_type == TRIAL_TYPE_STANDARD)

    @property
    def n_correct(self) -> int:
        return sum(
            1
            for trial in self.trials
            if trial.trial_type == TRIAL_TYPE_STANDARD and trial.outcome == "correct"
        )

    @property
    def has_blackfly(self) -> bool:
        return bool(self.timing.behavior_frames_mkv) and bool(self.timing.hardware_frames)

    @property
    def has_mini2p(self) -> bool:
        return bool(self.timing.mini2p_frames)

    @property
    def has_mega_sync(self) -> bool:
        return bool(self.timing.mega_sync)

    @property
    def has_hardware_frames(self) -> bool:
        return bool(self.timing.hardware_frames)

    def attrs(self) -> dict[str, Any]:
        attrs = {
            "mouse_id": self.mouse_id,
            "task": self.task,
            "firmware": self.firmware,
            "firmware_version": self.firmware_version,
            "parser_version": self.parser_version,
            "session_t0_unix": self.session_t0_unix,
            "session_iso": self.session_iso,
            "n_trials": self.n_trials,
            "n_standard_trials": self.n_standard_trials,
            "n_correct": self.n_correct,
            "has_blackfly": self.has_blackfly,
            "has_mini2p": self.has_mini2p,
            "has_mega_sync": self.has_mega_sync,
            "has_hardware_frames": self.has_hardware_frames,
            "parse_status": self.parse_status,
        }
        attrs.update(self.metadata)
        return attrs


@dataclass(frozen=True)
class SessionFileGroup:
    base_name: str
    directory: Path
    primary_log: Path
    console_log: Path | None = None
    behavior_log: Path | None = None
    hardware_frames: Path | None = None
    mini2p_frames: Path | None = None
    mega_sync: Path | None = None
    ffv1_frames: Path | None = None

    @property
    def sidecars(self) -> dict[str, Path]:
        return {
            key: value
            for key, value in {
                "hardware_frames": self.hardware_frames,
                "mini2p_frames": self.mini2p_frames,
                "mega_sync": self.mega_sync,
                "ffv1_frames": self.ffv1_frames,
            }.items()
            if value is not None
        }
