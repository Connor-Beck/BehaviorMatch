from __future__ import annotations

import csv
from pathlib import Path

from ..schema import (
    Event,
    NA_STRING,
    Session,
    Trial,
    canonicalize_sensor,
    clean_string,
    to_float,
    to_int,
)
from .base import BaseExtractor


CONFIG_TAGS = {
    "CMD",
    "TRAINING_STAGE",
    "TONE_HIGH_HZ",
    "TONE_LOW_HZ",
    "WM_GATE_DELAY_DEFAULT_MS",
    "WM2_AUDIO_CUE",
}


class MegaSyncExtractor(BaseExtractor):
    """Infer a behavior session from a `_mega_sync.csv` file alone.

    This is a fallback for sessions where the console log is unavailable. It
    preserves all Mega events and infers trial boundaries from the repeated
    `SENSOR,WM1` followed by `CUE1` pattern.
    """

    def parse(self) -> Session:
        events = self._read_mega_events(self.group.primary_log)
        if not events:
            raise ValueError(f"No parseable Mega sync rows in {self.group.primary_log}")

        session = Session(
            base_name=self.group.base_name,
            source_log=self.group.primary_log,
            session_t0_unix=events[0].pc_ts,
            firmware=self.firmware,
            firmware_version=self.firmware_version,
        )
        self._apply_filename_metadata(session)
        session.metadata["source_mode"] = "mega_sync_only"
        self.mark_partial(
            session,
            "Parsed from mega_sync only; trial summaries are unavailable and outcomes are inferred.",
        )

        active: Trial | None = None
        pending: list[Event] = []
        trial_index = 0

        for event in events:
            try:
                self._apply_session_tag(session, event)

                if active is None and self._is_sequence_start(event):
                    for pending_event in pending:
                        self.record_session_event(session, pending_event)
                    pending = []

                    trial_index += 1
                    active = Trial(
                        trial_index=trial_index,
                        t_start_s=event.t_session_s,
                        t_start_mega_us=event.mega_us,
                    )
                    self._apply_trial_tag(active, event)
                    self.record_trial_event(active, event, session)
                    continue

                if active is None and self._opens_trial(event, pending):
                    start_event = pending.pop()
                    for pending_event in pending:
                        self.record_session_event(session, pending_event)
                    pending = []

                    trial_index += 1
                    active = Trial(
                        trial_index=trial_index,
                        t_start_s=start_event.t_session_s,
                        t_start_mega_us=start_event.mega_us,
                    )
                    self.record_trial_event(active, start_event, session)
                    self._apply_trial_tag(active, event)
                    self.record_trial_event(active, event, session)
                    continue

                if event.tag == "CUE1" and active is not None:
                    self._finish_trial(active)
                    session.trials.append(active)
                    trial_index += 1
                    active = Trial(
                        trial_index=trial_index,
                        t_start_s=event.t_session_s,
                        t_start_mega_us=event.mega_us,
                    )
                    self._apply_trial_tag(active, event)
                    self.record_trial_event(active, event, session)
                    continue

                if active is None:
                    pending.append(event)
                    continue

                self._apply_trial_tag(active, event)
                self.record_trial_event(active, event, session)
                if self._closes_trial(event):
                    active.t_end_s = event.t_session_s
                    active.t_end_mega_us = event.mega_us
                    self._finish_trial(active)
                    session.trials.append(active)
                    active = None
            except Exception as exc:
                self.mark_partial(session, f"Mega event {event.mega_us}: {exc}")

        for pending_event in pending:
            self.record_session_event(session, pending_event)

        if active is not None:
            if active.t_end_s is None and active.events:
                active.t_end_s = active.events[-1].t_session_s
                active.t_end_mega_us = active.events[-1].mega_us
            self._finish_trial(active)
            session.trials.append(active)

        return self.finalize_session(session)

    def _read_mega_events(self, path: Path) -> list[Event]:
        rows: list[Event] = []
        with path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mega_us = to_int(row.get("mega_evt_us"), -1) or -1
                pc_ts = to_float(row.get("mega_evt_pc_time_sec"))
                if pc_ts is None or pc_ts <= 0:
                    pc_ts = to_float(row.get("uno_pc_time_sec"), 0.0) or 0.0
                tag = clean_string(row.get("tag", "")).strip()
                value = clean_string(row.get("value", "")).strip()
                if mega_us < 0 or pc_ts <= 0 or not tag:
                    continue
                rows.append(
                    Event(
                        t_session_s=0.0,
                        pc_ts=pc_ts,
                        kind="MEGA_EVT",
                        mega_us=mega_us,
                        tag=tag,
                        value=value,
                        raw_text=f"MEGA_EVT,{mega_us},{tag},{value}",
                        source="arduino",
                    )
                )

        if not rows:
            return rows
        session_t0 = rows[0].pc_ts
        for event in rows:
            event.t_session_s = event.pc_ts - session_t0
        return rows

    def _apply_session_tag(self, session: Session, event: Event) -> None:
        if event.tag not in CONFIG_TAGS:
            return
        key = event.tag.lower()
        value = event.value
        parsed = to_int(value)
        session.metadata[key] = parsed if parsed is not None else value
        if event.tag == "TRAINING_STAGE" and parsed is not None:
            session.metadata["training_stage"] = parsed

    def _opens_trial(self, event: Event, pending: list[Event]) -> bool:
        return event.tag == "CUE1" and bool(pending) and self._is_wm1(pending[-1])

    def _is_sequence_start(self, event: Event) -> bool:
        return event.tag == "WM_SEQ_START_MS"

    def _closes_trial(self, event: Event) -> bool:
        if event.tag not in {"SENSOR", "SENSOR_FAST"}:
            return False
        return canonicalize_sensor(event.value).lower().startswith("return_")

    def _is_wm1(self, event: Event) -> bool:
        if event.tag not in {"SENSOR", "SENSOR_FAST"}:
            return False
        return canonicalize_sensor(event.value).lower() == "wm1"

    def _apply_trial_tag(self, trial: Trial, event: Event) -> None:
        if event.tag == "CUE1":
            trial.cue1 = event.value
            if trial.cue1_us is None:
                trial.cue1_us = event.mega_us
        elif event.tag == "CUE2":
            trial.cue2 = event.value
            if trial.cue2_us is None:
                trial.cue2_us = event.mega_us
        elif event.tag == "WM_SEQ" and event.value == "CUE1":
            if trial.cue1_us is None:
                trial.cue1_us = event.mega_us
        elif event.tag == "WM_SEQ" and event.value == "CUE2":
            if trial.cue2_us is None:
                trial.cue2_us = event.mega_us
        elif event.tag == "CORRECT_TURN":
            trial.correct_side = event.value.lower()
        elif event.tag in {"SENSOR", "SENSOR_FAST"}:
            sensor = canonicalize_sensor(event.value).lower()
            if sensor.startswith("lick_") and trial.chosen_side == NA_STRING:
                trial.chosen_side = sensor.split("_", 1)[1]
            self._update_trial_from_mega_event(trial, event)

    def _finish_trial(self, trial: Trial) -> None:
        if trial.chosen_side != NA_STRING and trial.correct_side != NA_STRING:
            trial.outcome = "correct" if trial.chosen_side == trial.correct_side else "incorrect"
        elif trial.reward_delivered:
            trial.outcome = "correct"
        elif trial.punishment_delivered:
            trial.outcome = "incorrect"
        elif trial.outcome == NA_STRING:
            trial.outcome = "no_response"
