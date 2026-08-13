# voice-trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that listens to a PulseAudio/PipeWire microphone source, detects short loud sounds (e.g. a tongue click) via amplitude-based onset detection, and runs an arbitrary command when triggered.

**Architecture:** Three independent, pure-logic-first modules (`detector.py`, `audio.py`, `sources.py`) wired together by `cli.py`, with `main.py` as a thin process entry point that handles signals and the process exit code. `parec`/`pactl` are invoked as subprocesses; there are no Python audio/runtime dependencies.

**Tech Stack:** Python 3.13, stdlib only (`argparse`, `subprocess`, `array`, `signal`, `time`), pytest for tests.

**Spec:** `docs/superpowers/specs/2026-08-14-voice-trigger-design.md`

## Global Constraints

- No new runtime dependencies. `pyproject.toml`'s `dependencies = []` stays empty; only the stdlib is used.
- Commands are always executed via `subprocess.Popen(argv_list)`, never `shell=True`.
- Audio capture uses `parec` exclusively (PulseAudio-compatible, works under both PulseAudio and PipeWire's pulse layer).
- Source listing uses `pactl list short sources`.
- PCM format is fixed: 16000 Hz, mono, s16le, ~20ms chunks (640 bytes / 320 samples per chunk).
- `--threshold` default `0.3`, `--cooldown` default `0.5` (seconds).
- `run` defaults to one-shot exit (0 on trigger, non-zero on `--timeout` expiry). `--loop` makes it run forever, and is mutually exclusive with `--timeout`.
- All new source files go under `src/voice_trigger/`; tests go under `tests/`, mirroring module names.

---

### Task 1: Onset detector

**Files:**
- Create: `src/voice_trigger/detector.py`
- Test: `tests/test_detector.py`

**Interfaces:**
- Produces: `peak_level(chunk: bytes) -> float` — normalized (0.0-1.0) peak absolute amplitude of a 16-bit PCM chunk.
- Produces: `class OnsetDetector: def __init__(self, threshold: float, cooldown: float) -> None` and `def process(self, chunk: bytes, now: float) -> bool` — returns `True` exactly once per rising edge above `threshold`, suppressed for `cooldown` seconds after the last trigger.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_detector.py`:

```python
from array import array

from voice_trigger.detector import OnsetDetector, peak_level


def _chunk(amplitude: int, num_samples: int = 4) -> bytes:
    return array("h", [amplitude] * num_samples).tobytes()


def test_peak_level_of_silence_is_zero():
    assert peak_level(_chunk(0)) == 0.0


def test_peak_level_of_empty_chunk_is_zero():
    assert peak_level(b"") == 0.0


def test_peak_level_of_full_scale_is_near_one():
    assert peak_level(_chunk(32767)) > 0.999


def test_peak_level_ignores_sign():
    assert peak_level(_chunk(-32767)) > 0.999


def test_process_stays_false_below_threshold():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(1000), now=0.0) is False


def test_process_triggers_on_rising_edge():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(1000), now=0.0) is False
    assert detector.process(_chunk(30000), now=0.1) is True


def test_process_does_not_retrigger_while_sustained_above_threshold():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(30000), now=0.1) is False


def test_process_blocks_retrigger_within_cooldown():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(1000), now=0.2) is False
    assert detector.process(_chunk(30000), now=0.3) is False


def test_process_retriggers_after_cooldown_elapses():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(1000), now=0.2) is False
    assert detector.process(_chunk(30000), now=1.1) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice_trigger.detector'`

- [ ] **Step 3: Implement `detector.py`**

Create `src/voice_trigger/detector.py`:

```python
"""Amplitude-based onset detection for short trigger sounds."""

from __future__ import annotations

from array import array


def peak_level(chunk: bytes) -> float:
    samples = array("h")
    samples.frombytes(chunk)
    if not samples:
        return 0.0
    return max(abs(sample) for sample in samples) / 32768


class OnsetDetector:
    def __init__(self, threshold: float, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._above = False
        self._last_trigger: float | None = None

    def process(self, chunk: bytes, now: float) -> bool:
        level = peak_level(chunk)
        was_above = self._above
        self._above = level >= self.threshold
        if not self._above or was_above:
            return False
        if self._last_trigger is not None and now - self._last_trigger < self.cooldown:
            return False
        self._last_trigger = now
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_detector.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Type-check and lint**

Run: `uv run mypy src/voice_trigger/detector.py && uv run ruff check src/voice_trigger/detector.py tests/test_detector.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/voice_trigger/detector.py tests/test_detector.py
git commit -m "feat: add amplitude-based onset detector"
```

---

### Task 2: Audio capture

**Files:**
- Create: `src/voice_trigger/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `build_parec_command(source: str | None) -> list[str]`.
- Produces: `class AudioCapture: def __init__(self, source: str | None) -> None`, usable as `with AudioCapture(source) as capture:` then `for chunk in capture.chunks(): ...` — yields `bytes` chunks of exactly `CHUNK_SIZE` bytes; raises `RuntimeError` if the underlying `parec` process exits with an unexpected non-zero code; terminates the subprocess on `__exit__`.
- Produces: `CHUNK_SIZE: int` (module-level constant, 640).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio.py`:

```python
import io

from voice_trigger.audio import CHUNK_SIZE, _read_exact, build_parec_command


def test_chunk_size_is_20ms_at_16khz_mono_16bit():
    assert CHUNK_SIZE == 640


def test_build_parec_command_without_source():
    assert build_parec_command(None) == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
    ]


def test_build_parec_command_with_source():
    command = build_parec_command("alsa_input.example")
    assert command == [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
        "--device=alsa_input.example",
    ]


def test_read_exact_returns_full_size_from_stream():
    stream = io.BytesIO(b"x" * 100)
    assert _read_exact(stream, 50) == b"x" * 50


def test_read_exact_returns_short_read_on_eof():
    stream = io.BytesIO(b"x" * 10)
    assert _read_exact(stream, 50) == b"x" * 10


class _PartialReader:
    def __init__(self, pieces: list[bytes]) -> None:
        self._pieces = pieces

    def read(self, size: int) -> bytes:
        if not self._pieces:
            return b""
        return self._pieces.pop(0)


def test_read_exact_assembles_multiple_partial_reads():
    stream = _PartialReader([b"ab", b"cd", b"ef"])
    assert _read_exact(stream, 6) == b"abcdef"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice_trigger.audio'`

- [ ] **Step 3: Implement `audio.py`**

Create `src/voice_trigger/audio.py`:

```python
"""Subprocess-based PCM capture via `parec`."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from types import TracebackType
from typing import IO

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_FORMAT = "s16le"
BYTES_PER_SAMPLE = 2
CHUNK_DURATION_MS = 20
CHUNK_SIZE = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE * CHUNK_DURATION_MS // 1000


def build_parec_command(source: str | None) -> list[str]:
    command = [
        "parec",
        "--raw",
        f"--format={SAMPLE_FORMAT}",
        f"--rate={SAMPLE_RATE}",
        f"--channels={CHANNELS}",
    ]
    if source is not None:
        command.append(f"--device={source}")
    return command


def _read_exact(stream: IO[bytes], size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        piece = stream.read(size - len(buf))
        if not piece:
            break
        buf.extend(piece)
    return bytes(buf)


class AudioCapture:
    def __init__(self, source: str | None) -> None:
        self._source = source
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> AudioCapture:
        self._process = subprocess.Popen(
            build_parec_command(self._source),
            stdout=subprocess.PIPE,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process.wait()

    def chunks(self) -> Iterator[bytes]:
        assert self._process is not None
        assert self._process.stdout is not None
        stream = self._process.stdout
        while True:
            chunk = _read_exact(stream, CHUNK_SIZE)
            if len(chunk) < CHUNK_SIZE:
                break
            yield chunk
        self._process.wait()
        if self._process.returncode not in (0, None, -15):
            raise RuntimeError(
                f"parec exited unexpectedly with code {self._process.returncode}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audio.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Type-check and lint**

Run: `uv run mypy src/voice_trigger/audio.py && uv run ruff check src/voice_trigger/audio.py tests/test_audio.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/voice_trigger/audio.py tests/test_audio.py
git commit -m "feat: add parec-based audio capture"
```

---

### Task 3: Source listing

**Files:**
- Create: `src/voice_trigger/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `parse_source_names(output: str) -> list[str]`.
- Produces: `list_sources() -> list[str]` — runs `pactl list short sources` and returns parsed names.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sources.py`:

```python
from voice_trigger.sources import parse_source_names

SAMPLE_OUTPUT = (
    "0\talsa_input.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tRUNNING\n"
    "1\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tIDLE\n"
)


def test_parse_source_names_extracts_second_column():
    assert parse_source_names(SAMPLE_OUTPUT) == [
        "alsa_input.pci-0000_00_1f.3.analog-stereo",
        "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
    ]


def test_parse_source_names_skips_blank_lines():
    assert parse_source_names("\n" + SAMPLE_OUTPUT + "\n") == [
        "alsa_input.pci-0000_00_1f.3.analog-stereo",
        "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
    ]


def test_parse_source_names_empty_output():
    assert parse_source_names("") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice_trigger.sources'`

- [ ] **Step 3: Implement `sources.py`**

Create `src/voice_trigger/sources.py`:

```python
"""Enumerate available PulseAudio/PipeWire recording sources."""

from __future__ import annotations

import subprocess


def parse_source_names(output: str) -> list[str]:
    names = []
    for line in output.splitlines():
        if not line.strip():
            continue
        columns = line.split("\t")
        names.append(columns[1])
    return names


def list_sources() -> list[str]:
    result = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        check=True,
        text=True,
    )
    return parse_source_names(result.stdout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Type-check and lint**

Run: `uv run mypy src/voice_trigger/sources.py && uv run ruff check src/voice_trigger/sources.py tests/test_sources.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/voice_trigger/sources.py tests/test_sources.py
git commit -m "feat: add pactl-based source listing"
```

---

### Task 4: CLI wiring (`run` / `monitor` / `sources` subcommands)

**Files:**
- Create: `src/voice_trigger/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `voice_trigger.detector.OnsetDetector`, `voice_trigger.detector.peak_level` (Task 1); `voice_trigger.audio.AudioCapture` (Task 2); `voice_trigger.sources.list_sources` (Task 3).
- Produces: `build_parser() -> argparse.ArgumentParser`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` — parses argv, dispatches to a subcommand handler, returns a process exit code. Catches `FileNotFoundError`, `RuntimeError`, and `KeyboardInterrupt` from handlers and turns them into exit code `1` plus a message on stderr.
- Produces (used directly by tests, and by `main.py` in Task 5): `_run`, `_monitor`, `_sources` handler functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
from __future__ import annotations

from array import array
from collections.abc import Iterator

import pytest

from voice_trigger import cli


def _chunk(amplitude: int, num_samples: int = 4) -> bytes:
    return array("h", [amplitude] * num_samples).tobytes()


def _loud_chunk() -> bytes:
    return _chunk(20000)  # 20000 / 32768 ~= 0.61, above the default 0.3 threshold


def _quiet_chunk() -> bytes:
    return _chunk(0)


class _FakeAudioCapture:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __call__(self, source: str | None) -> "_FakeAudioCapture":
        return self

    def __enter__(self) -> "_FakeAudioCapture":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def chunks(self) -> Iterator[bytes]:
        yield from self._chunks


def _fake_clock(values: list[float]):
    it = iter(values)
    return lambda: next(it)


def test_run_and_timeout_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--loop", "--timeout", "5"])


def test_parses_command_after_dashdash():
    args = cli.build_parser().parse_args(["run", "--threshold", "0.4", "--", "echo", "hi"])
    assert args.threshold == 0.4
    assert args.command == ["echo", "hi"]


def test_run_one_shot_triggers_command_and_exits_zero(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    args = cli.build_parser().parse_args(["run", "--", "echo", "hi"])
    assert cli._run(args) == 0
    assert popen_calls == [["echo", "hi"]]


def test_run_one_shot_without_command_exits_zero_on_trigger(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    args = cli.build_parser().parse_args(["run"])
    assert cli._run(args) == 0
    assert popen_calls == []


def test_run_timeout_without_detection_exits_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()] * 3))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.1, 0.2, 10.0]))
    args = cli.build_parser().parse_args(["run", "--timeout", "5"])
    assert cli._run(args) == 1


def test_run_loop_keeps_triggering_command(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_loud_chunk(), _quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.0, 1.0, 2.0]))
    args = cli.build_parser().parse_args(["run", "--loop", "--", "echo", "hi"])
    assert cli._run(args) == 1  # generator exhausted, no explicit stop requested
    assert popen_calls == [["echo", "hi"], ["echo", "hi"]]


def test_monitor_prints_level_for_each_chunk(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()]))
    args = cli.build_parser().parse_args(["monitor"])
    assert cli._monitor(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "TRIGGER" not in lines[0]
    assert "TRIGGER" in lines[1]


def test_sources_prints_each_name(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_sources", lambda: ["a", "b"])
    assert cli._sources() == 0
    assert capsys.readouterr().out == "a\nb\n"


def test_main_reports_missing_parec(monkeypatch, capsys):
    def _raise(source: str | None) -> None:
        raise FileNotFoundError(2, "No such file or directory", "parec")

    monkeypatch.setattr(cli, "AudioCapture", _raise)
    assert cli.main(["run"]) == 1
    assert "parec" in capsys.readouterr().err


def test_main_handles_keyboard_interrupt(monkeypatch):
    def _raise(source: str | None) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "AudioCapture", _raise)
    assert cli.main(["run"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'voice_trigger.cli'`

- [ ] **Step 3: Implement `cli.py`**

Create `src/voice_trigger/cli.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Type-check and lint**

Run: `uv run mypy src/voice_trigger/cli.py && uv run ruff check src/voice_trigger/cli.py tests/test_cli.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/voice_trigger/cli.py tests/test_cli.py
git commit -m "feat: add run/monitor/sources CLI subcommands"
```

---

### Task 5: Process entry point (signal handling)

**Files:**
- Modify: `src/voice_trigger/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `voice_trigger.cli.main` (Task 4), imported as `cli_main` so tests can monkeypatch it by name.
- Produces: `main() -> None` — the `voice-trigger` console-script entry point (referenced by `pyproject.toml`'s `[project.scripts]`, unchanged). Registers a `SIGTERM` handler that raises `KeyboardInterrupt` (so `cli.main`'s existing `KeyboardInterrupt` handling and `AudioCapture.__exit__` cleanup run on `SIGTERM` too, matching `SIGINT`'s default behavior), then calls `sys.exit(cli_main())`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
from __future__ import annotations

import signal

import pytest

from voice_trigger.main import main


def test_main_exits_with_cli_return_code(monkeypatch):
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: 3)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 3


def test_main_registers_sigterm_handler_that_raises_keyboard_interrupt(monkeypatch):
    original_handler = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr("voice_trigger.main.cli_main", lambda: 0)
    try:
        with pytest.raises(SystemExit):
            main()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, original_handler)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `test_main_exits_with_cli_return_code` fails because `main()` still prints `"voice-trigger: Hello, World!"` and returns `None` instead of calling `sys.exit`.

- [ ] **Step 3: Implement `main.py`**

Replace the contents of `src/voice_trigger/main.py`:

```python
"""Entry point for the voice-trigger CLI."""

from __future__ import annotations

import signal
import sys

from voice_trigger.cli import main as cli_main


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full test suite, type-check, and lint**

Run: `uv run pytest -v && uv run mypy . && uv run ruff check .`
Expected: all tests pass, no mypy or ruff errors

- [ ] **Step 6: Update README usage section**

Replace the contents of `README.md`:

```markdown
# voice-trigger

PipeWire/PulseAudio 環境で、短い音(舌打ちなど)をトリガーに任意のコマンドを実行する CLI。

## 使い方

利用可能な入力ソースを確認する:

```sh
voice-trigger sources
```

閾値を調整する(実際に音を出しながらレベルを確認する):

```sh
voice-trigger monitor --source SOURCE_NAME
```

1回検知したらコマンドを実行して終了する:

```sh
voice-trigger run --source SOURCE_NAME --threshold 0.3 -- notify-send "triggered"
```

検知するたびにコマンドを実行し続ける:

```sh
voice-trigger run --source SOURCE_NAME --loop -- notify-send "triggered"
```
```

- [ ] **Step 7: Commit**

```bash
git add src/voice_trigger/main.py tests/test_main.py README.md
git commit -m "feat: wire up CLI entry point with SIGTERM handling"
```

---

## Manual verification (requires real audio hardware, not part of the automated task steps)

After Task 5 is committed:

1. `make install`
2. `voice-trigger sources` — confirm your microphone's source name appears.
3. `voice-trigger monitor --source <name>` — tap/click near the mic and observe the level rise; pick a `--threshold` that separates clicks from silence.
4. `voice-trigger run --source <name> --threshold <value> --timeout 10 -- true; echo $?` — confirm it exits `0` on a detected click within 10s, or non-zero if you stay silent.
5. `voice-trigger run --source <name> --threshold <value> --loop -- notify-send "triggered"` — confirm repeated clicks repeatedly run the command; stop with Ctrl-C.
