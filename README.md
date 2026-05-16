# BehaviorMatch

BehaviorMatch is a headless CLI for turning MouseMaze behavior logs into one
uniform per-session output. It accepts any normal CSV from a MouseMaze recording
session, including `<base>.csv`, `<base>_console.csv`, and
`<base>_mega_sync.csv`, then attaches matching timing sidecars when present,
detects the firmware family, and writes canonical outputs for downstream
analysis.

Supported input layouts:

- Explicit files selected one by one.
- A flat folder where all session files live together.
- A folder with files split across subfolders, such as `console/`,
  `mega_sync/`, `mini2p_frames/`, `hardware_frames/`, and `ffv1_frames/`.
- A single selected session CSV. The selected file can be the base log, console
  log, Mega sync log, or one of the supported frame sidecars.

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

You can also select one recording-output CSV directly. BehaviorMatch strips the
known suffix, uses the shared basename to find the rest of the session, and then
chooses the best primary source in this order:

- `<base>_console.csv`
- `<base>.csv`
- `<base>_mega_sync.csv`, as a Mega-sync-only fallback

These direct file selections are all valid:

```text
<base>.csv
<base>_console.csv
<base>_mega_sync.csv
<base>_hardware_frames.csv
<base>_mini2P_frames.csv
<base>_mini2p_frames.csv
<base>_ffv1_frames.csv
```

If no console or base log is available, a `_mega_sync.csv` file can be parsed on
its own as a Mega-sync-only session. Trial summaries that are not in the Mega
stream will be unavailable, and outcomes are inferred from lick side versus
correct side.

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

From this repository root, the included test-style command looks like:

```bash
python -m behaviormatch "TestData/Freelymoving_073720_tr3_0516_154840_475_mega_sync.csv" --output-dir "TestData" --on-existing overwrite
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

BehaviorMatch writes both `<base>.h5` and `<base>.mat` by default. Use
`--no-emit-mat` only when you want to skip MATLAB output. Use `--emit-csv` when
you also want CSV/JSON exports.

Windows example with an explicit output folder:

```bat
python -m behaviormatch "C:\Users\Public\Documents\Data\BV" --output-dir "C:\Users\Public\Documents\Data\BV" --on-existing overwrite
```

On macOS or Linux, use macOS/Linux paths instead of Windows `C:\...` paths:

```bash
python -m behaviormatch "/Users/connorbeck/Documents/Data/BV" --output-dir "/Users/connorbeck/Documents/Data/BV" --on-existing overwrite
```

`--emit-csv` writes:

- `<base>_trials.csv`
- `<base>_events.csv`
- `<base>_sensor_events.csv`
- `<base>_summary.json`

## Timing Safeguards

BehaviorMatch keeps timing tables conservative when the recording hardware
produces partial or mismatched files.

Mini2P frame matching uses the Mini2P frame sidecar as its source of truth:
`<base>_mini2P_frames.csv` or `<base>_mini2p_frames.csv`. The exported Mini2P
frame numbers are the rows from that file, not frame counts inferred from
console text. If ScanImage starts briefly, logs a few pulses, and is then
stopped and restarted, BehaviorMatch preserves only the frame rows that are
actually present in the selected Mini2P sidecar and slices them into trials by
their corrected timestamps.

Blackfly FFV1 frame matching is reconciled against `<base>_hardware_frames.csv`.
If the encoder and hardware TTL streams have different leading frame counts,
extra startup frames are marked as orphaned instead of shifting the rest of the
session onto the wrong hardware frame numbers.

Mega event timing is corrected through the Mega-to-UNO and UNO-to-PC fits when
there are at least two valid sync anchors. If the wire carrying the timing pulse
between the Blackfly UNO and the Arduino Mega was disconnected, the fit cannot
be trusted and BehaviorMatch falls back to the PC-side timestamps that were
logged with the events. The output still writes, but downstream analyses should
inspect `/session/timing/clock_corrections.attrs`, especially
`n_mega_uno_anchors`, `n_uno_pc_anchors`, and residual fields, before treating
Mega-event-to-camera alignment as hardware-synchronized.

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
