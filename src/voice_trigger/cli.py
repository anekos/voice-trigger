"""Command-line interface for voice-trigger."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence

from voice_trigger.audio import AudioCapture
from voice_trigger.detector import OnsetDetector, peak_level
from voice_trigger.sources import list_sources

MONITOR_DISPLAY_INTERVAL = 0.1  # seconds; throttles monitor's output to a readable rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-trigger",
        description=(
            "Listen to a microphone via parec and act on short loud sounds. "
            "Typical workflow: use `sources` to find a --source name, "
            "`monitor` to watch levels and tune --threshold by eye, "
            "then `run` with that threshold to trigger a command."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = subparsers.add_parser(
        "run",
        description=(
            "Watch the microphone and run COMMAND when a loud sound is detected. "
            "In one-shot mode (the default) it exits 0 as soon as the sound "
            "triggers, or non-zero if --timeout elapses first. With --loop it "
            "runs forever, triggering COMMAND on every detected sound and "
            "ignoring --timeout."
        ),
        help="run COMMAND when a loud sound is detected",
    )
    run_parser.add_argument(
        "-s",
        "--source",
        default=None,
        help="recording source name (see `voice-trigger sources`); "
        "default is the system default source",
    )
    run_parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.3,
        help="peak level (0-1) that counts as a trigger; use `voice-trigger "
        "monitor` to find a good value for your mic and environment "
        "(default: 0.3)",
    )
    run_parser.add_argument(
        "-c",
        "--cooldown",
        type=float,
        default=0.5,
        help="minimum seconds between triggers, to avoid re-triggering on "
        "the same sound (default: 0.5)",
    )
    timeout_group = run_parser.add_mutually_exclusive_group()
    timeout_group.add_argument(
        "-T",
        "--timeout",
        type=float,
        default=None,
        help="in one-shot mode, give up and exit non-zero after this many "
        "seconds with no trigger; ignored with --loop (default: wait "
        "forever)",
    )
    timeout_group.add_argument(
        "-l",
        "--loop",
        action="store_true",
        help="run forever, triggering COMMAND on every detected sound "
        "instead of exiting after the first one; disables --timeout",
    )
    run_parser.add_argument(
        "command",
        nargs="*",
        help="optional command and arguments to run on trigger, e.g. "
        "`voice-trigger run --threshold 0.5 -- notify-send hi`; run "
        "directly (no shell), and everything after -- is passed through "
        "as-is",
    )

    monitor_parser = subparsers.add_parser(
        "monitor",
        description=(
            "Print the microphone's peak level for each audio chunk, "
            "marking chunks that would trigger at the given --threshold. "
            "Use this to pick a --threshold value before running "
            "`voice-trigger run`."
        ),
        help="print live mic levels to help tune --threshold",
    )
    monitor_parser.add_argument(
        "-s",
        "--source",
        default=None,
        help="recording source name (see `voice-trigger sources`); "
        "default is the system default source",
    )
    monitor_parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.3,
        help="peak level (0-1) to mark as TRIGGER in the printed output (default: 0.3)",
    )

    subparsers.add_parser(
        "sources",
        description="List available PulseAudio/PipeWire recording source names.",
        help="list available recording source names",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "run":
            return _run(args)
        if args.subcommand == "monitor":
            return _monitor(args)
        if args.subcommand == "sources":
            return _sources()
        raise AssertionError(f"unknown subcommand: {args.subcommand}")
    except FileNotFoundError as error:
        print(f"error: {error.filename} not found", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1


def _run(args: argparse.Namespace) -> int:
    detector = OnsetDetector(threshold=args.threshold, cooldown=args.cooldown)
    deadline = None if args.timeout is None else time.monotonic() + args.timeout
    with AudioCapture(args.source) as capture:
        for chunk in capture.chunks():
            now = time.monotonic()
            if detector.process(chunk, now):
                if args.command:
                    subprocess.Popen(args.command)
                if not args.loop:
                    return 0
            elif deadline is not None and now >= deadline:
                return 1
    return 1


def _monitor(args: argparse.Namespace) -> int:
    peak = 0.0
    last_print: float | None = None
    with AudioCapture(args.source) as capture:
        for chunk in capture.chunks():
            peak = max(peak, peak_level(chunk))
            now = time.monotonic()
            if last_print is not None and now - last_print < MONITOR_DISPLAY_INTERVAL:
                continue
            triggered = peak >= args.threshold
            marker = "TRIGGER" if triggered else ""
            line = f"level={peak:.3f} threshold={args.threshold:.3f} {marker:<7}"
            print(line, end="\n" if triggered else "\r", flush=True)
            peak = 0.0
            last_print = now
    return 0


def _sources() -> int:
    for name in list_sources():
        print(name)
    return 0
