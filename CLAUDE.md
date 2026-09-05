# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`voice-trigger` is a Linux CLI that listens to a PulseAudio/PipeWire microphone and runs an arbitrary command when a short loud sound (e.g. a tongue click) is detected (`run`/`monitor`), or when a configured phrase is recognized (`listen`). Audio I/O is done by shelling out to `parec` (capture) and `pactl` (source enumeration), so those system tools must exist to run it (tests don't need them; they use fakes). Speech recognition uses vosk, with httpx and app-paths for model download/storage — all regular runtime dependencies. The README is written in Japanese.

Dependency policy (from the user): don't contort code to stay stdlib-only or dependency-free — prefer good libraries (httpx over urllib, app-paths for XDG dirs) as plain dependencies. No optional extras, and never make users run `uv tool install` variants by hand; `make install` is the whole story.

## Commands

Everything goes through `uv` and the Makefile:

- `make setup` — `uv sync` + install pre-commit hooks
- `make check` — mypy, then `ruff check --fix`, then `ruff format`
- `make test` — runs `make check` first, then pytest
- `uv run pytest tests/test_cli.py::test_name` — run a single test
- `make install` — `uv tool install --force --reinstall .` (installs the `voice-trigger` command for the user; run after finishing changes so the user can use the new version — see the `install-after-completion` skill)
- `make build` / `make publish-test` / `make publish-prod` — build and publish (publish targets take `TOKEN=...`)

Pre-commit runs mypy/ruff on commit and pytest on push, so `make test` passing means commits will go through cleanly.

## Architecture

Small pipeline under `src/voice_trigger/`, one concern per module:

- `main.py` — console-script entry point; maps SIGTERM to KeyboardInterrupt and exits with `cli.main()`'s return code.
- `cli.py` — click group and the subcommands: `run` (trigger a command on a loud sound, one-shot by default or `--loop`), `monitor` (print live levels to tune `--threshold`), `listen` (run commands mapped to recognized keywords, logging every recognition; `--dry-run` logs the same but never executes; settings resolve CLI option > config file > error/default), `vocab` (interactive REPL checking words against the model vocabulary), `paths` (print model storage locations and download state), `sources` (list source names). Owns the event loops: it pulls chunks from `AudioCapture` and feeds them to `OnsetDetector` or `CommandRecognizer`. Triggered commands are launched with `subprocess.Popen` (fire-and-forget, no shell).
- `audio.py` — `AudioCapture`, a context manager wrapping a `parec` subprocess emitting raw s16le mono 16 kHz PCM in 20 ms chunks. `--timeout` responsiveness in `cli._run` depends on chunks arriving every ~20 ms, since the deadline is only checked per chunk.
- `detector.py` — pure functions/state machine: `peak_level` (normalized 0–1 peak of a chunk) and `OnsetDetector`, which fires only on a rising edge (level crossing the threshold from below) and enforces a cooldown. Time is passed in as an argument, never read internally — this keeps it deterministic for tests.
- `sources.py` — `pactl` wrappers for listing sources and getting the default one.
- `config.py` — pydantic models for `listen`'s config file (`commands` entries — each with keywords, argv, and an optional `place-holder` string that `build_command` replaces with the recognized text — plus optional `language`/`source`), parsed from YAML/JSON via `yaml.safe_load`. Validation lives in the schema (strict `extra="forbid"`, duplicate-keyword check as a model validator), not hand-rolled checks; `load_config` converts YAML/validation errors to `RuntimeError` for the CLI's error path.
- `recognizer.py` — `CommandRecognizer` wraps a Vosk recognizer constrained to the configured phrases plus `[unk]` (grammar mode). Matching normalizes whitespace because Vosk returns tokenized text (relevant for Japanese). Configuring `"[unk]"` as a keyword makes it a catch-all for utterances that matched no other phrase (silence never fires). The Vosk objects are built only in the `create` classmethod; the class itself takes any `SpeechRecognizer` protocol object, which is how tests fake it.
- `models.py` — maps `--language` (`ja`/`en`) to a Vosk model name and auto-downloads it on first use (httpx + zipfile) into `app_paths`' user data dir. Download/extract happens in a sibling temp dir with an atomic rename at the end, so an interrupted run never leaves a partial model. Model choice constraint: grammar-constrained recognition only works with dynamic-graph models (HCLr/Gr.fst) — the big static-graph models (HCLG.fst, e.g. vosk-model-ja-0.22) reject runtime grammars, so each language uses its largest *dynamic-graph* model.

Error convention: lower layers raise `RuntimeError` (or let `FileNotFoundError` propagate for missing binaries); the `_cli_errors` decorator on each command converts them to `click.ClickException` (`Error: ...` on stderr, exit 1). Beware: click's `Exit`/`Abort` flow-control exceptions subclass `RuntimeError`, so the decorator must let them through. Usage errors exit 2 (click); KeyboardInterrupt (Ctrl-C or SIGTERM) becomes click's Abort (exit 1). Required parameters are positional arguments, not required options (user preference — e.g. `listen CONFIG_FILE`, `vocab LANGUAGE`).

Tests mirror the modules one-to-one and avoid real audio: they inject fake capture classes/chunk iterators and fixed timestamps, and build PCM chunks with `array("h", ...)`. Follow that pattern rather than mocking `parec`.
