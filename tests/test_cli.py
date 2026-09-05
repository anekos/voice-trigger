from __future__ import annotations

import json
from array import array
from collections.abc import Iterator
from typing import Self

from click.testing import CliRunner

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


def _invoke(*args: str):
    return CliRunner().invoke(cli.cli, args)


def test_run_rejects_loop_with_timeout():
    for argv in (["run", "--loop", "--timeout", "5"], ["run", "-l", "-T", "5"]):
        result = CliRunner().invoke(cli.cli, argv)
        assert result.exit_code == 2
        assert "mutually exclusive" in result.stderr


def test_run_prints_selected_source_to_stderr(monkeypatch):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 10.0]))
    result = _invoke("run", "-s", "mysrc", "-T", "5")
    assert result.stderr == "source: mysrc\n"


def test_run_prints_resolved_default_source_when_no_source_given(monkeypatch):
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 10.0]))
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    result = _invoke("run", "-T", "5")
    assert result.stderr == "source: defaultsrc\n"


def test_run_one_shot_triggers_command_after_dashdash_and_exits_zero(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0]))
    result = _invoke("run", "--", "echo", "hi")
    assert result.exit_code == 0
    assert popen_calls == [["echo", "hi"]]


def test_run_one_shot_without_command_exits_zero_on_trigger(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_loud_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0]))
    result = _invoke("run")
    assert result.exit_code == 0
    assert popen_calls == []


def test_run_timeout_without_detection_exits_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()] * 3))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.1, 0.2, 10.0]))
    result = _invoke("run", "--timeout", "5")
    assert result.exit_code == 1


def test_run_accepts_short_options(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()]))
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 10.0]))
    result = _invoke("run", "-s", "mysrc", "-t", "0.4", "-c", "0.6", "-T", "5")
    assert result.exit_code == 1  # -T deadline passed without a trigger
    assert result.stderr == "source: mysrc\n"


def test_run_loop_keeps_triggering_command(monkeypatch):
    popen_calls = []
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    monkeypatch.setattr(
        cli,
        "AudioCapture",
        _FakeAudioCapture([_loud_chunk(), _quiet_chunk(), _loud_chunk()]),
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 1.0, 2.0]))
    result = _invoke("run", "--loop", "--", "echo", "hi")
    assert result.exit_code == 1  # generator exhausted, no explicit stop requested
    assert popen_calls == [["echo", "hi"], ["echo", "hi"]]


def test_monitor_prints_level_for_each_chunk(monkeypatch):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    result = _invoke("monitor", "-t", "0.4")
    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    assert "TRIGGER" not in lines[0]
    assert "TRIGGER" in lines[1]


def test_monitor_overwrites_non_trigger_lines_and_keeps_trigger_lines(monkeypatch):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    result = _invoke("monitor")
    out = result.stdout
    assert out.count("\r") == 1
    assert out.count("\n") == 1
    assert out.index("\r") < out.index("\n")


def test_monitor_throttles_display_and_keeps_peak_seen_between_prints(monkeypatch):
    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli,
        "AudioCapture",
        _FakeAudioCapture([_quiet_chunk(), _loud_chunk(), _quiet_chunk()]),
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.05, 0.15]))
    result = _invoke("monitor")
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2  # the loud chunk at t=0.05 didn't get its own print
    assert "TRIGGER" not in lines[0]
    assert "TRIGGER" in lines[1]  # but its peak wasn't lost


def test_monitor_prints_selected_source_to_stderr(monkeypatch):
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk(), _loud_chunk()])
    )
    monkeypatch.setattr(cli.time, "monotonic", _fake_clock([0.0, 0.2]))
    result = _invoke("monitor", "-s", "mysrc")
    assert result.stderr == "source: mysrc\n"


class _FakeCommandRecognizer:
    def __init__(self, results: list[Recognition | None]) -> None:
        self._results = iter(results)

    def process(self, chunk: bytes) -> Recognition | None:
        return next(self._results)


def _patch_listen(
    monkeypatch, tmp_path, results: list[Recognition | None]
) -> list[str]:
    """Fake audio and recognition; returns the languages passed to ensure_model."""
    languages: list[str] = []

    def ensure_model(language: str):
        languages.append(language)
        return tmp_path

    monkeypatch.setattr(cli, "get_default_source", lambda: "defaultsrc")
    monkeypatch.setattr(
        cli, "AudioCapture", _FakeAudioCapture([_quiet_chunk()] * len(results))
    )
    monkeypatch.setattr(cli, "ensure_model", ensure_model)
    monkeypatch.setattr(
        cli.CommandRecognizer,
        "create",
        lambda model_path, phrases, sample_rate: _FakeCommandRecognizer(results),
    )
    return languages


_ECHO_COMMANDS = [{"keywords": ["open browser"], "command": ["echo", "hi"]}]


def _config_file(tmp_path, commands, **settings) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"commands": commands, **settings}))
    return str(path)


def test_listen_requires_config_file():
    assert _invoke("listen").exit_code == 2


def test_listen_rejects_unknown_language(tmp_path):
    config = _config_file(tmp_path, _ECHO_COMMANDS)
    assert _invoke("listen", "--language", "de", config).exit_code == 2


def test_listen_accepts_every_available_model_language(monkeypatch, tmp_path):
    for language in models.LANGUAGE_MODELS:
        _patch_listen(monkeypatch, tmp_path, [])
        config = _config_file(tmp_path, _ECHO_COMMANDS)
        result = _invoke("listen", "--language", language, config)
        assert result.exit_code == 1  # accepted; capture exhausted immediately


def test_listen_requires_language_from_option_or_config(monkeypatch, tmp_path):
    _patch_listen(monkeypatch, tmp_path, [])
    config = _config_file(tmp_path, _ECHO_COMMANDS)
    result = _invoke("listen", config)
    assert result.exit_code == 2
    assert "language" in result.stderr


def test_listen_takes_language_from_config(monkeypatch, tmp_path):
    languages = _patch_listen(monkeypatch, tmp_path, [])
    config = _config_file(tmp_path, _ECHO_COMMANDS, language="ja")
    assert _invoke("listen", config).exit_code == 1
    assert languages == ["ja"]


def test_listen_language_option_overrides_config(monkeypatch, tmp_path):
    languages = _patch_listen(monkeypatch, tmp_path, [])
    config = _config_file(tmp_path, _ECHO_COMMANDS, language="ja")
    assert _invoke("listen", "--language", "en", config).exit_code == 1
    assert languages == ["en"]


def test_listen_takes_source_from_config(monkeypatch, tmp_path):
    _patch_listen(monkeypatch, tmp_path, [])
    config = _config_file(tmp_path, _ECHO_COMMANDS, language="ja", source="cfgsrc")
    result = _invoke("listen", config)
    assert result.stderr == "source: cfgsrc\n"


def test_listen_source_option_overrides_config(monkeypatch, tmp_path):
    _patch_listen(monkeypatch, tmp_path, [])
    config = _config_file(tmp_path, _ECHO_COMMANDS, language="ja", source="cfgsrc")
    result = _invoke("listen", "-s", "optsrc", config)
    assert result.stderr == "source: optsrc\n"


def test_listen_runs_mapped_command(monkeypatch, tmp_path):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(
        monkeypatch,
        tmp_path,
        [None, Recognition(text="open browser", phrase="open browser")],
    )
    config = _config_file(tmp_path, _ECHO_COMMANDS)
    result = _invoke("listen", "--language", "en", config)
    assert result.exit_code == 1  # capture exhausted without an explicit stop
    assert popen_calls == [["echo", "hi"]]
    assert result.stdout.splitlines() == ["heard: 'open browser' -> open browser"]


def test_listen_fills_placeholder_with_recognized_text(monkeypatch, tmp_path):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(
        monkeypatch,
        tmp_path,
        [Recognition(text="ブラウザ ひらいて", phrase="ブラウザ ひらいて")],
    )
    config = _config_file(
        tmp_path,
        [
            {
                "keywords": ["ブラウザ ひらいて"],
                "place-holder": "%s",
                "command": ["notify-send", "heard: %s"],
            }
        ],
        language="ja",
    )
    _invoke("listen", config)
    assert popen_calls == [["notify-send", "heard: ブラウザ ひらいて"]]


def test_listen_ignores_unmatched_utterances(monkeypatch, tmp_path):
    popen_calls = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
    _patch_listen(monkeypatch, tmp_path, [Recognition(text="[unk]", phrase=None)])
    config = _config_file(tmp_path, _ECHO_COMMANDS)
    _invoke("listen", "--language", "en", config)
    assert popen_calls == []


def test_listen_dry_run_logs_but_never_runs(monkeypatch, tmp_path):
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
    config = _config_file(tmp_path, _ECHO_COMMANDS)
    result = _invoke("listen", "--language", "en", config, "--dry-run")
    assert popen_calls == []
    assert result.stdout.splitlines() == [
        "heard: 'open browser' -> open browser",
        "heard: '[unk]' -> (no match)",
    ]


def test_listen_reports_missing_config_file(tmp_path):
    missing = str(tmp_path / "nope.json")
    result = _invoke("listen", "--language", "en", missing)
    assert result.exit_code == 2  # click.Path(exists=True) rejects it
    assert "nope.json" in result.stderr


def test_listen_reports_invalid_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"commands": []}')
    result = _invoke("listen", "--language", "en", str(path))
    assert result.exit_code == 1
    assert "Error:" in result.stderr


class _FakeVocabulary:
    def __init__(self, words: set[str]) -> None:
        self._words = words

    def __contains__(self, word: str) -> bool:
        return word in self._words


def test_vocab_reports_each_word_per_line(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ensure_model", lambda language: tmp_path)
    monkeypatch.setattr(
        cli.Vocabulary,
        "load",
        lambda model_path: _FakeVocabulary({"ぶらうざ", "つぎ"}),
    )
    result = CliRunner().invoke(
        cli.cli, ["vocab", "ja"], input="ぶらうざ ブラウザ\nつぎ\n"
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "ぶらうざ: ok",
        "ブラウザ: missing",
        "つぎ: ok",
    ]


def test_vocab_requires_language():
    assert _invoke("vocab").exit_code == 2


def test_vocab_rejects_unknown_language():
    assert _invoke("vocab", "de").exit_code == 2


def test_paths_prints_model_locations_and_download_state(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "models_dir", lambda: tmp_path)
    ja_model = tmp_path / models.LANGUAGE_MODELS["ja"]
    ja_model.mkdir()
    result = _invoke("paths")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == f"models: {tmp_path}"
    assert f"model[ja]: {ja_model} (downloaded)" in lines
    en_model = tmp_path / models.LANGUAGE_MODELS["en"]
    assert f"model[en]: {en_model} (not downloaded)" in lines


def test_sources_prints_each_name(monkeypatch):
    monkeypatch.setattr(cli, "list_sources", lambda: ["a", "b"])
    result = _invoke("sources")
    assert result.exit_code == 0
    assert result.stdout == "a\nb\n"


def test_missing_parec_reports_clean_error(monkeypatch):
    def _raise(source: str | None) -> None:
        raise FileNotFoundError(2, "No such file or directory", "parec")

    monkeypatch.setattr(cli, "AudioCapture", _raise)
    result = _invoke("run")
    assert result.exit_code == 1
    assert "parec" in result.stderr


def test_keyboard_interrupt_exits_nonzero(monkeypatch):
    def _raise(source: str | None) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "AudioCapture", _raise)
    result = _invoke("run")
    assert result.exit_code == 1
