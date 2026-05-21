from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import pytest

from behaviormatch import discovery
from behaviormatch.cli import build_parser
from behaviormatch.detection import identify
from behaviormatch.pipeline import parse_group
from behaviormatch.schema import ClockCorrections, Event, Session, TimingData
from behaviormatch.timing import _correct_event_times, apply_corrections


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FIXTURE_WM = FIXTURES / "wm_behavior"
FIXTURE_CODEV45 = FIXTURES / "codev4_5"
FIXTURE_MEGA_SYNC_ONLY = FIXTURES / "mega_sync_only"
FIXTURE_CODEV44_WITH_MEGA = FIXTURES / "codev4_4_with_mega"


def test_cli_emits_mat_by_default() -> None:
    parser = build_parser()

    args = parser.parse_args(["/tmp/session"])
    no_mat_args = parser.parse_args(["/tmp/session", "--no-emit-mat"])

    assert args.emit_mat is True
    assert no_mat_args.emit_mat is False


def test_discovery_prefers_console_log() -> None:
    groups = discovery.walk(FIXTURE_WM)

    assert len(groups) == 1
    assert groups[0].primary_log.name.endswith("_console.csv")
    assert groups[0].behavior_log is not None


def test_discovery_groups_explicit_files() -> None:
    paths = [
        FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_console.csv",
        FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_mega_sync.csv",
        FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_hardware_frames.csv",
        FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_mini2P_frames.csv",
        FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_ffv1_frames.csv",
    ]

    groups = discovery.walk_many(paths)

    assert len(groups) == 1
    group = groups[0]
    assert group.console_log == paths[0]
    assert group.mega_sync == paths[1]
    assert group.hardware_frames == paths[2]
    assert group.mini2p_frames == paths[3]
    assert group.ffv1_frames == paths[4]


def test_discovery_sidecar_file_selects_full_session() -> None:
    mega_sync_path = FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_mega_sync.csv"

    groups = discovery.walk(mega_sync_path)

    assert len(groups) == 1
    group = groups[0]
    assert group.console_log == FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_console.csv"
    assert group.mega_sync == mega_sync_path
    assert group.hardware_frames == FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_hardware_frames.csv"
    assert group.mini2p_frames == FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_mini2P_frames.csv"
    assert group.ffv1_frames == FIXTURE_CODEV45 / "Freelymoving_2001_codev45_0101_000000_000_ffv1_frames.csv"

    cli_groups = discovery.walk_many([mega_sync_path])
    assert len(cli_groups) == 1
    assert cli_groups[0].console_log == group.console_log
    assert cli_groups[0].mega_sync == group.mega_sync


def test_discovery_groups_kind_separated_subfolders(tmp_path: Path) -> None:
    placements = {
        "console": "Freelymoving_2001_codev45_0101_000000_000_console.csv",
        "mega_sync": "Freelymoving_2001_codev45_0101_000000_000_mega_sync.csv",
        "hardware_frames": "Freelymoving_2001_codev45_0101_000000_000_hardware_frames.csv",
        "mini2p_frames": "Freelymoving_2001_codev45_0101_000000_000_mini2P_frames.csv",
        "ffv1_frames": "Freelymoving_2001_codev45_0101_000000_000_ffv1_frames.csv",
    }
    for folder, filename in placements.items():
        target_dir = tmp_path / folder
        target_dir.mkdir()
        shutil.copy2(FIXTURE_CODEV45 / filename, target_dir / filename)

    groups = discovery.walk(tmp_path, recursive=True)

    assert len(groups) == 1
    assert groups[0].console_log is not None
    assert groups[0].console_log.parent.name == "console"
    assert groups[0].mega_sync is not None
    assert groups[0].mega_sync.parent.name == "mega_sync"


def test_discovery_kind_separated_sidecar_file_selects_full_session(tmp_path: Path) -> None:
    placements = {
        "console": "Freelymoving_2001_codev45_0101_000000_000_console.csv",
        "mega_sync": "Freelymoving_2001_codev45_0101_000000_000_mega_sync.csv",
        "hardware_frames": "Freelymoving_2001_codev45_0101_000000_000_hardware_frames.csv",
        "mini2p_frames": "Freelymoving_2001_codev45_0101_000000_000_mini2P_frames.csv",
        "ffv1_frames": "Freelymoving_2001_codev45_0101_000000_000_ffv1_frames.csv",
    }
    for folder, filename in placements.items():
        target_dir = tmp_path / folder
        target_dir.mkdir()
        shutil.copy2(FIXTURE_CODEV45 / filename, target_dir / filename)

    groups = discovery.walk(tmp_path / "mega_sync" / placements["mega_sync"])

    assert len(groups) == 1
    assert groups[0].console_log is not None
    assert groups[0].console_log.parent.name == "console"
    assert groups[0].mega_sync is not None
    assert groups[0].mega_sync.parent.name == "mega_sync"


def test_parse_real_wm_behavior_fixture(tmp_path: Path) -> None:
    group = discovery.walk(FIXTURE_WM)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert result.session is not None
    assert result.session.source_log == group.behavior_log
    assert result.session.n_trials == 46
    assert result.session.n_standard_trials == 30
    assert result.session.trials[0].outcome == "incorrect"
    assert result.session.trials[0].cue1_us == 124513796
    assert result.session.trials[0].cue2_us == 124813552
    assert result.session.trials[0].gate_open_us == 125812936
    assert result.session.trials[0].lick_us == 133765296
    assert result.session.trials[0].events[-1].tag == "WM_TRIAL_SUMMARY"
    assert result.session.events
    assert len(result.session.trials[0].events) > 0
    assert result.h5_path is not None

    with h5py.File(result.h5_path, "r") as h5:
        assert h5["session"].attrs["firmware"] == "WM_behavior"
        assert h5["session"].attrs["n_trials"] == 46
        assert h5["session"].attrs["parser_version"] == "0.2.0"
        assert "events" in h5["session"]
        assert "clock_corrections" in h5["session"]["timing"]
        assert h5["trials"]["0001"]["events"].shape[0] > 0
        assert "sensor_events" in h5["trials"]["0001"]


def test_codev45_timing_sidecars(tmp_path: Path) -> None:
    groups = discovery.walk(FIXTURE_CODEV45)
    assert [group.base_name for group in groups] == ["Freelymoving_2001_codev45_0101_000000_000"]

    group = groups[0]
    firmware, _, _ = identify(group)
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite", emit_csv=True)

    assert firmware == "CodeV4_5"
    assert result.session is not None
    assert result.session.n_trials == 2
    assert result.session.trials[0].outcome == "correct"
    assert result.session.trials[1].trial_type == "random_cue"
    assert result.session.trials[0].frames.mkv_frames[0]["hardware_frame_number"] >= 1
    assert len(result.csv_paths) == 4
    assert all(path.exists() for path in result.csv_paths)

    with h5py.File(result.h5_path, "r") as h5:
        assert "hardware_frames" in h5["session"]["timing"]
        assert "behavior_frames_mkv" in h5["session"]["timing"]
        assert h5["session"]["timing"]["mega_sync"].shape[0] == 2
        assert h5["trials"]["0001"]["mkv_frames"].shape[0] >= 1
        assert "clock_corrections" in h5["session"]["timing"]


def test_parse_mega_sync_only_fixture(tmp_path: Path) -> None:
    mega_sync_path = FIXTURE_MEGA_SYNC_ONLY / "Freelymoving_9999_tr3_0101_000000_000_mega_sync.csv"
    groups = discovery.walk(mega_sync_path)

    assert len(groups) == 1
    group = groups[0]
    assert group.primary_log == mega_sync_path
    assert group.mega_sync == mega_sync_path

    firmware, _, _ = identify(group)
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite", emit_mat=True)

    assert firmware == "MegaSync"
    assert result.session is not None
    assert result.session.parse_status == "partial"
    assert result.session.n_trials == 2
    assert [trial.outcome for trial in result.session.trials] == ["correct", "incorrect"]
    assert result.session.trials[0].sensor_events
    assert result.mat_path is not None
    assert result.mat_path.exists()

    with h5py.File(result.h5_path, "r") as h5:
        assert h5["session"].attrs["firmware"] == "MegaSync"
        assert h5["session"].attrs["n_trials"] == 2
        assert h5["session"]["timing"]["mega_sync"].shape[0] == 19
        assert h5["trials"]["0001"]["sensor_events"].shape[0] >= 5


def test_parse_mega_sync_only_wm_seq_format(tmp_path: Path) -> None:
    mega_sync_path = tmp_path / "Freelymoving_9998_tr1_0101_000000_000_mega_sync.csv"
    mega_sync_path.write_text(
        "\n".join(
            [
                "uno_pc_time_sec,uno_edge_us,mega_evt_pc_time_sec,mega_evt_us,tag,value,dropped_reported",
                "1000.000,100,1000.000,500,CMD,START_BEHAVIOR,0",
                "1001.000,1100,1001.000,1500,WM_SEQ_START_MS,1,0",
                "1001.100,1200,1001.100,1600,TONE_PLAY_HZ,4000,0",
                "1001.110,1210,1001.110,1610,WM_SEQ,CUE1,0",
                "1001.500,1500,1001.500,2000,TONE_PLAY_HZ,13000,0",
                "1001.510,1510,1001.510,2010,WM_SEQ,CUE2,0",
                "1002.000,2000,1002.000,2500,WM_GATE_CMD,91,0",
                "1002.010,2010,1002.010,2510,WM_SEQ,DONE,0",
                "1003.000,3000,1003.000,3500,SENSOR,Gate,0",
                "1004.000,4000,1004.000,4500,SENSOR,WM2,0",
                "1005.000,5000,1005.000,5500,SENSOR,Lick Left,0",
                "1005.100,5100,1005.100,5600,REWARD,left,0",
                "1006.000,6000,1006.000,6500,SENSOR,Return Left,0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    group = discovery.walk(mega_sync_path)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert result.session is not None
    assert result.session.n_trials == 1
    trial = result.session.trials[0]
    assert trial.cue1_us == 1610
    assert trial.cue2_us == 2010
    assert trial.gate_open_us == 2500
    assert trial.lick_us == 5500
    assert trial.outcome == "correct"
    assert trial.lick_us > trial.cue2_us


def test_bad_mega_uno_fit_keeps_pc_side_mega_event_times() -> None:
    event = Event(
        t_session_s=10.0,
        pc_ts=1010.0,
        kind="MEGA_EVT",
        mega_us=1000,
        tag="WM_SEQ",
        value="CUE2",
    )
    corrections = ClockCorrections(
        uno_pc_slope=1.0,
        uno_pc_intercept=0.0,
        n_uno_pc_anchors=2,
        mega_uno_slope=10.0,
        mega_uno_intercept=0.0,
        mega_uno_residual_us=1_000_000.0,
        n_mega_uno_anchors=2,
    )

    _correct_event_times([event], corrections, session_t0=1000.0)

    assert event.t_session_s == 10.0


def test_bad_mega_uno_fit_keeps_pc_side_mega_sync_rows(tmp_path: Path) -> None:
    session = Session(
        base_name="bad_fit",
        source_log=tmp_path / "bad_fit_mega_sync.csv",
        session_t0_unix=1000.0,
    )
    timing = TimingData(
        mega_sync=[
            {
                "uno_edge_us": 0,
                "mega_evt_us": 0,
                "mega_evt_pc_time_sec": 1001.0,
                "uno_pc_time_sec": 1001.0,
                "t_session_s": 0.0,
            },
            {
                "uno_edge_us": 1_000_000,
                "mega_evt_us": 1_000_000,
                "mega_evt_pc_time_sec": 1002.0,
                "uno_pc_time_sec": 1002.0,
                "t_session_s": 0.0,
            },
            {
                "uno_edge_us": 100_000_000,
                "mega_evt_us": 2_000_000,
                "mega_evt_pc_time_sec": 1003.0,
                "uno_pc_time_sec": 1100.0,
                "t_session_s": 0.0,
            },
        ]
    )

    applied = apply_corrections(timing, ClockCorrections(), session.session_t0_unix, session)

    assert "mega_uno_lin" not in applied
    assert [row["t_session_s"] for row in timing.mega_sync] == [1.0, 2.0, 3.0]
    assert any("mega_uno_residual_us" in error for error in session.parse_errors)


def test_codev44_legacy_fixture(tmp_path: Path) -> None:
    group = discovery.walk(FIXTURES / "codev4_4")[0]
    firmware, _, _ = identify(group)
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert firmware == "CodeV4_4"
    assert result.session is not None
    assert result.session.n_trials == 2
    assert [trial.outcome for trial in result.session.trials] == ["correct", "incorrect"]
    assert result.session.trials[0].correct_side == "right"


def test_stage0_synthetic_trials(tmp_path: Path) -> None:
    group = discovery.walk(FIXTURES / "stage0")[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert result.session is not None
    assert result.session.task == "habituation"
    assert result.session.n_trials == 2
    assert all(trial.trial_type == "synthetic" for trial in result.session.trials)


def test_mat_export_handles_aborted_trial(tmp_path: Path) -> None:
    scipy_io = pytest.importorskip("scipy.io")
    group = discovery.walk(FIXTURES / "aborted_codev4_4")[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite", emit_mat=True)

    assert result.session is not None
    assert result.status == "partial"
    assert result.mat_path is not None
    assert result.mat_path.exists()

    data = scipy_io.loadmat(result.mat_path, squeeze_me=True, struct_as_record=False)
    session = data["session"]
    trials = session.trials
    if hasattr(trials, "outcome"):
        assert trials.outcome == "aborted"
    else:
        assert trials[0].outcome == "aborted"


def test_codev44_with_mega_uses_behavior_log_for_timing(tmp_path: Path) -> None:
    """CodeV4_4 sessions with a behavior log carrying MEGA_EVT events should
    extract µs-precision timing from those events rather than the console log."""
    group = discovery.walk(FIXTURE_CODEV44_WITH_MEGA)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert result.session is not None
    assert result.session.n_trials == 3
    t1, t2, t3 = result.session.trials

    # gate_open_us comes from WM_GATE_CMD=91 MEGA_EVT (not available in console log)
    assert t1.gate_open_us == 39537720
    assert t2.gate_open_us == 106611012
    assert t3.gate_open_us == 180000000

    # lick_us is µs-precise from SENSOR,Lick MEGA_EVT (console log only has ms precision)
    assert t1.lick_us == 69319744
    assert t2.lick_us == 130000000
    assert t3.lick_us == 200000000

    # wm2_us extracted from SENSOR,WM2
    assert t1.wm2_us == 54391928
    assert t2.wm2_us == 120000000

    # return_us extracted from SENSOR,Return Left/Right
    assert t1.return_us == 89958808
    assert t2.return_us == 140000000


def test_codev44_with_mega_trial_start_uses_wm1_not_cue_echo(tmp_path: Path) -> None:
    """Trial t_start_s must reflect the WM1 sensor entry, not the config-time
    Cue1: echo that appears at session start before the mouse enters the maze."""
    group = discovery.walk(FIXTURE_CODEV44_WITH_MEGA)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    t1, t2, t3 = result.session.trials

    # WM1 fires at 18562 ms ≈ 18.5 s; the Cue1: echo is at t=0.566 s
    assert t1.t_start_s > 15.0, f"Trial 1 t_start_s={t1.t_start_s:.3f} should be ~18.5 s (WM1 entry)"

    # t_start_mega_us set from WM1 SENSOR or TRIAL_START_INDEX
    assert t1.t_start_mega_us == 18562432
    assert t2.t_start_mega_us in (103587500, 103595004)  # WM1 or TRIAL_START_INDEX
    assert t3.t_start_mega_us in (160000000, 165000000)


def test_codev44_with_mega_outcome_from_outcome_event(tmp_path: Path) -> None:
    """OUTCOME MEGA_EVT values (SHAPING_REWARD, CORRECT, INCORRECT) must be
    mapped to trial.outcome rather than being silently dropped."""
    group = discovery.walk(FIXTURE_CODEV44_WITH_MEGA)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    t1, t2, t3 = result.session.trials
    assert t1.outcome == "shaping_reward"
    assert t2.outcome == "correct"
    assert t3.outcome == "incorrect"


def test_codev44_with_mega_chosen_side_from_mouse_choice(tmp_path: Path) -> None:
    """MOUSE_CHOICE MEGA_EVT should populate chosen_side."""
    group = discovery.walk(FIXTURE_CODEV44_WITH_MEGA)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    t1, t2, t3 = result.session.trials
    assert t1.chosen_side == "left"
    assert t2.chosen_side == "right"
    assert t3.chosen_side == "right"


def test_codev44_with_mega_cue_frequencies_correct(tmp_path: Path) -> None:
    """cue1/cue2 store the tone frequency strings; cue1_us/cue2_us remain None
    because the old firmware logs cue frequency as config, not a play timestamp."""
    group = discovery.walk(FIXTURE_CODEV44_WITH_MEGA)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    t1, t2, t3 = result.session.trials
    assert t1.cue1 == "13000"
    assert t1.cue2 == "13000"
    assert t2.cue1 == "4000"
    assert t2.correct_side == "right"
    assert t3.correct_side == "left"
    # Old firmware doesn't log when the cue plays — timestamps unavailable
    assert t1.cue1_us is None
    assert t1.cue2_us is None
