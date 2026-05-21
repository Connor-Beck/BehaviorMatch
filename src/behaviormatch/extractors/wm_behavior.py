from __future__ import annotations

from ..schema import Session, Trial, parse_key_values, to_int
from .base import BaseExtractor


class WMBehaviorExtractor(BaseExtractor):
    def parse(self) -> Session:
        rows = self._read_best_event_rows()
        session = self.new_session(rows)
        session.metadata["event_source_log"] = str(rows[0].path)

        active: Trial | None = None
        saw_end = False

        for row in rows:
            event = self.event_from_row(row, session.session_t0_unix)
            text = event.raw_text

            try:
                if text.startswith("WM_META"):
                    self._apply_wm_meta(session, text)

                if saw_end:
                    self.record_session_event(session, event)
                    continue

                if text.startswith("WM_TRIAL_START"):
                    if active is not None:
                        session.trials.append(active)
                    values = parse_key_values(text)
                    trial_index = to_int(values.get("trial_index"), len(session.trials) + 1) or len(session.trials) + 1
                    active = Trial(trial_index=trial_index, t_start_s=event.t_session_s)
                    active.apply_values(values)
                    self.record_trial_event(active, event, session)
                    continue

                if active is not None:
                    self.record_trial_event(active, event, session)
                    if text.startswith("WM_TRIAL_SUMMARY"):
                        values = parse_key_values(text)
                        active.apply_values(values)
                        active.t_end_s = event.t_session_s
                        session.trials.append(active)
                        active = None
                    elif text.startswith("WM_END"):
                        self._apply_wm_end(session, text)
                        if active.t_end_s is None:
                            active.t_end_s = event.t_session_s
                        session.trials.append(active)
                        active = None
                        saw_end = True
                    continue

                self.record_session_event(session, event)
                if text.startswith("WM_END"):
                    self._apply_wm_end(session, text)
                    saw_end = True
            except Exception as exc:
                self.mark_partial(session, f"Row {row.row_index}: {exc}")

        if active is not None:
            if active.t_end_s is None:
                self.finish_trial_as_aborted(session, active)
            else:
                session.trials.append(active)

        return self.finalize_session(session)

    def _read_best_event_rows(self):
        rows = self.read_rows()
        behavior_log = self.group.behavior_log
        if behavior_log is None or behavior_log == self.group.primary_log:
            return rows

        try:
            behavior_rows = self.read_rows(behavior_log)
        except Exception:
            return rows

        if self._has_wm_trials(behavior_rows) and self._mega_event_count(behavior_rows) > self._mega_event_count(rows):
            return behavior_rows
        return rows

    def _has_wm_trials(self, rows) -> bool:
        return any(row.message.startswith("WM_TRIAL_START") for row in rows)

    def _mega_event_count(self, rows) -> int:
        return sum(1 for row in rows if row.message.startswith("MEGA_EVT,"))

    def _apply_wm_end(self, session: Session, text: str) -> None:
        values = parse_key_values(text)
        for source_key, attr_key in (
            ("end_reason", "end_reason"),
            ("n_standard", "wm_end_n_standard"),
            ("n_correct_standard", "wm_end_n_correct_standard"),
            ("final_level", "final_level"),
        ):
            if source_key not in values:
                continue
            parsed = to_int(values[source_key])
            session.metadata[attr_key] = parsed if parsed is not None else values[source_key]
