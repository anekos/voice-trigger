from __future__ import annotations

from array import array
from collections.abc import Iterator
from typing import Self

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

    def __call__(self, source: str | None) -> _FakeAudioCapture:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def chunks(self) -> Iterator[bytes]:
        yield from self._chunks


def _fake_clock(values: list[float]):
    it = iter(values)
    return lambda: next(it)


def test_run_and_timeout_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--loop", "--timeout", "5"])


def test_parses_command_after_dashdash():
    args = cli.build_parser().parse_args(
        ["run", "--threshold", "0.4", "--", "echo", "hi"]
    )
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
        cli,
        "AudioCapture",
        _FakeAudioCapture([_loud_chunk(), _quiet_chunk(), _loud_chunk()]),
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.0, 1.0, 2.0]))
    args = cli.build_parser().parse_args(["run", "--loop", "--", "echo", "hi"])
    assert cli._run(args) == 1  # generator exhausted, no explicit stop requested
    assert popen_calls == [["echo", "hi"], ["echo", "hi"]]


def test_monitor_prints_level_for_each_chunk(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
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
