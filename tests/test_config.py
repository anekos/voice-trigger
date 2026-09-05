from __future__ import annotations

import json

import pytest

from voice_trigger.config import load_config


def _write(tmp_path, content: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return str(path)


@pytest.mark.parametrize(
    "content",
    [
        "[unclosed",
        "just a scalar",
        "[]",
        "{}",
        '{"commands": []}',
        '{"commands": "not-an-array"}',
        '{"commands": ["not-an-object"]}',
        '{"commands": [{"keywords": ["a"]}]}',
        '{"commands": [{"keywords": ["a"], "command": ["x"], "extra": 1}]}',
        '{"commands": [{"keywords": [], "command": ["x"]}]}',
        '{"commands": [{"keywords": ["a"], "command": []}]}',
        '{"commands": [{"keywords": ["a", 1], "command": ["x"]}]}',
        '{"commands": [{"keywords": ["a"], "command": "not-a-list"}]}',
        '{"commands": [{"keywords": ["a"], "command": ["x"]}], "unknown": 1}',
        '{"commands": [{"keywords": ["a"], "command": ["x"]}], "language": "de"}',
        '{"commands": [{"keywords": ["a"], "command": ["x"]}], "source": 1}',
    ],
)
def test_load_config_rejects_invalid_content(tmp_path, content):
    with pytest.raises(RuntimeError):
        load_config(_write(tmp_path, content))


def test_load_config_rejects_duplicate_keywords_across_entries(tmp_path):
    content = json.dumps(
        {
            "commands": [
                {"keywords": ["a"], "command": ["x"]},
                {"keywords": ["b", "a"], "command": ["y"]},
            ]
        }
    )
    with pytest.raises(RuntimeError, match="duplicate keyword 'a'"):
        load_config(_write(tmp_path, content))


def test_keyword_commands_maps_every_keyword_to_its_command(tmp_path):
    content = json.dumps(
        {
            "commands": [
                {
                    "keywords": ["ブラウザ ひらいて", "ぶらうざ"],
                    "command": ["xdg-open", "https://a"],
                },
                {"keywords": ["つぎ"], "command": ["playerctl", "next"]},
            ]
        }
    )
    config = load_config(_write(tmp_path, content))
    assert config.keyword_commands() == {
        "ブラウザ ひらいて": ["xdg-open", "https://a"],
        "ぶらうざ": ["xdg-open", "https://a"],
        "つぎ": ["playerctl", "next"],
    }
    assert config.language is None
    assert config.source is None


def test_load_config_accepts_yaml_with_settings(tmp_path):
    content = (
        "language: ja\n"
        "source: mysrc\n"
        "commands:\n"
        "  - keywords: [ぶらうざ]\n"
        "    command: [xdg-open, 'https://a']\n"
        "  - keywords: [つぎ, ねくすと]\n"
        "    command: [playerctl, next]\n"
    )
    config = load_config(_write(tmp_path, content))
    assert config.language == "ja"
    assert config.source == "mysrc"
    assert config.keyword_commands() == {
        "ぶらうざ": ["xdg-open", "https://a"],
        "つぎ": ["playerctl", "next"],
        "ねくすと": ["playerctl", "next"],
    }
