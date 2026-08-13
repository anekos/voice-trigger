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
