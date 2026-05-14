# MouseMaze Session Storage Spec

**Status:** Draft
**Date:** 2026-05-07
**Authors:** Connor Beck

This spec defines the on-disk and in-MATLAB shape of a parsed MouseMaze session.
It is the output contract for BehaviorMatch.

---

## 1. Goals and non-goals

**Goals:**
- One uniform per-session artifact that carries the full session — **regardless of which streams were recorded** (Mega-only, Mega + Blackfly, Mega + Blackfly + mini2P, or future combinations).
- Single `load(<basename>.mat)` in MATLAB returns a **single struct** the user can navigate without `isfield` plumbing for the typical case (gated by top-level booleans).
- Per-trial fields are first-class: `session.trials(N).cue1`, `session.trials(N).sensor_events`, `session.trials(N).mini2p_frames`.
- Variable-length per-trial fields appear as MATLAB `table` objects (after `load_session.m`) so they render as side-by-side spreadsheets in the workspace browser.
- Computational workflows (Python / vectorized MATLAB) are equally well-served — categorical/numeric columns, no nested cell arrays.
- **Timing on legacy files is corrected at parse time**, not stored corrected at recording time. Re-parsing yields better timestamps as the correction pipeline improves.

**Non-goals:**
- NWB / DANDI export (deferred; HDF5 + `.mat` covers stated needs).
- Cross-session aggregation or per-mouse rollups (separate tooling).
- Modifying any raw recording file (`_console.csv`, `_*_frames.csv`, `_mega_sync.csv`, `.mkv`) — those are archival.
- Hand-annotation of parsed output (any analysis tags would go to a future sibling `<base>_annotations.h5`, out of scope).

---

## 2. Domain definitions

| Term     | Definition                                                                                                    | Example                                   |
| -------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Session  | One mouse, one continuous recording. Bounded by recording start → recording stop.                            | `Freelymoving_1363_tr1_0504_185130_091`   |
| Trial    | One cue → choice → outcome → return cycle. Boundaries are firmware-specific.                                 | `WM_TRIAL_START` … `WM_TRIAL_SUMMARY`     |
| Synthetic trial | Trial synthesized from `WM1` → `Return *` sensor cycles when no firmware trial markers exist (Stage 0). | habituation cycle                         |
| Event    | A timestamped row from any source — Mega serial line, GUI message, sensor crossing, command/ACK.              | `MEGA_EVT,12345678,SENSOR,WM1`            |
| Sensor event | An IR sensor crossing — first-class subset of events, exposed as its own per-trial table.                 | `Time: 17958 ms, Sensor: WM1`             |
| Stream   | A recorded data source: `mega` (always present), `blackfly` (overhead camera), `mini2p` (calcium imaging).    | `has_blackfly == true`                    |
| Frame    | One sample from a TTL-driven imaging stream. 1-based row index in its sidecar CSV is the canonical frame number. | hardware_frame_number = 12345          |

---

## 3. File layout per session

### 3.1 Raw inputs (read-only, archival)

Per session, all files share a basename `<base>` and live in one directory:

```
<base>/
├── <base>_console.csv              # primary log: pc_ts, time_str, message  (always present in v0.3.0+)
├── <base>.csv                      # legacy main log (pre-v0.2.7 only)
├── <base>_hardware_frames.csv      # Blackfly TTL edges            (only if has_blackfly)
├── <base>_mini2P_frames.csv        # mini2P TTL edges              (only if has_mini2p)
├── <base>_mega_sync.csv            # Mega↔UNO clock-pair rows      (only if has_mega_sync)
├── <base>_ffv1_frames.csv          # encoder frame index → pc_ts   (only if has_blackfly)
├── <base>_ffv1.mkv                 # video                         (only if has_blackfly)
└── ...DLC pickles, suite2p, etc... # downstream artifacts (out of scope of this spec)
```

The parser **reads only**. Raw files are never modified. The `.mkv` is referenced by path in `/session/.attrs/mkv_path` but not opened.

### 3.2 Derived outputs (rebuildable from raw)

```
<base>/
├── <base>.h5                       # consolidated HDF5            (canonical on-disk form)
└── <base>.mat                      # optional MATLAB export       (written via scipy.io.savemat)
```

Both are **derived**: regenerable by re-running the parser. A `parser_version` and `corrections_applied` attribute on `/session/` lets analysis code detect stale outputs.

### 3.3 Package artifacts

```
src/behaviormatch/
├── cli.py
├── discovery.py
├── pipeline.py
├── h5_writer.py
├── mat_writer.py
├── reader.py
└── extractors/
```

---

## 4. Variant matrix

The session schema is **sparse**: fields exist only when their stream was recorded. Top-level boolean flags on the session struct gate access — analysis scripts check the bool before drilling.

| Recording mode             | `has_hardware_frames` | `has_blackfly` | `has_mini2p` | `has_mega_sync` |
| -------------------------- | :-------------------: | :------------: | :----------: | :-------------: |
| Mega-only (no camera, no SI)|         no            |       no       |     no       |       yes¹      |
| Mega + Blackfly             |         yes           |      yes       |     no       |       yes       |
| Mega + Blackfly + mini2P    |         yes           |      yes       |     yes      |       yes       |

¹ `_mega_sync.csv` is written whenever the UNO is running, which is whenever any TTL stream is recorded. Mega-only sessions skip the UNO entirely → `has_mega_sync = false`.

**Rule:** within a single session, every trial has the same field shape. Across sessions, the shape varies by recording mode. A boolean is the only thing analysis code needs to check.

---

## 5. HDF5 layout (`<base>.h5`)

```
<base>.h5
├── /session/.attrs
│       mouse_id                 (str)
│       task                     (str)
│       firmware                 (str: "WM_behavior" | "CodeV4_5" | "CodeV4_4")
│       firmware_version         (str)
│       parser_version           (str: semver, e.g. "0.2.0")
│       corrections_applied      (str array: e.g. ["uno_pc_drift_lin", "ttl_debounce_1ms"])
│       session_t0_unix          (float64) — pc_ts of first row of _console.csv
│       session_iso              (str)
│       n_trials                 (int)
│       n_standard_trials        (int)
│       n_correct                (int)
│       has_hardware_frames      (bool)
│       has_blackfly             (bool) — alias for "has FFV1+hardware_frames pair"
│       has_mini2p               (bool)
│       has_mega_sync            (bool)
│       mkv_path                 (str, only if has_blackfly)
│       parse_status             (str: "clean" | "partial")
│       parse_errors             (variable-length str array)
│
├── /session/events                       (full session event log; see §6.3)
│
├── /session/timing/                      (one group; subdatasets only when stream present)
│   ├── hardware_frames                   (table; only if has_hardware_frames)
│   ├── behavior_frames_mkv               (table; only if has_blackfly)
│   ├── mini2p_frames                     (table; only if has_mini2p)
│   ├── mega_sync                         (table; only if has_mega_sync)
│   └── clock_corrections.attrs           (parameters of the fits, see §9)
│
└── /trials/
    ├── 0001/.attrs                       (all scalar trial fields; see §6.2)
    ├── 0001/sensor_events                (table; always present, may be zero-length)
    ├── 0001/events                       (raw audit-log subset for [t_start_s, t_end_s_next))
    ├── 0001/mkv_frames                   (table; only if has_blackfly)
    ├── 0001/mini2p_frames                (table; only if has_mini2p)
    ├── 0002/...
    └── ...
```

**Notes:**
- All variable-length string columns use `h5py.string_dtype(encoding="utf-8")`.
- All datasets use `gzip` level 4 compression.
- **No `iti_events`** — superseded. The per-trial `events` table covers `[t_start_s, t_start_s_next)` (or `[t_start_s, session_end]` for the last trial). User can slice on `t_session_s > t_end_s` to get post-summary tail.
- **No `pre_session_events` / `post_session_events`** — superseded. `/session/events` carries the full session log; pre-trial-1 and post-final-trial slices are recoverable by `t_session_s < trials[0].t_start_s` and `t_session_s > trials[end].t_end_s` respectively.
- **No `/trials_table`** — superseded. The MATLAB ergonomics that motivated it are now handled by `load_session.m` walking `/trials/<NNNN>/.attrs` and assembling a struct array.

---

## 6. Schema details

### 6.1 Session attrs

See §5 for the full list. Every attr is single-valued per session.

### 6.2 Per-trial scalar fields (stored as `/trials/NNNN/.attrs`)

| Field                  | Type     | Units         | Source                                                  | Notes                                                              |
| ---------------------- | -------- | ------------- | ------------------------------------------------------- | ------------------------------------------------------------------ |
| `trial_index`          | int64    | —             | `WM_TRIAL_START.trial_index` / `TRIAL_START_INDEX`      | 1-based.                                                           |
| `standard_index`       | int64    | —             | `WM_TRIAL_START.standard_index`                         | nullable; absent for non-WM_behavior firmwares.                    |
| `trial_type`           | str      | —             | union of firmware fields                                | enum: `standard`,`correction`,`replay`,`random_cue`,`synthetic`.   |
| `level`                | int64    | —             | `WM_TRIAL_START.level`                                  | nullable.                                                          |
| `delay_ms`             | int64    | ms            | `WM_TRIAL_START.delay_ms`                               | nullable.                                                          |
| `cue1`                 | str      | —             | `WM_TRIAL_START.cue1` / `Cue1: <hz>`                    | normalized to `"high"` / `"low"` / Hz string.                      |
| `cue2`                 | str      | —             | `WM_TRIAL_START.cue2` / `Cue2: <hz>`                    | same.                                                              |
| `correct_side`         | str      | —             | `WM_TRIAL_START.correct_side` / `Correct turn:`         | `left`, `right`, `either`, or `NA`.                                |
| `bias_left_count`      | int64    | —             | `WM_TRIAL_START.bias_left_count`                        | nullable.                                                          |
| `p_right_correct`      | float64  | —             | `WM_TRIAL_START.p_right_correct`                        | nullable.                                                          |
| `p_correction`         | float64  | —             | `WM_TRIAL_START.p_correction`                           | nullable.                                                          |
| `chosen_side`          | str      | —             | `WM_TRIAL_SUMMARY.chosen_side` / inferred from sensors  | `left`, `right`, or `NA`.                                          |
| `outcome`              | str      | —             | `WM_TRIAL_SUMMARY.outcome` / inferred                   | enum: `correct`,`incorrect`,`no_response`,`aborted`,`backward`,`NA`. |
| `latency_ms`           | int64    | ms            | `WM_TRIAL_SUMMARY.latency_ms`                           | nullable.                                                          |
| `replay_played`        | uint8    | bool          | `WM_TRIAL_SUMMARY.replay_played`                        | 0/1; nullable.                                                     |
| `consecutive_misses`   | int64    | —             | `WM_TRIAL_SUMMARY.consecutive_misses`                   | nullable.                                                          |
| `punishment_delivered` | uint8    | bool          | `PUNISH_DELIVERED` event in window                      | 0/1.                                                               |
| `reward_delivered`     | uint8    | bool          | `REWARD_DELIVERED` event in window                      | 0/1.                                                               |
| `t_start_s`            | float64  | s (corrected) | trial-start event `t_session_s`                         | post-correction (see §9). Every other `t_*_s` is also corrected.   |
| `t_end_s`              | float64  | s (corrected) | trial-end event `t_session_s`                           |                                                                    |
| `t_start_mega_us`      | int64    | µs (Mega)     | trial-start `MEGA_EVT.us`                               | raw, uncorrected.                                                  |
| `t_end_mega_us`        | int64    | µs (Mega)     | trial-end `MEGA_EVT.us`                                 |                                                                    |
| `cue1_us`, `cue2_us`, `gate_open_us`, `wm2_us`, `lick_us`, `decision_us`, `return_us` | int64 | µs (Mega) | per-event `MEGA_EVT.us` | nullable. |

### 6.3 Events table (full session and per-trial subsets)

`/session/events` and `/trials/NNNN/events` share this schema. Per-trial is a strict subset by `t_session_s` window.

| Column        | Type    | Units         | Notes                                                                   |
| ------------- | ------- | ------------- | ----------------------------------------------------------------------- |
| `t_session_s` | float64 | s (corrected) | Seconds since `session_t0_unix`. **Drift-corrected** (see §9).          |
| `pc_ts`       | float64 | s (Unix)      | Original PC timestamp, uncorrected.                                     |
| `kind`        | str     | —             | Coarse classification; see permitted values below.                      |
| `mega_us`     | int64   | µs (Mega)     | `-1` sentinel when not a `MEGA_EVT` line.                               |
| `tag`         | str     | —             | E.g., `SENSOR`, `WM_PHASE`, `CMD`, `WM_SEQ`, `TONE_PLAY_HZ`.            |
| `value`       | str     | —             | E.g., `WM1`, `13000`, `incorrect`.                                      |
| `raw_text`    | str     | —             | Original line, preserved verbatim.                                      |
| `source`      | str     | —             | `arduino` \| `host` \| `gui`.                                           |

**Permitted `kind` values:** `MEGA_EVT`, `SENSOR_TXT`, `TRIAL_START`, `TRIAL_SUMMARY`, `TRIAL_RESTART`, `CHOICE`, `PUNISH`, `REWARD`, `ACK`, `META`, `END`, `RETURN`, `GUI_SYSTEM`, `GUI_WM`, `GUI_TIMING`, `GUI_LOCK`, `GUI_DLC`, `GUI_OTHER`, `UNKNOWN`.

### 6.4 Sensor events table (per-trial; always present)

`/trials/NNNN/sensor_events` — derived from the events table, filtered to IR sensor crossings only. Always written, even if empty (zero-length OK; per §4 the field is always present within a session).

| Column        | Type    | Units         | Notes                                                                       |
| ------------- | ------- | ------------- | --------------------------------------------------------------------------- |
| `t_session_s` | float64 | s (corrected) | Drift-corrected.                                                            |
| `t_trial_s`   | float64 | s (corrected) | `t_session_s − t_start_s`. Zero-aligned to trial start; convenient for plots. |
| `sensor`      | str     | —             | Canonical name. Becomes `categorical` after `load_session.m`.               |
| `mega_us`     | int64   | µs (Mega)     | Authoritative Mega timestamp; `-1` if sourced from `Time: <ms>` legacy line. |

**Sensor name normalization:** the parser maps the union of all firmware sensor strings to a canonical set. Initial canonical set (extend as needed): `WM1`, `WM2`, `Wait_sensor`, `Decision_Left`, `Decision_Right`, `Return_Left`, `Return_Right`, `Lick_Left`, `Lick_Right`, `Reward_Left`, `Reward_Right`. Any unmapped raw name is stored verbatim with a one-line warning to `parse_errors`.

### 6.5 Frame tables

#### 6.5.1 `hardware_frames` (Blackfly TTL, session-level)

| Column                | Type    | Units                                  | Notes                                              |
| --------------------- | ------- | -------------------------------------- | -------------------------------------------------- |
| `frame_number`        | int64   | —                                      | 1-based row index in source CSV.                   |
| `t_session_s`         | float64 | s (corrected, **UNO→PC** drift-fitted) | See §9 for the fit.                                |
| `pc_ts`               | float64 | s (Unix, raw)                          | Original.                                          |
| `uno_edge_us`         | int64   | µs (UNO)                               | UNO's `micros()` at the TTL edge.                  |
| `dropped_reported`    | uint8   | bool                                   | UNO firmware reported a dropped edge.              |
| `debounced`           | uint8   | bool                                   | **NEW** — `1` if the row is a spurious double-edge filtered out by the parser; the row is retained for audit but flagged. |

#### 6.5.2 `behavior_frames_mkv` (Blackfly encoder side)

| Column                  | Type    | Units                | Notes                                                        |
| ----------------------- | ------- | -------------------- | ------------------------------------------------------------ |
| `mkv_frame_i`           | int64   | —                    | 0-based index — what you index into the MKV with.            |
| `t_session_s`           | float64 | s (corrected)        | Encoder-side corrected time.                                 |
| `pc_ts`                 | float64 | s (Unix, raw)        | Original encoder timestamp.                                  |
| `rel_ms`                | float64 | ms                   | Reported by encoder.                                         |
| `hardware_frame_number` | int64   | —                    | Nearest-`pc_ts` join into `hardware_frames`. `-1` if no pair. |
| `is_orphan`             | uint8   | bool                 | **NEW** — `1` if encoder frame has no hardware match within ±2× nominal interval (startup-window mismatch flag). |

#### 6.5.3 `mini2p_frames` (per-plane TTL)

Same schema as `hardware_frames`, minus `debounced` (mini2P TTL doesn't bounce in observed data; will add if found). The TTL fires **once per imaging plane**, so the rate measured from the inter-edge intervals is the *plane* rate, not the volume rate.

Reported in `clock_corrections.attrs`:
- `mini2p_per_plane_hz` — measured from the median TTL interval (e.g., 19.68 Hz for 3-plane × 6.55 Hz volume).
- `mini2p_planes_per_volume` — defaults to `0` (unknown). Supply externally from ScanImage config; volume rate is then `per_plane_hz / planes_per_volume`.

We do not auto-detect `planes_per_volume` from the TTL stream because a steady single-plane stream is mathematically indistinguishable from a multi-plane stream that lacks an inter-volume gap.

#### 6.5.4 `mega_sync` (clock anchors)

| Column             | Type    | Units                | Notes                                                              |
| ------------------ | ------- | -------------------- | ------------------------------------------------------------------ |
| `uno_edge_us`      | int64   | µs (UNO)             |                                                                    |
| `mega_evt_us`      | int64   | µs (Mega)            |                                                                    |
| `mega_tag`         | str     | —                    | `CMD`, `SENSOR`, etc. — the tag of the paired event.               |
| `mega_value`       | str     | —                    |                                                                    |
| `t_session_s`      | float64 | s (corrected)        | Computed from `uno_pc_time_sec` after UNO→PC fit.                  |
| `pc_skew_s`        | float64 | s                    | `mega_evt_pc_time_sec − uno_pc_time_sec` (USB read-thread jitter). |
| `dropped_reported` | uint8   | bool                 |                                                                    |

#### 6.5.5 Per-trial frame slices (`/trials/NNNN/{mkv_frames,mini2p_frames}`)

Each is a pre-sliced view of the corresponding session-level table, scoped to `[t_start_s, t_end_s]`. Schema is the same minus `pc_ts` (since `t_session_s` is already corrected) and minus `is_orphan` / `debounced` flags (those rows are excluded from per-trial slices by default — only retained at session-level for audit).

---

## 7. MATLAB layout (`<base>.mat` after `load_session.m`)

After `session = load_session('Freelymoving_…mat')`, the workspace shows:

```
session                              1×1   struct
session.mouse_id                     '1363'                          (char or string scalar)
session.task                         'tr1'
session.firmware                     'WM_behavior'
session.parser_version               '0.2.0'
session.has_hardware_frames          true
session.has_blackfly                 true
session.has_mini2p                   true
session.has_mega_sync                true
session.session_t0_unix              1.7779e+09
session.session_iso                  '2026-05-04T18:51:30Z'

session.trials                       1×147  struct                   ← struct array, scroll to inspect
session.trials(47).trial_index       47
session.trials(47).cue1              <categorical>  high
session.trials(47).chosen_side       <categorical>  left
session.trials(47).outcome           <categorical>  incorrect
session.trials(47).t_start_s         3812.94
session.trials(47).t_end_s           3826.61
session.trials(47).cue1_us           int64
session.trials(47).sensor_events     8×4    table                    ← double-click → tabular view
session.trials(47).events            53×8   table
session.trials(47).mkv_frames        742×5  table                    (only if has_blackfly)
session.trials(47).mini2p_frames     72×4   table                    (only if has_mini2p)

session.events                       198432×8  table                 ← full session log
session.timing                       1×1    struct
session.timing.hardware_frames       281201×6 table
session.timing.behavior_frames_mkv   281305×6 table
session.timing.mini2p_frames         83282×5 table
session.timing.mega_sync             2920×7  table
session.timing.clock_corrections     1×1    struct                   ← fit parameters; see §9
```

**Categorical conversions** applied by `load_session.m`:
- `cue1`, `cue2`, `correct_side`, `chosen_side`, `outcome`, `trial_type`, `firmware`, `kind`, `tag`, `source` (in events tables), `sensor` (in sensor_events), `mega_tag` (in mega_sync).

**Datetime conversion (opt-in flag):** `load_session(file, 'datetime', true)` adds a `pc_datetime` column to every table where `pc_ts` exists, computed as `datetime(pc_ts, 'ConvertFrom', 'posixtime')`.

`load_session.m` is ~50 lines. Recursion: walk the loaded struct, for each leaf that is a struct of equal-length column vectors, call `struct2table(leaf)`. Then apply categorical conversion to the named columns. Pure read-side; never modifies the file.

---

## 8. Time conventions

A MouseMaze session has **four** clocks. The spec picks one as canonical for analysis and keeps the others as audit columns.

| Clock        | Source                       | Drift                    | Used as                         |
| ------------ | ---------------------------- | ------------------------ | ------------------------------- |
| Mega `micros()` | Arduino Mega (16 MHz xtal) | ±100 ppm spec; ~1200 ppm observed UNO-side | raw `mega_us` / `t_*_us` audit |
| UNO `micros()`  | Arduino UNO (16 MHz xtal)  | ~1200 ppm vs PC observed | raw `uno_edge_us` audit         |
| PC clock     | OS, NTP-disciplined          | ≪10 ppm typically        | raw `pc_ts` audit               |
| **Corrected session time** `t_session_s` | Derived | 0 by definition | **Canonical analysis axis**     |

**Canonical:** `t_session_s` (float64 seconds, zero at `session_t0_unix`). Every event, frame, and trial-boundary timestamp is reported in this axis, post-correction. The original `pc_ts` and `mega_us` / `uno_edge_us` are kept as raw audit columns.

`session_t0_unix` is the `pc_ts` of the first row of `_console.csv` (the `[System] Console log → ...` line). Wall-clock can be reconstructed as `pc_ts = session_t0_unix + t_session_s` (post-correction the relationship is exact for events on the PC clock; UNO/Mega-clock rows are converted via the fits in §9).

---

## 9. Timing correction pipeline (legacy data)

The parser computes corrections **at parse time**, applies them to `t_session_s` in all output tables, and records the fit parameters at `/session/timing/clock_corrections.attrs`. Re-parsing with an improved pipeline replaces the corrections automatically.

### 9.1 Anchors available

| Anchor                                    | Source                                            | Use                                       |
| ----------------------------------------- | ------------------------------------------------- | ----------------------------------------- |
| `(uno_edge_us, pc_time_sec)` pairs        | every row of `_hardware_frames.csv` (and mini2P)  | UNO clock ↔ PC clock fit                  |
| `(mega_evt_us, uno_edge_us)` pairs        | `_mega_sync.csv`                                  | Mega clock ↔ UNO clock fit                |
| `(ffv1.frame_i, ffv1.pc_ts)`              | `_ffv1_frames.csv`                                | Encoder PC clock (independent)            |
| `_console.csv` first row `pc_ts`          | the `[System] Console log → ...` line             | session_t0_unix anchor                    |

### 9.2 Corrections applied (initial pipeline, version 0.2.0)

In order:

1. **TTL debounce on `hardware_frames`.** Edges with `Δuno_edge_us < 1000 µs` (1 ms) from the previous edge are flagged `debounced=1` and excluded from per-trial slices. They are kept in the session-level table for audit. Empirically: 32 such double-edges in a 281k-frame session — 0.011%, all ~8–12 µs spacing.
   - **Tag in `corrections_applied`:** `"ttl_debounce_1ms"`.
2. **UNO `micros()` ↔ PC time linear fit.** Least-squares `pc_ts ≈ a · uno_edge_us + b` over all hardware_frame rows (excluding debounced). Yields a per-session UNO→PC slope (typically ~1.001 — the 1200 ppm drift observed in the test session). The fit residual stdev is reported as `uno_pc_residual_ms`.
   - For all `uno_edge_us` columns in `mini2p_frames`, `mega_sync`, etc., compute their PC equivalent via the fit; subtract `session_t0_unix` to produce `t_session_s`.
   - **Tag:** `"uno_pc_drift_lin"`.
3. **Mega `micros()` ↔ UNO `micros()` linear fit.** Least-squares over `_mega_sync.csv` rows. Yields a Mega→UNO slope. Combined with the UNO→PC fit, gives Mega→PC.
   - For events with only `mega_us` (no PC timestamp), recover `t_session_s` via Mega→UNO→PC.
   - **Tag:** `"mega_uno_lin"`.
4. **FFV1 ↔ hardware_frames startup-window reconciliation.** The encoder may have started before the UNO began TTL logging (or vice versa). Procedure: count rows in `_ffv1_frames.csv` and `_hardware_frames.csv`; if `n_ffv1 > n_hardware`, the first `n_ffv1 − n_hardware` encoder frames are flagged `is_orphan=1` and `hardware_frame_number=-1`. The opposite case (rare; UNO ran longer than encoder) is symmetric. **No frame counts are silently merged.**
   - In the example session: `n_ffv1 = 281305`, `n_hardware = 281233`. 72 leading encoder frames are flagged orphan; the remainder match 1:1 within ±0.5 frame intervals.
   - **Tag:** `"ffv1_startup_reconcile"`.
5. **Drift-residual sanity check.** After (2), report:
    - `mini2p_per_plane_hz` (median TTL interval; e.g. 19.68 Hz for 3-plane × 6.55 Hz volume).
    - `blackfly_fps` (computed from corrected hardware_frames intervals; expected 50–100 Hz).
    - If either deviates from a sane band, write a warning to `parse_errors`.

> **Note on `uno_pc_residual_ms`.** The UNO buffers ~4 TTL edges per USB packet, so multiple `uno_edge_us` values share the same `pc_ts`. This packet quantization shows up as ~10–20 ms of *residual stdev* even when the underlying clock fit is excellent. The slope is unaffected — with ~10⁵ anchors it converges to <1 ppm. So a 19 ms residual on a 71-min session is **not** a fit failure; it reflects the raw `pc_ts` granularity. The §10.2 startup handshake and §10.3 heartbeat sync don't fix this either — only finer PC-side timestamping would. Treat `uno_pc_residual_ms` as a quantization-noise indicator, not as the per-event timing accuracy.

### 9.3 What the fit parameters look like on disk

`/session/timing/clock_corrections.attrs` (HDF5 attrs):

```
uno_pc_slope               (float64)        UNO_us → PC_s     (≈ 1e-6 × something close to 1)
uno_pc_intercept           (float64)        seconds at uno_us = 0
uno_pc_residual_ms         (float64)        stdev of fit residuals; dominated by 4-edge USB packet quantization on legacy data
n_uno_pc_anchors           (int64)
mega_uno_slope             (float64)        Mega_us → UNO_us  (~1.0 ± a few ppm; high residual on legacy data due to sparse pairing)
mega_uno_intercept         (float64)
mega_uno_residual_us       (float64)
n_mega_uno_anchors         (int64)
n_ttl_debounced            (int64)
n_ffv1_orphan              (int64)
blackfly_fps               (float64)        post-correction estimate (median-interval based)
mini2p_per_plane_hz        (float64)        per-plane TTL rate (volume rate = / planes_per_volume)
mini2p_planes_per_volume   (int64)          0 = unknown; supply externally from ScanImage config
```

### 9.4 What this buys you for legacy files

- A `pc_ts`-tagged event and a `mega_us`-tagged event hundreds of seconds apart will now sit on the same `t_session_s` axis to within ~1 ms (residual stdev), instead of accumulating the ~5 s drift seen in the 71-min test session.
- Per-trial frame slices use corrected times, so cross-stream alignment ("show me the calcium frame nearest the cue1 onset for trial 47") is accurate without any per-script clock arithmetic.
- The 32 spurious blackfly double-edges no longer show up as 0.008-ms-interval frames in trial slices.
- 72 startup-orphan FFV1 frames are flagged, not silently joined to the wrong hardware frame.

The parser version moves to **0.2.0** when this pipeline ships. Re-parsing legacy `.h5` files with v0.2.0 produces corrected outputs without touching raw data.

---

## 10. Recording-time fixes (future experiments)

These are firmware / GUI changes that prevent the upstream causes of the corrections in §9. Each is **independent**; ship in any order.

### 10.1 UNO-side TTL debounce (eliminates §9.2(1))

**File:** [arduino/BlackflyTiming/BlackflyTiming.ino](arduino/BlackflyTiming/) (or the UNO firmware controlling TTL capture).

Add a guard interval in the edge ISR: ignore an edge whose `micros()` is within `MIN_EDGE_INTERVAL_US` (recommend 1000 µs = 1 ms — well below blackfly's 15.156 ms nominal) of the previous edge on the same channel. Write to the CSV only after the guard passes.

Effect: spurious double-edges never reach the disk → parser §9.2(1) becomes a no-op (still correct on legacy files).

### 10.2 Encoder ↔ TTL startup handshake (eliminates §9.2(4))

**Files:** [MouseMaze.py](MouseMaze.py) (FFV1 encoder thread), [arduino/BlackflyTiming/](arduino/BlackflyTiming/).

At session start:
1. GUI sends `BEGIN_TTL_CAPTURE` to UNO; UNO ACKs and starts logging.
2. GUI waits for ACK before opening the FFV1 encoder.
3. Optionally: the very first hardware-frame row is tagged with a `start_marker=1` flag, written by the UNO upon receipt of `BEGIN_TTL_CAPTURE`.

Effect: `n_ffv1 == n_hardware` exactly (modulo any in-flight frames at session end, which are bounded by one encoder queue depth).

### 10.3 Periodic Mega↔UNO sync pulse cadence (improves §9.2(3) fit)

**File:** [arduino/WM_behavior/WM_behavior.ino](arduino/WM_behavior/) and [arduino/CodeV4_5/CodeV4_5.ino](arduino/CodeV4_5/).

Today, Mega→UNO sync edges occur opportunistically (one per `MEGA_EVT` line). For long quiet stretches (e.g., a stage-0 habituation with no events for minutes), the regression has gaps. Add a **heartbeat sync edge** at fixed cadence (recommend 1 Hz — ~4000 anchors per 71-min session, vs the ~3000 currently observed):

```cpp
// somewhere in loop()
if (millis() - lastSyncHeartbeatMs >= 1000) {
  lastSyncHeartbeatMs = millis();
  pulseSyncEdge();         // existing helper that drops the UNO sync line high+low
  logMegaEvent("HEARTBEAT", "");   // pairs the edge in _mega_sync.csv
}
```

Effect: tighter `mega_uno_residual_us` (likely sub-100 µs) and no quiet-period gaps. Heartbeat events also let post-hoc analysis confirm the Mega never reset.

### 10.4 Session-start / session-end markers on every stream

**File:** [MouseMaze.py](MouseMaze.py).

GUI emits a single `SESSION_BEGIN` line to `_console.csv` and a Mega-side command that produces a `MEGA_EVT,...,SESSION_BEGIN,1`. UNO mirrors with a `_mega_sync.csv` row. At session end, same with `SESSION_END`.

Effect: explicit zero-and-end anchors on every stream. Removes the current ambiguity that `session_t0_unix` is "the first row of _console.csv" (which is a system-log line, not a hardware event).

### 10.5 (Optional, larger work) UNO clock TCXO upgrade

The 1200 ppm drift observed is at the edge of UNO's nominal ±100 ppm crystal spec. Some boards drift more; some drift less. A TCXO (~$10) drops drift to <2 ppm and removes most of the residual after §9.2(2). Out of scope for this spec — flagged as a future hardware option.

### 10.6 Migration order recommendation

1. §10.1 (debounce) — pure firmware, single file, immediate quality win.
2. §10.4 (begin/end markers) — pure host change, ~10 LOC.
3. §10.3 (heartbeat) — pure firmware, ~5 LOC per .ino.
4. §10.2 (handshake) — host + firmware coordination; touches encoder thread.
5. §10.5 (TCXO) — only if §10.3's tighter fit still leaves residuals you care about.

Steps 1–4 are zero risk to existing data: the parser's correction pipeline (§9) is already designed to be a no-op on already-clean recordings.

---

## 11. MATLAB load wrapper (`load_session.m`) contract

BehaviorMatch can emit `.mat` files via `--emit-mat`. A MATLAB convenience
loader can be added by downstream projects if table/categorical conversion is
needed.

**Signature:**

```matlab
function session = load_session(matfile, varargin)
% LOAD_SESSION  Load a MouseMaze .mat session and convert variable-length
%               fields to MATLAB tables, with categorical conversion for
%               low-cardinality string columns.
%
% Inputs:
%   matfile       — path to <base>.mat
%   'datetime'    — true|false (default false). Add pc_datetime columns to tables.
%   'minimal'     — true|false (default false). Drop /session/events and
%                   per-trial /events audit logs from output to save memory.
%
% Output:
%   session — struct laid out per STORAGE_SPEC.md §7.
%
% Raises:
%   error if `parser_version` < required minimum (settable in this function).
```

**Behavior contract:**
1. Calls `load(matfile)` to retrieve the raw struct.
2. Asserts `parser_version` ≥ `MIN_PARSER_VERSION` (a constant inside the function); errors loudly if stale.
3. Walks the struct recursively. For any leaf that is a struct whose fields are equal-length column vectors / cell arrays of equal length, converts via `struct2table`.
4. For each known categorical column (per the list in §7), applies `categorical(...)`.
5. If `'datetime'` is set, adds `pc_datetime` to every table that has `pc_ts`.
6. If `'minimal'` is set, removes `session.events` and `session.trials(*).events` after the table conversion.

**Non-behavior:**
- Never modifies the .mat file.
- Never prompts the user.
- Never silently drops columns (only `'minimal'` is allowed to drop the audit log).

**Test expectation:** downstream MATLAB loaders should load a fixture session
and assert the resulting struct shape against this schema.

---

## 12. Read / write contracts

**Recording-time writers** (MouseMaze GUI; out of this parser's control, but constraints listed for completeness):
- `_console.csv` is append-only and `flush()`'d after each line. Always present in v0.3.0+.
- `_hardware_frames.csv`, `_mini2P_frames.csv`, `_mega_sync.csv`, `_ffv1_frames.csv` are append-only; mid-session crashes leave a parseable prefix.
- Files are NOT modified after session end. The parser depends on this.

**Parser** (`src/behaviormatch/`):
- Reads raw inputs only. Never writes back to the session directory's raw files.
- Output `<base>.h5` and `<base>.mat` are deterministic given inputs and `parser_version`.
- Records `parser_version`, `corrections_applied`, fit parameters in `/session/.attrs` and `/session/timing/clock_corrections.attrs`.
- Crash safety: writes to `<base>.h5.tmp` and `<base>.mat.tmp`, then atomically renames on success. Partial files never appear.
- On parse error: best-effort. Partial sessions get `parse_status="partial"` and `parse_errors` populated. **A clean trial is never lost because a later trial was malformed.**

**Analysis** (Python or MATLAB):
- Reads `<base>.h5` or `<base>.mat`. Never writes.
- Validates `parser_version` if a specific correction version is required.
- Hand annotation (if ever added) goes to a sibling `<base>_annotations.h5` — out of scope.

---

---

## 14. Open questions

1. **Sensor name canonicalization** — the canonical set in §6.4 is a first guess. Real legacy data may emit names not yet in the map (e.g., MouseSleep firmware variants). First parse pass should log unmapped names; we extend the canonical set from there.
2. **Multi-Z mini2P plane indexing** — currently we report only the per-plane TTL. If users want per-volume timestamps and per-plane offsets in the trial frames table, we need a `plane_index` column derived from the per-plane vs. inter-volume gap (the 5 ms vs 50 ms split visible in the test data). Defer until first analysis script needs it.
3. **DLC pose data** — out of scope of THIS spec, but the load_session.m wrapper could optionally attach the rule-filtered DLC `.h5` to `session.dlc_pose` if a sibling `*_rulefiltered.h5` exists. Defer pending user demand.
4. **Cross-session index** — no session catalog or per-mouse rollup is in this spec. If users want `find_sessions(mouse_id, date_range)`, that's a separate sidecar (probably a single SQLite at the data-root level) and a separate spec.

---

## 15. Deferred decisions

- **NWB / DANDI export.** Not in scope. The HDF5 layout is close enough to NWB's per-acquisition / per-trial structure that a future NWB writer would map fields rather than re-extract from raw. Re-evaluate if a publication or DANDI deposit is on the roadmap.
- **Real-time / live parsing during recording.** The parser is post-hoc only. Live parsing would require a streaming variant — separate concern.
- **Multi-process parallel batching** of sessions. Sequential parse is fast enough for current data volumes. Add only if measured.
- **Hand-annotation mechanism.** Out of scope; `<base>_annotations.h5` sibling pattern is the future direction.
- **TCXO hardware upgrade for UNO.** §10.5 — quality bump, not currently bottleneck.
