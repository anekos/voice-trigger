from __future__ import annotations

import json
from array import array
from collections.abc import Iterator
from typing import Self

import pytest

from voice_trigger import cli, models
from voice_trigger.recognizer import Recognition


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


def test_run_accepts_short_options():
    args = cli.build_parser().parse_args(
        ["run", "-s", "mysrc", "-t", "0.4", "-c", "0.6", "-T", "5"]
    )
    assert args.source == "mysrc"
    assert args.threshold == 0.4
    assert args.cooldown == 0.6
    assert args.timeout == 5.0


def test_run_accepts_short_loop_option():
    args = cli.build_parser().parse_args(["run", "-l"])
    assert args.loop is True


def test_short_loop_and_short_timeout_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "-l", "-T", "5"])


def test_monitor_accepts_short_options():
    args = cli.build_parser().parse_args(["monitor", "-s", "mysrc", "-t", "0.4"])
    assert args.source == "mysrc"
    assert args.threshold == 0.4


def test_run_prints_selected_source_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 10.0]))
    args = cli.build_parser().parse_args(["run", "-s", "mysrc", "-T", "5"])
    cli._run(args)
    assert capsys.readouterr().err == "source: mysrc\n"


def test_run_prints_resolved_default_source_when_no_source_given(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 10.0]))
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    args = cli.build_parser().parse_args(["run", "-T", "5"])
    cli._run(args)
    assert capsys.readouterr().err == "source: defaultsrc\n"


def test_run_one_shot_triggers_command_and_exits_zero(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    args = cli.build_parser().parse_args(["run", "--", "echo", "hi"])
    assert cli._run(args) == 0
    assert popen_calls == [["echo", "hi"]]


def test_run_one_shot_without_command_exits_zero_on_trigger(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    args = cli.build_parser().parse_args(["run"])
    assert cli._run(args) == 0
    assert popen_calls == []


def test_run_timeout_without_detection_exits_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()] * 3))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.1, 0.2, 10.0]))
    args = cli.build_parser().parse_args(["run", "--timeout", "5"])
    assert cli._run(args) == 1


def test_run_loop_keeps_triggering_command(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
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
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    args = cli.build_parser().parse_args(["monitor"])
    assert cli._monitor(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "TRIGGER" not in lines[0]
    assert "TRIGGER" in lines[1]


def test_monitor_overwrites_non_trigger_lines_and_keeps_trigger_lines(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    args = cli.build_parser().parse_args(["monitor"])
    assert cli._monitor(args) == 0
    out = capsys.readouterr().out
    assert out.count("\r") == 1
    assert out.count("\n") == 1
    assert out.index("\r") < out.index("\n")


def test_monitor_throttles_display_and_keeps_peak_seen_between_prints(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli,
        "AudioCapture",
        _FakeAudioCapture([_quiet_chunk(), _loud_chunk(), _quiet_chunk()]),
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.05, 0.15]))
    args = cli.build_parser().parse_args(["monitor"])
    assert cli._monitor(args) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2  # the loud chunk at t=0.05 didn't get its own print
    assert "TRIGGER" not in lines[0]
    assert "TRIGGER" in lines[1]  # but its peak wasn't lost


def test_monitor_prints_selected_source_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    args = cli.build_parser().parse_args(["monitor", "-s", "mysrc"])
    cli._monitor(args)
    assert capsys.readouterr().err == "source: mysrc\n"


def test_sources_prints_each_name(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_sources", lambda: ["a", "b"])
    assert cli._sources() == 0
    assert capsys.readouterr().out == "a\nb\n"


class _FakeCommandRecognizer:
    def __init__(self, results: list[Recognition | None]) -> None:
        self._results = iter(results)

    def process(self, chunk: bytes) -> Recognition | None:
        return next(self._results)


def _patch_listen(monkeypatch, tmp_path, results: list[Recognition | None]):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()] * len(results))
    )
    monkeypatch.setattr(cli, "ensure_model", lambda language: tmp_path)
    monkeypatch.setattr(
        cli.CommandRecognizer,
        "create",
        lambda model_path, phrases, sample_rate: _FakeCommandRecognizer(results),
    )


def _commands_file(tmp_path, mapping) -> str:
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(mapping))
    return str(path)


def test_listen_requires_language_and_commands():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["listen"])


def test_listen_rejects_unknown_language(tmp_path):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["listen", "--language", "de", "--commands", "commands.json"]
        )


def test_listen_language_choices_match_available_models():
    parser = cli.build_parser()
    args = parser.parse_args(["listen", "--language", "ja", "--commands", "x.json"])
    assert args.language in models.LANGUAGE_MODELS
    for language in models.LANGUAGE_MODELS:
        parser.parse_args(["listen", "--language", language, "--commands", "x.json"])


def test_listen_runs_mapped_command(monkeypatch, tmp_path, capsys):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(
        monkeypatch,
        tmp_path,
        [None, Recognition(text="open browser", phrase="open browser")],
    )
    commands = _commands_file(
        tmp_path, [{"keywords": ["open browser"], "command": ["echo", "hi"]}]
    )
    args = cli.build_parser().parse_args(
        ["listen", "--language", "en", "--commands", commands]
    )
    assert cli._listen(args) == 1  # capture exhausted without an explicit stop
    assert popen_calls == [["echo", "hi"]]
    assert capsys.readouterr().out.splitlines() == [
        "heard: 'open browser' -> open browser"
    ]


def test_listen_ignores_unmatched_utterances(monkeypatch, tmp_path):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(monkeypatch, tmp_path, [Recognition(text="[unk]", phrase=None)])
    commands = _commands_file(
        tmp_path, [{"keywords": ["open browser"], "command": ["echo", "hi"]}]
    )
    args = cli.build_parser().parse_args(
        ["listen", "--language", "en", "--commands", commands]
    )
    cli._listen(args)
    assert popen_calls == []


def test_listen_dry_run_logs_but_never_runs(monkeypatch, tmp_path, capsys):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(
        monkeypatch,
        tmp_path,
        [
            Recognition(text="open browser", phrase="open browser"),
            Recognition(text="[unk]", phrase=None),
        ],
    )
    commands = _commands_file(
        tmp_path, [{"keywords": ["open browser"], "command": ["echo", "hi"]}]
    )
    args = cli.build_parser().parse_args(
        ["listen", "--language", "en", "--commands", commands, "--dry-run"]
    )
    cli._listen(args)
    assert popen_calls == []
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "heard: 'open browser' -> open browser",
        "heard: '[unk]' -> (no match)",
    ]


def test_listen_reports_missing_commands_file(tmp_path, capsys):
    missing = str(tmp_path / "nope.json")
    assert cli.main(["listen", "--language", "en", "--commands", missing]) == 1
    assert "nope.json" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content",
    [
        "[unclosed",
        "just a scalar",
        "[]",
        "{}",
        '["not-an-object"]',
        '[{"keywords": ["a"]}]',
        '[{"keywords": ["a"], "command": ["x"], "extra": 1}]',
        '[{"keywords": [], "command": ["x"]}]',
        '[{"keywords": ["a"], "command": []}]',
        '[{"keywords": ["a", 1], "command": ["x"]}]',
        '[{"keywords": ["a"], "command": "not-a-list"}]',
    ],
)
def test_load_commands_rejects_invalid_mappings(tmp_path, content):
    path = tmp_path / "commands.json"
    path.write_text(content)
    with pytest.raises(RuntimeError):
        cli._load_commands(str(path))


def test_load_commands_rejects_duplicate_keywords(tmp_path):
    path = _commands_file(
        tmp_path,
        [
            {"keywords": ["a"], "command": ["x"]},
            {"keywords": ["b", "a"], "command": ["y"]},
        ],
    )
    with pytest.raises(RuntimeError, match="duplicate keyword 'a'"):
        cli._load_commands(path)


def test_load_commands_maps_every_keyword_to_its_command(tmp_path):
    path = _commands_file(
        tmp_path,
        [
            {
                "keywords": ["ブラウザ ひらいて", "ぶらうざ"],
                "command": ["xdg-open", "https://a"],
            },
            {"keywords": ["つぎ"], "command": ["playerctl", "next"]},
        ],
    )
    assert cli._load_commands(path) == {
        "ブラウザ ひらいて": ["xdg-open", "https://a"],
        "ぶらうざ": ["xdg-open", "https://a"],
        "つぎ": ["playerctl", "next"],
    }


def test_load_commands_accepts_yaml(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(
        "- keywords: [ぶらうざ]\n"
        "  command: [xdg-open, 'https://a']\n"
        "- keywords: [つぎ, ねくすと]\n"
        "  command: [playerctl, next]\n"
    )
    assert cli._load_commands(str(path)) == {
        "ぶらうざ": ["xdg-open", "https://a"],
        "つぎ": ["playerctl", "next"],
        "ねくすと": ["playerctl", "next"],
    }


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
