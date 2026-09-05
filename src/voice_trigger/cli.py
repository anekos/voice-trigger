"""Command-line interface for voice-trigger."""

from __future__ import annotations

import functools
import subprocess
import sys
import time
from collections.abc import Callable

import click

from voice_trigger.audio import SAMPLE_RATE, AudioCapture
from voice_trigger.config import load_config
from voice_trigger.detector import OnsetDetector, peak_level
from voice_trigger.models import LANGUAGE_MODELS, ensure_model
from voice_trigger.recognizer import CommandRecognizer
from voice_trigger.sources import get_default_source, list_sources

MONITOR_DISPLAY_INTERVAL = 0.1  # seconds; throttles monitor's output to a readable rate

_source_option = click.option(
    "-s",
    "--source",
    default=None,
    help="Recording source name (see `voice-trigger sources`); "
    "default is the system default source.",
)


def _cli_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as error:
            raise click.ClickException(f"{error.filename} not found") from error
        except (click.exceptions.Exit, click.exceptions.Abort):
            # both subclass RuntimeError; let click's own flow control through
            raise
        except RuntimeError as error:
            raise click.ClickException(str(error)) from error

    return wrapper


@click.group()
def cli() -> None:
    """Listen to a microphone via parec and act on sounds or spoken keywords.

    Typical workflow: use `sources` to find a --source name, `monitor` to
    watch levels and tune --threshold by eye, then `run` with that threshold
    to trigger a command — or `listen` to trigger commands by voice keywords.
    """


@cli.command()
@_source_option
@click.option(
    "-t",
    "--threshold",
    type=float,
    default=0.3,
    show_default=True,
    help="Peak level (0-1) that counts as a trigger; use `voice-trigger "
    "monitor` to find a good value for your mic and environment.",
)
@click.option(
    "-c",
    "--cooldown",
    type=float,
    default=0.5,
    show_default=True,
    help="Minimum seconds between triggers, to avoid re-triggering on the same sound.",
)
@click.option(
    "-T",
    "--timeout",
    type=float,
    default=None,
    help="In one-shot mode, give up and exit non-zero after this many "
    "seconds with no trigger (default: wait forever); incompatible "
    "with --loop.",
)
@click.option(
    "-l",
    "--loop",
    is_flag=True,
    help="Run forever, triggering COMMAND on every detected sound instead "
    "of exiting after the first one; incompatible with --timeout.",
)
@click.argument("command", nargs=-1)
@click.pass_context
@_cli_errors
def run(
    ctx: click.Context,
    source: str | None,
    threshold: float,
    cooldown: float,
    timeout: float | None,
    loop: bool,
    command: tuple[str, ...],
) -> None:
    """Run COMMAND when a loud sound is detected.

    In one-shot mode (the default) exit 0 as soon as the sound triggers, or
    non-zero if --timeout elapses first; without COMMAND this works as a
    pure detection gate. COMMAND is run directly (no shell), and everything
    after -- is passed through as-is.
    """
    if loop and timeout is not None:
        raise click.UsageError("--loop and --timeout are mutually exclusive")
    detector = OnsetDetector(threshold=threshold, cooldown=cooldown)
    deadline = None if timeout is None else time.monotonic() + timeout
    with AudioCapture(source) as capture:
        _print_selected_source(source)
        for chunk in capture.chunks():
            now = time.monotonic()
            if detector.process(chunk, now):
                if command:
                    subprocess.Popen(list(command))
                if not loop:
                    return
            elif deadline is not None and now >= deadline:
                ctx.exit(1)
    ctx.exit(1)


@cli.command()
@_source_option
@click.option(
    "-t",
    "--threshold",
    type=float,
    default=0.3,
    show_default=True,
    help="Peak level (0-1) to mark as TRIGGER in the printed output.",
)
@_cli_errors
def monitor(source: str | None, threshold: float) -> None:
    """Print live mic levels to help tune --threshold.

    Prints the microphone's peak level for each audio chunk, marking chunks
    that would trigger at the given --threshold. Use this to pick a
    --threshold value before running `voice-trigger run`.
    """
    peak = 0.0
    last_print: float | None = None
    with AudioCapture(source) as capture:
        _print_selected_source(source)
        for chunk in capture.chunks():
            peak = max(peak, peak_level(chunk))
            now = time.monotonic()
            if last_print is not None and now - last_print < MONITOR_DISPLAY_INTERVAL:
                continue
            triggered = peak >= threshold
            marker = "TRIGGER" if triggered else ""
            line = f"level={peak:.3f} threshold={threshold:.3f} {marker:<7}"
            print(line, end="\n" if triggered else "\r", flush=True)
            peak = 0.0
            last_print = now


@cli.command()
@_source_option
@click.option(
    "--language",
    default=None,
    type=click.Choice(tuple(LANGUAGE_MODELS)),
    help="Recognition language; picks which Vosk model to use. Overrides "
    "`language` from CONFIG_FILE.",
)
@click.argument(
    "config_file",
    metavar="CONFIG_FILE",
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Recognize and log as usual but never run any command; use this "
    "to tune the keywords in CONFIG_FILE.",
)
@click.pass_context
@_cli_errors
def listen(
    ctx: click.Context,
    source: str | None,
    language: str | None,
    config_file: str,
    dry_run: bool,
) -> None:
    """Run commands mapped to recognized voice keywords.

    CONFIG_FILE is a YAML (or JSON) object holding `commands` — an array of
    {"keywords": [...], "command": [...]} entries; each entry's command (an
    argv array) runs when any of its keywords is recognized — and optional
    `language` and `source` settings, which the corresponding command-line
    options override. The Vosk model for the language is downloaded
    automatically on first use.
    """
    config = load_config(config_file)
    language = language or config.language
    if language is None:
        raise click.UsageError(
            "no language given: pass --language or set `language` in CONFIG_FILE"
        )
    source = source or config.source
    commands = config.keyword_commands()
    model_path = ensure_model(language)
    command_recognizer = CommandRecognizer.create(
        model_path, list(commands), SAMPLE_RATE
    )
    with AudioCapture(source) as capture:
        _print_selected_source(source)
        for chunk in capture.chunks():
            result = command_recognizer.process(chunk)
            if result is None:
                continue
            print(f"heard: {result.text!r} -> {result.phrase or '(no match)'}")
            if not dry_run and result.phrase is not None:
                subprocess.Popen(commands[result.phrase])
    ctx.exit(1)


@cli.command()
@_cli_errors
def sources() -> None:
    """List available PulseAudio/PipeWire recording source names."""
    for name in list_sources():
        print(name)


def _print_selected_source(source: str | None) -> None:
    print(f"source: {source or get_default_source()}", file=sys.stderr)
