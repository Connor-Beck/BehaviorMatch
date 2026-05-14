from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import pytest

from behaviormatch import discovery
from behaviormatch.detection import identify
from behaviormatch.pipeline import parse_group


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FIXTURE_WM = FIXTURES / "wm_behavior"
FIXTURE_CODEV45 = FIXTURES / "codev4_5"


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


def test_parse_real_wm_behavior_fixture(tmp_path: Path) -> None:
    group = discovery.walk(FIXTURE_WM)[0]
    result = parse_group(group, output_dir=tmp_path, on_existing="overwrite")

    assert result.session is not None
    assert result.session.n_trials == 46
    assert result.session.n_standard_trials == 30
    assert result.session.trials[0].outcome == "incorrect"
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
