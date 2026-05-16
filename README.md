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

Run these commands from the BehaviorMatch repository root, which is the folder
that contains `pyproject.toml`.

### macOS/Linux virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### Windows Conda environment

Use Anaconda Prompt or a PowerShell session where `conda activate` works:

```bat
cd C:\Users\<username>\Documents\GitHub\BehaviorMatch

conda create -n behaviormatch python=3.11 -y
conda activate behaviormatch

python -m pip install --upgrade pip
python -m pip install -e .
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

On Windows, this equivalent form is often more reliable because it does not
depend on the `behaviormatch` launcher being on `PATH`:

```bat
python -m behaviormatch --help
```

## CLI

The clearest input is the session folder. A session folder should contain a
primary log such as `<base>_console.csv` or `<base>.csv`; BehaviorMatch will
attach matching sidecars such as `<base>_mega_sync.csv`,
`<base>_mini2P_frames.csv`, `<base>_hardware_frames.csv`, and
`<base>_ffv1_frames.csv` when present.

You can also select a sidecar file directly, including `<base>_mega_sync.csv`.
BehaviorMatch uses the shared basename to find the matching primary log and
other sidecars. If no primary log is available, a `_mega_sync.csv` file can be
parsed on its own as a Mega-sync-only session; trial summaries that are not in
the Mega stream will be unavailable, and outcomes are inferred from lick side
versus correct side.

Parse one flat session folder in place:

```bash
behaviormatch /path/to/session --on-existing overwrite
```

Windows example:

```bat
python -m behaviormatch "C:\Users\Public\Documents\Data\BV" --on-existing overwrite
```

Parse by selecting a `_mega_sync.csv` file:

```bash
behaviormatch /path/to/Freelymoving_1363_tr1_0504_185130_091_mega_sync.csv --on-existing overwrite
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
behaviormatch /path/to/session --emit-csv
```

BehaviorMatch writes `<base>.mat` by default. Use `--no-emit-mat` when you only
want the canonical HDF5 output.

Windows example with an explicit output folder:

```bat
python -m behaviormatch "C:\Users\Public\Documents\Data\BV" --output-dir "C:\Users\Public\Documents\Data\BV" --on-existing overwrite
```

`--emit-csv` writes:

- `<base>_trials.csv`
- `<base>_events.csv`
- `<base>_sensor_events.csv`
- `<base>_summary.json`

## MATLAB Import

BehaviorMatch writes `.mat` files by default. Add the BehaviorMatch folder to
MATLAB's path and load the exported `.mat` file with the root-level
`load_session.m` helper:

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

`load_session.m` loads the `.mat` export, not the canonical `.h5` file. If
MATLAB reports an error like `Unknown text on line number 1 ... "HDF"`, it is
trying to use MATLAB `load()` on an HDF5 file. Re-run BehaviorMatch without
`--no-emit-mat`, then call `load_session` on the `.mat` file:

```matlab
addpath('C:\Users\<username>\Documents\GitHub\BehaviorMatch')

session = load_session('C:\Users\Public\Documents\Data\BV\Freelymoving_1363_tr1_0504_185130_091.mat');
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

## Troubleshooting

If Windows prints `'behaviormatch' is not recognized as an internal or external
command`, either the package has not been installed into the active Python
environment or the launcher is not on `PATH`. Activate the intended Conda
environment, run `python -m pip install -e .` from the repository root, then use
`python -m behaviormatch ...`.

If Python prints `No module named behaviormatch`, check that you are in the
environment where BehaviorMatch was installed and that `python -m pip install
-e .` was run from the folder containing `pyproject.toml`. This project uses a
`src/` package layout, so running from the repository folder alone is not enough
until the package is installed.

If a copied command fails unexpectedly, retype option names such as
`--output-dir` with normal hyphens. Some chat/email clients replace `--` with a
long dash that command-line parsers do not recognize.

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
