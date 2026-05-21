from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

from ..schema import (
    Event,
    RawLogRow,
    Session,
    SessionFileGroup,
    Trial,
    clean_string,
    parse_key_values,
    parse_mega_event,
    parse_sensor_text,
    to_float,
    to_int,
)


TIME_STR_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
LEGACY_STAGE_RE = re.compile(r"^Freelymoving_(?P<mouse>.+?)_tr(?P<stage>\d)_(?P<mmdd>\d{4})_.*$", re.I)
TASK_NAME_RE = re.compile(r"^Freelymoving_(?P<mouse>.+?)_(?P<task>[A-Za-z0-9_]+)_(?P<mmdd>\d{4})_.*$", re.I)

STAGE_TASKS = {
    "0": "habituation",
    "1": "cue_wm",
    "2": "alternation_wm",
    "3": "discrimination",
    "4": "random_cue",
    "5": "alternation_wm_with_delay",
    "6": "reversal",
    "7": "probabilistic",
}


class BaseExtractor:
    def __init__(self, group: SessionFileGroup, firmware: str, firmware_version: str):
        self.group = group
        self.firmware = firmware
        self.firmware_version = firmware_version

    def parse(self) -> Session:
        raise NotImplementedError

    def read_rows(self, path: Path | None = None) -> list[RawLogRow]:
        path = path or self.group.primary_log
        rows: list[RawLogRow] = []
        with path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader, start=1):
                parsed = self._parse_csv_row(row, i, path)
                if parsed is not None:
                    rows.append(parsed)
        if not rows:
            raise ValueError(f"No parseable rows in {path}")
        return rows

    def _parse_csv_row(self, row: list[str], row_index: int, path: Path) -> RawLogRow | None:
        if not row:
            return None
        first = row[0].strip()
        if not first or first.lower() == "pc_ts":
            return None
        try:
            pc_ts = float(first)
        except Exception:
            return None

        time_str = ""
        if len(row) >= 3 and TIME_STR_RE.match(row[1].strip()):
            time_str = row[1].strip()
            message = ",".join(row[2:]).strip()
        elif len(row) >= 2:
            message = ",".join(row[1:]).strip()
        else:
            message = row[-1].strip()

        if not message:
            return None
        return RawLogRow(row_index=row_index, pc_ts=pc_ts, time_str=time_str, message=message, path=path)

    def new_session(self, rows: list[RawLogRow]) -> Session:
        session = Session(
            base_name=self.group.base_name,
            source_log=rows[0].path,
            session_t0_unix=rows[0].pc_ts,
            firmware=self.firmware,
            firmware_version=self.firmware_version,
        )
        self._apply_filename_metadata(session)
        for row in rows[:200]:
            if row.message.startswith("WM_META"):
                self._apply_wm_meta(session, row.message)
                break
        return session

    def _apply_filename_metadata(self, session: Session) -> None:
        legacy = LEGACY_STAGE_RE.match(self.group.base_name)
        if legacy:
            session.mouse_id = legacy.group("mouse")
            stage = legacy.group("stage")
            session.task = STAGE_TASKS.get(stage, f"tr{stage}")
            session.metadata["training_stage"] = to_int(stage)
            return

        task_named = TASK_NAME_RE.match(self.group.base_name)
        if task_named:
            session.mouse_id = task_named.group("mouse")
            session.task = task_named.group("task")

    def _apply_wm_meta(self, session: Session, message: str) -> None:
        values = parse_key_values(message)
        session.task = clean_string(values.get("task_name", session.task))
        session.firmware_version = clean_string(values.get("firmware_version", session.firmware_version))
        session.mouse_id = clean_string(values.get("mouse_id", session.mouse_id))
        session.session_iso = clean_string(values.get("session_iso", session.session_iso))
        for key in ("n_trials_target", "time_cap_s", "start_level"):
            if key in values:
                parsed = to_int(values[key])
                if parsed is not None:
                    session.metadata[key] = parsed
        if "punishment" in values:
            session.metadata["punishment"] = values["punishment"]

    def event_from_row(self, row: RawLogRow, session_t0: float) -> Event:
        text = row.message.strip()
        t_session_s = row.pc_ts - session_t0

        mega = parse_mega_event(text)
        if mega:
            mega_us, tag, value = mega
            return Event(
                t_session_s=t_session_s,
                pc_ts=row.pc_ts,
                kind="MEGA_EVT",
                mega_us=mega_us,
                tag=tag,
                value=value,
                raw_text=text,
                source="arduino",
            )

        sensor = parse_sensor_text(text)
        if sensor:
            _, sensor_name = sensor
            return Event(
                t_session_s=t_session_s,
                pc_ts=row.pc_ts,
                kind="SENSOR_TXT",
                tag="SENSOR",
                value=sensor_name,
                raw_text=text,
                source="arduino",
            )

        kind, tag, value, source = self._classify_text_event(text)
        return Event(
            t_session_s=t_session_s,
            pc_ts=row.pc_ts,
            kind=kind,
            mega_us=-1,
            tag=tag,
            value=value,
            raw_text=text,
            source=source,
        )

    def _classify_text_event(self, text: str) -> tuple[str, str, str, str]:
        if text.startswith("WM_TRIAL_START"):
            return "TRIAL_START", "WM_TRIAL_START", parse_key_values(text).get("trial_index", ""), "arduino"
        if text.startswith("WM_TRIAL_SUMMARY"):
            return "TRIAL_SUMMARY", "WM_TRIAL_SUMMARY", parse_key_values(text).get("trial_index", ""), "arduino"
        if text.startswith("WM_TRIAL_RESTART"):
            return "TRIAL_RESTART", "WM_TRIAL_RESTART", parse_key_values(text).get("reason", ""), "arduino"
        if text.startswith("WM_CHOICE"):
            return "CHOICE", "WM_CHOICE", parse_key_values(text).get("side", ""), "arduino"
        if text.startswith("PUNISH_DELIVERED"):
            return "PUNISH", "PUNISH_DELIVERED", parse_key_values(text).get("reason", ""), "arduino"
        if text.startswith("REWARD_DELIVERED"):
            return "REWARD", "REWARD_DELIVERED", parse_key_values(text).get("side", ""), "arduino"
        if text.startswith("WM_META"):
            return "META", "WM_META", "", "arduino"
        if text.startswith("WM_END"):
            return "END", "WM_END", parse_key_values(text).get("end_reason", ""), "arduino"
        if text.startswith("ACK"):
            return "ACK", "ACK", text, "host"
        if text.startswith("EVT:RETURN") or text.startswith("Return "):
            return "RETURN", "RETURN", text, "arduino"
        if text.startswith("["):
            tag = text[1 : text.find("]")] if "]" in text else "GUI"
            kind = {
                "System": "GUI_SYSTEM",
                "WM": "GUI_WM",
                "Timing": "GUI_TIMING",
                "Lock": "GUI_LOCK",
                "DLC": "GUI_DLC",
            }.get(tag, "GUI_OTHER")
            return kind, tag, text, "gui"
        if text.startswith("Cue1:") or text.startswith("Cue2:") or text.startswith("Correct turn:"):
            tag = text.split(":", 1)[0].strip().upper().replace(" ", "_")
            return "GUI_WM", tag, text.split(":", 1)[1].strip() if ":" in text else "", "arduino"
        if "Total trial" in text:
            return "TRIAL_SUMMARY", "TOTAL_TRIAL", text, "arduino"
        return "UNKNOWN", "", "", "host"

    def record_session_event(self, session: Session, event: Event) -> None:
        session.events.append(event)

    def record_trial_event(self, trial: Trial, event: Event, session: Session | None = None) -> None:
        trial.events.append(event)
        self._update_trial_from_event(trial, event)
        if session is not None:
            session.events.append(event)

    def _update_trial_from_event(self, trial: Trial, event: Event) -> None:
        text = event.raw_text
        values = parse_key_values(text)

        if event.kind == "CHOICE":
            side = values.get("side") or event.value
            if side:
                trial.chosen_side = side.lower()
            if event.mega_us >= 0 and trial.decision_us is None:
                trial.decision_us = event.mega_us
        elif event.kind == "PUNISH":
            trial.punishment_delivered = True
        elif event.kind == "REWARD":
            trial.reward_delivered = True
        elif text.startswith("WM_CUE_REPLAY"):
            trial.replay_played = True
        elif text.startswith("WM_TRIAL_RESTART"):
            self._reset_trial_sequence_times(trial)
        elif text.startswith("WM_CROSS_LICK"):
            trial.outcome = "incorrect"
        elif text.startswith("WM_BACKWARD"):
            trial.outcome = "backward"

        if event.kind == "MEGA_EVT":
            self._update_trial_from_mega_event(trial, event)
        else:
            self._update_trial_from_sensor_text(trial, event)

    def _update_trial_from_mega_event(self, trial: Trial, event: Event) -> None:
        tag = event.tag
        value = event.value
        mega_us = event.mega_us
        if mega_us < 0:
            return

        if tag == "WM_SEQ" and value == "CUE1" and trial.cue1_us is None:
            trial.cue1_us = mega_us
        elif tag == "WM_SEQ" and value == "CUE2" and trial.cue2_us is None:
            trial.cue2_us = mega_us
        elif tag == "WM_SEQ" and value == "DONE" and trial.gate_open_us is None:
            trial.gate_open_us = mega_us
        elif tag == "WM_GATE_CMD" and self._is_wm_gate_open(value) and trial.gate_open_us is None:
            trial.gate_open_us = mega_us
        elif tag in {"SENSOR", "SENSOR_FAST"}:
            self._update_trial_from_sensor_name(trial, value, mega_us, prefer_exact=True)
        elif tag == "RETURN" and trial.return_us is None:
            trial.return_us = mega_us
        elif tag in {"MOUSE_CHOICE", "WM_PHASE"} and trial.decision_us is None:
            trial.decision_us = mega_us
        elif tag == "REWARD":
            trial.reward_delivered = True
        elif tag == "PUNISH":
            trial.punishment_delivered = True
        elif tag == "WM_TRIAL_RESTART":
            self._reset_trial_sequence_times(trial)
        elif tag == "TRIAL_START_INDEX" and trial.t_start_mega_us is None:
            trial.t_start_mega_us = mega_us
        elif tag == "OUTCOME":
            _OUTCOME_MAP = {
                "CORRECT": "correct",
                "INCORRECT": "incorrect",
                "MISS": "no_response",
                "SHAPING_REWARD": "shaping_reward",
                "NO_RESPONSE": "no_response",
                "BACKWARD": "backward",
            }
            mapped = _OUTCOME_MAP.get(value.upper().strip())
            if mapped:
                trial.outcome = mapped

    def _update_trial_from_sensor_text(self, trial: Trial, event: Event) -> None:
        sensor = parse_sensor_text(event.raw_text)
        if not sensor:
            return
        time_ms, sensor_name = sensor
        if time_ms is None:
            return
        self._update_trial_from_sensor_name(trial, sensor_name, time_ms * 1000)

    def _update_trial_from_sensor_name(
        self,
        trial: Trial,
        sensor_name: str,
        approx_us: int,
        *,
        prefer_exact: bool = False,
    ) -> None:
        sensor = sensor_name.strip()
        if sensor == "WM2":
            trial.wm2_us = self._choose_sensor_time(trial.wm2_us, approx_us, prefer_exact)
        elif sensor.startswith("Lick"):
            trial.lick_us = self._choose_sensor_time(trial.lick_us, approx_us, prefer_exact)
        elif sensor.startswith("Return"):
            trial.return_us = self._choose_sensor_time(trial.return_us, approx_us, prefer_exact)

    def _choose_sensor_time(
        self,
        existing_us: int | None,
        candidate_us: int,
        prefer_exact: bool,
    ) -> int:
        if existing_us is None:
            return candidate_us
        if prefer_exact and 0 <= candidate_us - existing_us <= 10_000:
            return candidate_us
        return existing_us

    def _reset_trial_sequence_times(self, trial: Trial) -> None:
        trial.cue1_us = None
        trial.cue2_us = None
        trial.gate_open_us = None

    def _is_wm_gate_open(self, value: str) -> bool:
        parsed = to_int(value)
        return parsed == 91 or "OPEN" in str(value).upper()

    def mark_partial(self, session: Session, message: str) -> None:
        session.parse_status = "partial"
        session.parse_errors.append(message)

    def finish_trial_as_aborted(self, session: Session, trial: Trial, events: Iterable[Event] = ()) -> None:
        for event in events:
            self.record_trial_event(trial, event, session)
        trial.outcome = "aborted"
        if trial.events:
            trial.t_end_s = trial.events[-1].t_session_s
        session.trials.append(trial)
        self.mark_partial(session, f"Trial {trial.trial_index} ended without a summary.")

    def finalize_session(self, session: Session) -> Session:
        if session.parse_errors and session.parse_status == "clean":
            session.parse_status = "partial"
        return session


def infer_received_turn(value: str) -> str:
    value = str(value).strip()
    lowered = value.lower()
    if lowered in {"0", "left", "l"}:
        return "left"
    if lowered in {"1", "right", "r"}:
        return "right"
    return lowered or "NA"


def parse_total_trial_line(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    matches = list(re.finditer(r"(?P<key>[A-Za-z0-9 ]+):\s*(?P<value>.*?)(?=,\s*[A-Za-z0-9 ]+:\s*|$)", text))
    for match in matches:
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip().strip(",")
        if key:
            result[key] = value
    return result
