from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import discovery
from .csv_writer import write_csv_bundle
from .detection import identify
from .h5_writer import write_h5
from .mat_writer import write_mat
from .schema import Session, SessionFileGroup
from .timing import attach_timing


LogFn = Callable[[str], None]


@dataclass
class ParseResult:
    group: SessionFileGroup
    h5_path: Path | None
    mat_path: Path | None
    csv_paths: tuple[Path, ...]
    session: Session | None
    status: str
    message: str = ""


def output_path_for(group: SessionFileGroup, output_dir: str | Path | None, suffix: str) -> Path:
    directory = Path(output_dir).expanduser() if output_dir else group.directory
    return directory / f"{group.base_name}{suffix}"


def output_dir_for(group: SessionFileGroup, output_dir: str | Path | None) -> Path:
    return Path(output_dir).expanduser() if output_dir else group.directory


def resolve_existing(path: Path, policy: str) -> Path | None:
    if not path.exists():
        return path
    if policy == "skip":
        return None
    if policy == "overwrite":
        return path
    if policy != "versioned":
        raise ValueError(f"Unknown existing-output policy: {policy}")

    stem = path.stem
    suffix = path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_v{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find versioned output path for {path}")


def parse_group(
    group: SessionFileGroup,
    output_dir: str | Path | None = None,
    emit_mat: bool = False,
    emit_csv: bool = False,
    on_existing: str = "skip",
    dry_run: bool = False,
    log: LogFn | None = None,
) -> ParseResult:
    log = log or (lambda _: None)
    firmware, version, extractor_class = identify(group)

    h5_target = output_path_for(group, output_dir, ".h5")
    h5_path = resolve_existing(h5_target, on_existing)
    if h5_path is None:
        message = f"skip existing {h5_target}"
        log(message)
        return ParseResult(group, None, None, (), None, "skipped", message)

    mat_path: Path | None = None
    if emit_mat:
        mat_target = output_path_for(group, output_dir, ".mat")
        mat_path = resolve_existing(mat_target, on_existing)
        if mat_path is None and on_existing == "skip":
            mat_path = None

    if dry_run:
        message = f"{group.base_name}: {firmware} {version} -> {h5_path}"
        log(message)
        return ParseResult(group, h5_path, mat_path, (), None, "dry-run", message)

    log(f"{group.base_name}: parsing as {firmware} {version}")
    extractor = extractor_class(group, firmware, version)
    session = extractor.parse()
    attach_timing(session, group)
    write_h5(session, h5_path)
    csv_paths: tuple[Path, ...] = ()
    if emit_csv:
        csv_paths = write_csv_bundle(session, output_dir_for(group, output_dir), stem=h5_path.stem)
    if emit_mat and mat_path is not None:
        write_mat(session, mat_path)

    message = f"wrote {h5_path}"
    if mat_path is not None:
        message += f" and {mat_path}"
    if csv_paths:
        message += f" and {len(csv_paths)} CSV/JSON exports"
    log(message)
    return ParseResult(group, h5_path, mat_path, csv_paths, session, session.parse_status, message)


def run(
    input_path: str | Path | Sequence[str | Path],
    output_dir: str | Path | None = None,
    emit_mat: bool = False,
    emit_csv: bool = False,
    on_existing: str = "skip",
    recursive: bool = False,
    dry_run: bool = False,
    log: LogFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[ParseResult]:
    log = log or (lambda _: None)
    should_cancel = should_cancel or (lambda: False)
    if isinstance(input_path, (str, Path)):
        groups = discovery.walk(input_path, recursive=recursive)
    else:
        groups = discovery.walk_many(input_path, recursive=recursive)
    log(f"discovered {len(groups)} session(s)")

    results: list[ParseResult] = []
    for group in groups:
        if should_cancel():
            log("cancelled before next session")
            break
        try:
            results.append(
                parse_group(
                    group,
                    output_dir=output_dir,
                    emit_mat=emit_mat,
                    emit_csv=emit_csv,
                    on_existing=on_existing,
                    dry_run=dry_run,
                    log=log,
                )
            )
        except Exception as exc:
            message = f"{group.base_name}: failed: {exc}"
            log(message)
            results.append(ParseResult(group, None, None, (), None, "failed", message))
    return results


def dry_run_lines(groups: Iterable[SessionFileGroup]) -> list[str]:
    lines: list[str] = []
    for group in groups:
        firmware, version, _ = identify(group)
        sidecars = ", ".join(group.sidecars) if group.sidecars else "no sidecars"
        lines.append(f"{group.base_name}: {firmware} {version}; {sidecars}; primary={group.primary_log}")
    return lines
