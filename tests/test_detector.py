from array import array

from voice_trigger.detector import OnsetDetector, peak_level


def _chunk(amplitude: int, num_samples: int = 4) -> bytes:
    return array("h", [amplitude] * num_samples).tobytes()


def test_peak_level_of_silence_is_zero():
    assert peak_level(_chunk(0)) == 0.0


def test_peak_level_of_empty_chunk_is_zero():
    assert peak_level(b"") == 0.0


def test_peak_level_of_full_scale_is_near_one():
    assert peak_level(_chunk(32767)) > 0.999


def test_peak_level_ignores_sign():
    assert peak_level(_chunk(-32767)) > 0.999


def test_process_stays_false_below_threshold():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(1000), now=0.0) is False


def test_process_triggers_on_rising_edge():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(1000), now=0.0) is False
    assert detector.process(_chunk(30000), now=0.1) is True


def test_process_does_not_retrigger_while_sustained_above_threshold():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(30000), now=0.1) is False


def test_process_blocks_retrigger_within_cooldown():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(1000), now=0.2) is False
    assert detector.process(_chunk(30000), now=0.3) is False


def test_process_retriggers_after_cooldown_elapses():
    detector = OnsetDetector(threshold=0.5, cooldown=1.0)
    assert detector.process(_chunk(30000), now=0.0) is True
    assert detector.process(_chunk(1000), now=0.2) is False
    assert detector.process(_chunk(30000), now=1.1) is True
