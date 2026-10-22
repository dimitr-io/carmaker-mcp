"""The guide, section by section (agents in some clients cannot open MCP resources)."""

import pytest

from carmaker_mcp import guide


def test_topics_and_sections():
    assert "ipgdriver" in guide.section(None) and "Topics:" in guide.section(None)
    s = guide.section("ipgdriver")
    assert s.startswith("## IPGDriver reference") and "## When something goes wrong" not in s
    for key in ("Driver.Course.CornerCutCoef", "Driver.Mode", "Driver.Knowl", "Driver.Long.dtAccBrake",
                "Lap-time optimisation procedure", "Race Driver Adaption"):
        assert key in s, key
    assert guide.section("safety").startswith("## Safety")
    with pytest.raises(ValueError, match="unknown topic"):
        guide.section("nope")


def test_every_topic_finds_its_section():
    for topic, heading in guide.TOPICS.items():
        assert guide.section(topic).startswith(heading), topic
