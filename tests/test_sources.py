import subprocess

import pytest

from voice_trigger import sources
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
