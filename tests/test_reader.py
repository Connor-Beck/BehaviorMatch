from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from behaviormatch import discover_data_root, discovery, load_session
from behaviormatch.pipeline import parse_group
from behaviormatch.reader import MIN_PARSER_VERSION, _check_parser_version, _version_tuple


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FIXTURE_CODEV45 = FIXTURES / "codev4_5"
FIXTURE_WM = FIXTURES / "wm_behavior"


def _parse_into_session_dir(fixture_dir: Path, dest_root: Path) -> Path:
    group = discovery.walk(fixture_dir)[0]
    session_dir = dest_root / group.base_name
    session_dir.mkdir(parents=True, exist_ok=True)
    parse_group(group, output_dir=session_dir, on_existing="overwrite")
    return session_dir


def test_load_session_wm_behavior(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_WM, tmp_path)
    session = load_session(session_dir)

    assert session.firmware == "WM_behavior"
    assert session.parser_version == "0.2.0"
    assert session.n_trials == 46
    assert isinstance(session.has_blackfly, bool)
    assert session.session_t0_unix > 0
    assert session.parse_status in {"clean", "partial"}

    assert isinstance(session.events, pd.DataFrame)
    assert len(session.events) > 0
    assert {"t_session_s", "pc_ts", "kind", "tag", "value"}.issubset(session.events.columns)

    assert isinstance(session.trials, pd.DataFrame)
    assert len(session.trials) == 46
    assert "trial_index" in session.trials.columns
    assert session.trials["trial_index"].iloc[0] == 1
    assert session.trials["trial_index"].is_monotonic_increasing
    assert session.trials["outcome"].iloc[0] == "incorrect"

    assert "clock_corrections" not in session.timing
    assert isinstance(session.clock_corrections, dict)
    assert session.curation is None
    assert session.curation_h5_path is None


def test_load_session_codev45_with_imaging(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_CODEV45, tmp_path)
    session = load_session(session_dir)

    assert session.firmware == "CodeV4_5"
    assert session.n_trials == 2
    assert "hardware_frames" in session.timing
    assert "behavior_frames_mkv" in session.timing
    assert "mega_sync" in session.timing
    assert isinstance(session.timing["mega_sync"], pd.DataFrame)
    assert len(session.timing["mega_sync"]) == 2

    trial_events = session.get_trial_events(1)
    assert isinstance(trial_events, pd.DataFrame)
    assert len(trial_events) > 0

    sensor_events = session.get_trial_sensor_events(1)
    assert isinstance(sensor_events, pd.DataFrame)
    assert "sensor" in sensor_events.columns or len(sensor_events) == 0

    mkv = session.get_trial_mkv_frames(1)
    assert isinstance(mkv, pd.DataFrame)
    assert len(mkv) >= 1

    assert session.get_trial_calcium(1) is None
    assert session.get_trial_dlc(1) is None


def test_load_session_reads_curation_when_present(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_CODEV45, tmp_path)
    base = session_dir.name
    curation_path = session_dir / f"{base}_curation.h5"

    str_dt = h5py.string_dtype(encoding="utf-8")
    with h5py.File(curation_path, "w") as h5:
        cur = h5.create_group("curation")
        cur.attrs["rules_version"] = "0.1.0"
        cur.attrs["rules_hash"] = "deadbeef"
        cur.create_dataset("trial_num", data=np.array([1, 2], dtype=np.int64))
        cur.create_dataset("online_status", data=np.array(["valid", "valid"], dtype=str_dt))
        cur.create_dataset("offline_status", data=np.array(["valid", "no_reward"], dtype=str_dt))
        cur.create_dataset("effective_start_ts", data=np.array([10.0, 50.0], dtype=np.float64))

    session = load_session(session_dir)
    assert session.curation is not None
    assert {"trial_num", "online_status", "offline_status"}.issubset(session.curation.columns)
    assert session.curation["online_status"].tolist() == ["valid", "valid"]
    assert session.curation_attrs["rules_version"] == "0.1.0"
    assert session.curation_h5_path == curation_path


def test_load_session_with_curation_false_skips_curation(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_CODEV45, tmp_path)
    base = session_dir.name
    str_dt = h5py.string_dtype(encoding="utf-8")
    with h5py.File(session_dir / f"{base}_curation.h5", "w") as h5:
        cur = h5.create_group("curation")
        cur.create_dataset("trial_num", data=np.array([1], dtype=np.int64))
        cur.create_dataset("online_status", data=np.array(["valid"], dtype=str_dt))

    session = load_session(session_dir, with_curation=False)
    assert session.curation is None
    assert session.curation_h5_path is None


def test_get_trial_calcium_reads_embedded_data(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_CODEV45, tmp_path)
    base = session_dir.name

    n_cells, n_volumes = 4, 10
    f_raw = np.random.rand(n_cells, n_volumes).astype(np.float32)
    dff = (f_raw - f_raw.mean(axis=1, keepdims=True)).astype(np.float32)
    t_volume = np.linspace(100.0, 110.0, n_volumes).astype(np.float64)
    event_dtype = np.dtype(
        [
            ("cell_idx", "<u4"),
            ("onset_volume", "<i4"),
            ("offset_volume", "<i4"),
            ("peak_volume", "<i4"),
            ("amplitude", "<f4"),
            ("duration_s", "<f4"),
        ]
    )
    events = np.array([(0, 1, 4, 2, 0.7, 0.5), (2, 5, 9, 7, 0.4, 0.4)], dtype=event_dtype)

    with h5py.File(session_dir / f"{base}_curation.h5", "w") as h5:
        trial_grp = h5.create_group("trials/0001/calcium")
        trial_grp.attrs["extraction_id"] = "test_extract_001"
        trial_grp.attrs["n_volumes"] = n_volumes
        trial_grp.create_dataset("F", data=f_raw)
        trial_grp.create_dataset("dff", data=dff)
        trial_grp.create_dataset("t_volume_s", data=t_volume)
        trial_grp.create_dataset("events", data=events)

    session = load_session(session_dir)
    cal = session.get_trial_calcium(1)
    assert cal is not None
    assert cal["F"].shape == (n_cells, n_volumes)
    assert cal["dff"].shape == (n_cells, n_volumes)
    assert cal["t_volume_s"].shape == (n_volumes,)
    assert isinstance(cal["events"], pd.DataFrame)
    assert len(cal["events"]) == 2
    assert cal["attrs"]["extraction_id"] == "test_extract_001"
    assert session.get_trial_calcium(2) is None


def test_get_trial_dlc_reads_embedded_data(tmp_path: Path) -> None:
    session_dir = _parse_into_session_dir(FIXTURE_CODEV45, tmp_path)
    base = session_dir.name

    n_bp, n_frames = 3, 50
    x = np.random.rand(n_bp, n_frames).astype(np.float32)
    y = np.random.rand(n_bp, n_frames).astype(np.float32)
    likelihood = np.random.rand(n_bp, n_frames).astype(np.float32)
    t_mkv = np.linspace(100.0, 105.0, n_frames).astype(np.float64)

    with h5py.File(session_dir / f"{base}_curation.h5", "w") as h5:
        trial_grp = h5.create_group("trials/0001/dlc")
        trial_grp.attrs["extraction_id"] = "dlc_test_001"
        trial_grp.attrs["mkv_frame_i_start"] = 1000
        trial_grp.attrs["mkv_frame_i_end"] = 1049
        trial_grp.create_dataset("x", data=x)
        trial_grp.create_dataset("y", data=y)
        trial_grp.create_dataset("likelihood", data=likelihood)
        trial_grp.create_dataset("t_mkv_s", data=t_mkv)

    session = load_session(session_dir)
    dlc = session.get_trial_dlc(1)
    assert dlc is not None
    assert dlc["x"].shape == (n_bp, n_frames)
    assert dlc["likelihood"].shape == (n_bp, n_frames)
    assert dlc["t_mkv_s"].shape == (n_frames,)
    assert dlc["attrs"]["extraction_id"] == "dlc_test_001"


def test_load_session_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_session(tmp_path / "does-not-exist")


def test_load_session_missing_h5_raises(tmp_path: Path) -> None:
    empty = tmp_path / "Empty_session"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="Parser output not found"):
        load_session(empty)


def test_version_check_rejects_old_parser_version(tmp_path: Path) -> None:
    fake = tmp_path / "Old_session"
    fake.mkdir()
    with h5py.File(fake / "Old_session.h5", "w") as h5:
        sg = h5.create_group("session")
        sg.attrs["parser_version"] = "0.1.0"
    with pytest.raises(ValueError, match="parser_version"):
        load_session(fake)


def test_version_tuple_handles_suffixes() -> None:
    assert _version_tuple("0.2.0") == (0, 2, 0)
    assert _version_tuple("0.2.0a1") == (0, 2, 0)
    assert _version_tuple("1.0") == (1, 0)


def test_version_check_passes_at_minimum() -> None:
    _check_parser_version(MIN_PARSER_VERSION, Path("/dev/null"))


def test_discover_data_root_lists_mice_and_sessions(tmp_path: Path) -> None:
    for mouse in ("1363", "9999"):
        (tmp_path / mouse).mkdir()
    for session_name in ("Sess_A", "Sess_B"):
        session_dir = tmp_path / "1363" / session_name
        session_dir.mkdir()
        (session_dir / f"{session_name}.h5").touch()
    parsed = tmp_path / "9999" / "Sess_C"
    parsed.mkdir()
    (parsed / "Sess_C.h5").touch()
    (tmp_path / "9999" / "Sess_D").mkdir()

    result = discover_data_root(tmp_path)
    assert set(result.keys()) == {"1363", "9999"}
    assert sorted(path.name for path in result["1363"]) == ["Sess_A", "Sess_B"]
    assert [path.name for path in result["9999"]] == ["Sess_C"]


def test_discover_data_root_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_data_root(tmp_path / "nope")
