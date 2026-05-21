from __future__ import annotations

from ..schema import (
    NA_STRING,
    Session,
    Trial,
    TRIAL_TYPE_RANDOM_CUE,
    TRIAL_TYPE_STANDARD,
    TRIAL_TYPE_SYNTHETIC,
    parse_mega_event,
    parse_sensor_text,
    to_int,
)
from .base import BaseExtractor, infer_received_turn, parse_total_trial_line


class CodeV44Extractor(BaseExtractor):
    def parse(self) -> Session:
        rows = self._read_best_rows()
        session = self.new_session(rows)

        if str(session.metadata.get("training_stage", "")) == "0":
            return self._parse_synthetic_stage0(rows, session)

        active: Trial | None = None
        pending_random_cue = False
        last_correct_count = 0

        for row in rows:
            event = self.event_from_row(row, session.session_t0_unix)
            text = event.raw_text
            mega = parse_mega_event(text)
            try:
                if ">>> RANDOM CUE TRIAL" in text:
                    pending_random_cue = True

                # Update active trial's start time from TRIAL_START_INDEX or WM1 sensor
                if event.kind == "MEGA_EVT" and active is not None and active.t_start_mega_us is None:
                    if mega and mega[1] == "TRIAL_START_INDEX":
                        active.t_start_mega_us = mega[0]
                        active.t_start_s = event.t_session_s
                    elif event.tag == "SENSOR" and event.value == "WM1":
                        active.t_start_mega_us = event.mega_us
                        active.t_start_s = event.t_session_s

                opening_new = text.startswith("Cue1:") and (active is None or active.t_end_s is not None)
                if opening_new:
                    if active is not None:
                        session.trials.append(active)
                    active = Trial(
                        trial_index=len(session.trials) + 1,
                        trial_type=TRIAL_TYPE_RANDOM_CUE if pending_random_cue else TRIAL_TYPE_STANDARD,
                        t_start_s=event.t_session_s,
                    )

                if active is not None:
                    self._apply_legacy_line(active, text)
                    self.record_trial_event(active, event, session)
                    if "Total trial" in text:
                        last_correct_count = self._close_total_trial(active, text, last_correct_count)
                        active.t_end_s = event.t_session_s
                        pending_random_cue = False
                    continue

                self.record_session_event(session, event)
            except Exception as exc:
                self.mark_partial(session, f"Row {row.row_index}: {exc}")

        if active is not None:
            if active.t_end_s is None:
                self.finish_trial_as_aborted(session, active)
            else:
                session.trials.append(active)

        if not session.trials:
            return self._parse_synthetic_stage0(rows, session)
        return self.finalize_session(session)

    def _apply_legacy_line(self, trial: Trial, text: str) -> None:
        if text.startswith("Cue1:"):
            trial.cue1 = text.split(":", 1)[1].strip()
        elif text.startswith("Cue2:"):
            trial.cue2 = text.split(":", 1)[1].strip()
        elif text.startswith("Correct turn:"):
            trial.correct_side = text.split(":", 1)[1].strip().lower()
        elif ">>> RANDOM CUE TRIAL" in text:
            trial.trial_type = TRIAL_TYPE_RANDOM_CUE
        elif "Reward delivered for random cue trial" in text:
            trial.reward_delivered = True
            trial.outcome = "correct"

    def _read_best_rows(self):
        rows = self.read_rows()
        behavior_log = self.group.behavior_log
        if behavior_log is None or behavior_log == self.group.primary_log:
            return rows
        try:
            behavior_rows = self.read_rows(behavior_log)
        except Exception:
            return rows
        if self._mega_event_count(behavior_rows) > self._mega_event_count(rows):
            return behavior_rows
        return rows

    def _mega_event_count(self, rows) -> int:
        return sum(1 for row in rows if row.message.startswith("MEGA_EVT,"))

    def _close_total_trial(self, trial: Trial, text: str, last_correct_count: int) -> int:
        fields = parse_total_trial_line(text)
        parsed_index = to_int(fields.get("total_trial"))
        if parsed_index is not None:
            trial.trial_index = parsed_index

        correct_count = to_int(fields.get("correct_count"), last_correct_count) or last_correct_count
        if trial.outcome in (NA_STRING, "NA", ""):
            trial.outcome = "correct" if correct_count > last_correct_count else "incorrect"

        received = fields.get("received_turn")
        if received and trial.chosen_side in (NA_STRING, "NA", ""):
            trial.chosen_side = infer_received_turn(received)

        stage_phase = to_int(fields.get("stage1_active_phase"))
        if stage_phase is not None:
            trial.level = stage_phase

        delay = to_int(fields.get("wm_delay_ms"))
        if delay is not None:
            trial.delay_ms = delay

        return correct_count

    def _parse_synthetic_stage0(self, rows, session: Session) -> Session:
        session.trials.clear()
        session.events.clear()

        active: Trial | None = None
        for row in rows:
            event = self.event_from_row(row, session.session_t0_unix)
            sensor = parse_sensor_text(event.raw_text)
            sensor_name = sensor[1] if sensor else ""

            if active is None and sensor_name == "WM1":
                active = Trial(
                    trial_index=len(session.trials) + 1,
                    trial_type=TRIAL_TYPE_SYNTHETIC,
                    outcome="NA",
                    t_start_s=event.t_session_s,
                )
                self.record_trial_event(active, event, session)
                continue

            if active is not None:
                self.record_trial_event(active, event, session)
                if sensor_name.startswith("Return"):
                    active.t_end_s = event.t_session_s
                    session.trials.append(active)
                    active = None
                continue

            self.record_session_event(session, event)

        if active is not None:
            self.finish_trial_as_aborted(session, active)
        return self.finalize_session(session)
