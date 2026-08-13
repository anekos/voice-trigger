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
