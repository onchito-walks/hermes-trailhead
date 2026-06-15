from hermes_trailhead.channels import CHANNELS, get_channel


def test_channels_have_unique_keys():
    keys = [channel.key for channel in CHANNELS]
    assert len(keys) == len(set(keys))


def test_core_channels_present():
    for key in ["web-search", "x-search", "hermes-upstream", "newsletter", "docs-watcher", "agent-reach"]:
        assert get_channel(key).key == key


def test_setup_plans_are_non_empty():
    for channel in CHANNELS:
        assert channel.setup_plan
        assert channel.title
        assert channel.default_path
