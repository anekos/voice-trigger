import subprocess

import pytest

from voice_trigger import sources
from voice_trigger.sources import get_default_source, parse_source_names

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


def test_list_sources_raises_runtime_error_with_stderr_on_pactl_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["pactl", "list", "short", "sources"],
            stderr="Connection refused\n",
        )

    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Connection refused"):
        sources.list_sources()


def test_get_default_source_strips_trailing_newline(monkeypatch: pytest.MonkeyPatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["pactl", "get-default-source"],
            returncode=0,
            stdout="alsa_input.pci-0000_00_1f.3.analog-stereo\n",
        )

    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    assert get_default_source() == "alsa_input.pci-0000_00_1f.3.analog-stereo"


def test_get_default_source_raises_runtime_error_with_stderr_on_pactl_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["pactl", "get-default-source"],
            stderr="Connection refused\n",
        )

    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Connection refused"):
        get_default_source()
