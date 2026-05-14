from __future__ import annotations

import re

from ..schema import (
    Session,
    Trial,
    TRIAL_TYPE_RANDOM_CUE,
    TRIAL_TYPE_STANDARD,
    parse_mega_event,
    to_int,
)
from .base import BaseExtractor, infer_received_turn, parse_total_trial_line


TRIAL_INDEX_RE = re.compile(r"TrialIndex:\s*(\d+)", re.I)


class CodeV45Extractor(BaseExtractor):
    def parse(self) -> Session:
        rows = self.read_rows()
        session = self.new_session(rows)

        active: Trial | None = None
        pending_random_cue = False
        last_correct_count = 0

        for row in rows:
            event = self.event_from_row(row, session.session_t0_unix)
            text = event.raw_text
            mega = parse_mega_event(text)

            try:
                start_index: int | None = None
                start_mega_us: int | None = None
                if mega and mega[1] == "TRIAL_START_INDEX":
                    start_index = to_int(mega[2])
                    start_mega_us = mega[0]
                else:
                    match = TRIAL_INDEX_RE.search(text)
                    if match and active is None:
                        start_index = to_int(match.group(1))

                if ">>> RANDOM CUE TRIAL" in text:
                    pending_random_cue = True

                if start_index is not None:
                    if active is not None:
                        session.trials.append(active)
                    active = Trial(
                        trial_index=start_index or len(session.trials) + 1,
                        trial_type=TRIAL_TYPE_RANDOM_CUE if pending_random_cue else TRIAL_TYPE_STANDARD,
                        t_start_s=event.t_session_s,
                        t_start_mega_us=start_mega_us,
                    )
                    self.record_trial_event(active, event, session)
                    continue

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

    def _close_total_trial(self, trial: Trial, text: str, last_correct_count: int) -> int:
        fields = parse_total_trial_line(text)
        parsed_index = to_int(fields.get("total_trial"))
        if parsed_index is not None:
            trial.trial_index = parsed_index

        correct_count = to_int(fields.get("correct_count"), last_correct_count) or last_correct_count
        trial.outcome = "correct" if correct_count > last_correct_count else "incorrect"

        received = fields.get("received_turn")
        if received:
            trial.chosen_side = infer_received_turn(received)

        stage1 = to_int(fields.get("stage1_active_phase"))
        if stage1 is not None:
            trial.level = stage1

        delay = to_int(fields.get("wm_delay_ms"))
        if delay is not None:
            trial.delay_ms = delay

        return correct_count
