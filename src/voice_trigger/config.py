"""Listen-mode configuration: keyword/command mapping plus optional settings."""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class CommandEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    placeholder: str | None = Field(None, alias="place-holder", min_length=1)

    def build_command(self, text: str) -> list[str]:
        """The argv to run, with the recognized text filling the placeholder."""
        if self.placeholder is None:
            return self.command
        return [arg.replace(self.placeholder, text) for arg in self.command]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[CommandEntry] = Field(min_length=1)
    language: Literal["ja", "en"] | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _forbid_duplicate_keywords(self) -> Config:
        seen: set[str] = set()
        for entry in self.commands:
            for keyword in entry.keywords:
                if keyword in seen:
                    raise ValueError(f"duplicate keyword {keyword!r}")
                seen.add(keyword)
        return self

    def keyword_entries(self) -> dict[str, CommandEntry]:
        """Flatten the entries into a keyword -> entry mapping."""
        return {keyword: entry for entry in self.commands for keyword in entry.keywords}


def load_config(path: str) -> Config:
    with open(path) as file:
        try:
            # YAML is a superset of JSON, so one parser covers both formats.
            data = yaml.safe_load(file)
        except yaml.YAMLError as error:
            raise RuntimeError(f"{path} is not valid YAML: {error}") from error
    try:
        return Config.model_validate(data)
    except ValidationError as error:
        raise RuntimeError(f"{path}: {error}") from error
