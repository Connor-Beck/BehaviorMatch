# BehaviorMatch

BehaviorMatch is a headless CLI for turning MouseMaze behavior logs into one
uniform per-session output. It reads a session `_console.csv` or legacy
`<base>.csv`, attaches timing sidecars when present, detects the firmware
family, and writes a canonical `<base>.h5`.

Supported input layouts:

- Explicit files selected one by one.
- A flat folder where all session files live together.
- A folder with files split across subfolders, such as `console/`,
  `mega_sync/`, `mini2p_frames/`, `hardware_frames/`, and `ffv1_frames/`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

For MATLAB export support:

```bash
python -m pip install -e ".[mat]"
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## CLI

Parse one flat session folder in place:

```bash
behaviormatch /path/to/session --on-existing overwrite
```

Parse selected files:

```bash
behaviormatch \
  /path/to/Freelymoving_1363_tr1_0504_185130_091_console.csv \
  /path/to/Freelymoving_1363_tr1_0504_185130_091_mega_sync.csv \
  /path/to/Freelymoving_1363_tr1_0504_185130_091_mini2P_frames.csv \
  --output-dir /path/to/parsed
```

Parse a standard kind-separated folder:

```bash
behaviormatch /path/to/session_root --recursive --output-dir /path/to/parsed
```

Dry-run discovery:

```bash
behaviormatch /path/to/data --recursive --dry-run
```

Optional exports:

```bash
behaviormatch /path/to/session --emit-csv --emit-mat
```

`--emit-csv` writes:

- `<base>_trials.csv`
- `<base>_events.csv`
- `<base>_sensor_events.csv`
- `<base>_summary.json`

## Output

The canonical output is `<base>.h5`:

```text
<base>.h5
├── /session/.attrs
├── /session/events
├── /session/timing/
│   ├── hardware_frames
│   ├── behavior_frames_mkv
│   ├── mini2p_frames
│   ├── mega_sync
│   └── clock_corrections.attrs
└── /trials/
    └── 0001/
        ├── events
        ├── sensor_events
        ├── mkv_frames
        └── mini2p_frames
```

See [docs/storage-spec.md](docs/storage-spec.md) for the full schema.

## Supported Logs

- `WM_behavior`, structured `WM_TRIAL_START` / `WM_TRIAL_SUMMARY`.
- `CodeV4_5`, `TRIAL_START_INDEX` events.
- `CodeV4_4`, legacy free-text trials.
- Stage 0 habituation logs, converted into synthetic trials from `WM1` to a
  return sensor.
