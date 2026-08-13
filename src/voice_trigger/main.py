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
