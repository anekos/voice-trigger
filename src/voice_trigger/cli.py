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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voice-trigger")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--source", default=None)
    run_parser.add_argument("--threshold", type=float, default=0.3)
    run_parser.add_argument("--cooldown", type=float, default=0.5)
    timeout_group = run_parser.add_mutually_exclusive_group()
    timeout_group.add_argument("--timeout", type=float, default=None)
    timeout_group.add_argument("--loop", action="store_true")
    run_parser.add_argument("command", nargs="*")

    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--source", default=None)
    monitor_parser.add_argument("--threshold", type=float, default=0.3)

    subparsers.add_parser("sources")

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
    with AudioCapture(args.source) as capture:
        for chunk in capture.chunks():
            level = peak_level(chunk)
            marker = "TRIGGER" if level >= args.threshold else ""
            print(f"level={level:.3f} threshold={args.threshold:.3f} {marker}")
    return 0


def _sources() -> int:
    for name in list_sources():
        print(name)
    return 0
