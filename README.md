# BehaviorMatch

BehaviorMatch is a headless CLI for turning MouseMaze behavior logs into one
uniform per-session output. It reads a session `_console.csv` or legacy
`<base>.csv`, attaches timing sidecars when present, detects the firmware
family, and writes a canonical `<base>.h5` output for downstream analysis.

Supported input layouts:

- Explicit files selected one by one.
- A flat folder where all session files live together.
- A folder with files split across subfolders, such as `console/`,
  `mega_sync/`, `mini2p_frames/`, `hardware_frames/`, and `ffv1_frames/`.

## Install

Create a virtual environment, then install the package:

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

For development and testing:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Run the CLI help to see all available options:

```bash
behaviormatch --help
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

## MATLAB Import

Use `--emit-mat` when parsing, then add the BehaviorMatch folder to MATLAB's
path and load the exported `.mat` file with the root-level `load_session.m`
helper:

```matlab
addpath('/path/to/BehaviorMatch')

session = load_session('/path/to/parsed/Freelymoving_1363_tr1_0504_185130_091.mat');
```

The helper converts event, sensor, and frame structs into MATLAB tables and
converts common string fields to categoricals. Optional flags:

```matlab
session = load_session(file, 'datetime', true);  % add pc_datetime columns
session = load_session(file, 'minimal', true);   % drop audit-log event tables
```

Example access:

```matlab
session.trials(1).outcome
session.trials(1).sensor_events
session.timing.clock_corrections
```

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

## Contributing

Contributions are welcome. Please keep the repository clean by adding new
utility files to `.gitignore` and verifying changes with `python -m pytest`.

## License

This project is licensed under the MIT License.
