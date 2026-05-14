from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Iterable, Sequence

from .schema import SessionFileGroup


SIDECAR_SUFFIXES = {
    "_console": "console_log",
    "_hardware_frames": "hardware_frames",
    "_mini2P_frames": "mini2p_frames",
    "_mini2p_frames": "mini2p_frames",
    "_mega_sync": "mega_sync",
    "_ffv1_frames": "ffv1_frames",
}

SESSION_BASENAME_RE = re.compile(
    r"^Freelymoving_.+?_(?:tr\d|[A-Za-z][A-Za-z0-9_]*)_\d{4}_\d{6}_\d+$",
    re.IGNORECASE,
)


def strip_known_suffix(path: Path) -> tuple[str, str]:
    stem = path.stem
    for suffix, kind in SIDECAR_SUFFIXES.items():
        if stem.endswith(suffix):
            return stem[: -len(suffix)], kind
    return stem, "behavior_log"


def _csv_candidates(input_path: Path, recursive: bool) -> Iterable[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() == ".csv":
            yield input_path
        return

    pattern = "**/*.csv" if recursive else "*.csv"
    yield from sorted(input_path.glob(pattern))


def _build_groups(csv_paths: Iterable[Path], wanted_base: str | None = None) -> list[SessionFileGroup]:
    buckets: dict[str, dict[str, Path]] = defaultdict(dict)
    primary_dirs: dict[str, Path] = {}

    for csv_path in sorted(csv_paths):
        base_name, kind = strip_known_suffix(csv_path)
        if kind == "behavior_log" and not SESSION_BASENAME_RE.match(base_name):
            continue
        if wanted_base is not None and base_name != wanted_base:
            continue
        buckets[base_name][kind] = csv_path
        if kind in {"console_log", "behavior_log"}:
            primary_dirs[base_name] = csv_path.parent

    groups: list[SessionFileGroup] = []
    for base_name, files in sorted(buckets.items()):
        primary = files.get("console_log") or files.get("behavior_log")
        if primary is None:
            continue
        groups.append(
            SessionFileGroup(
                base_name=base_name,
                directory=primary_dirs.get(base_name, primary.parent),
                primary_log=primary,
                console_log=files.get("console_log"),
                behavior_log=files.get("behavior_log"),
                hardware_frames=files.get("hardware_frames"),
                mini2p_frames=files.get("mini2p_frames"),
                mega_sync=files.get("mega_sync"),
                ffv1_frames=files.get("ffv1_frames"),
            )
        )

    groups.sort(key=lambda group: (group.base_name, str(group.primary_log)))
    return groups


def walk(input_path: str | Path, recursive: bool = False) -> list[SessionFileGroup]:
    """Group MouseMaze CSVs under one path into sessions.

    The parser prefers `<base>_console.csv`, falls back to `<base>.csv`, and
    attaches any matching timing sidecars. With ``recursive=True``, sidecars may
    live in kind-separated subfolders under the input root.
    """
    root = Path(input_path).expanduser()
    if not root.exists():
        raise FileNotFoundError(root)

    wanted_base: str | None = None
    if root.is_file():
        wanted_base, _ = strip_known_suffix(root)

    return _build_groups(_csv_candidates(root, recursive), wanted_base=wanted_base)


def walk_many(input_paths: Sequence[str | Path], recursive: bool = False) -> list[SessionFileGroup]:
    """Group sessions from explicit files and/or directories.

    This is the CLI path for mixed inputs such as a console file plus sidecars
    selected individually, a flat session folder, or a root whose files are
    split across subfolders like ``console/``, ``mega_sync/``, and
    ``mini2p_frames/``.
    """
    if not input_paths:
        return []

    csv_paths: list[Path] = []
    for raw_path in input_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)
        csv_paths.extend(_csv_candidates(path, recursive))

    return _build_groups(csv_paths)
