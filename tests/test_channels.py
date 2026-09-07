from hermes_trailhead.channels import CHANNELS, get_channel
from hermes_trailhead.paths import resolve_hermes_home


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


def test_resolve_hermes_home_normal(tmp_path):
    # Standard layout: $HOME/.hermes holds config.yaml.
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "config.yaml").write_text("x: 1")
    got = resolve_hermes_home(tmp_path)
    assert got == tmp_path / ".hermes"


def test_resolve_hermes_home_nested_chroot(tmp_path):
    # Chroot/container layout: $HOME points INSIDE a .hermes dir and the real
    # config lives in the enclosing .hermes. Regression: the doctor used to
    # report the config "missing" at the fake $HOME/.hermes path.
    hermes = tmp_path / ".hermes"
    fake_home = hermes / "home"
    fake_home.mkdir(parents=True)
    (hermes / "config.yaml").write_text("x: 1")
    got = resolve_hermes_home(fake_home)
    assert got == hermes


def test_resolve_hermes_home_falls_back_when_no_config(tmp_path):
    # No config anywhere: fall back to $HOME/.hermes so the doctor reports it
    # as missing rather than guessing.
    (tmp_path / ".hermes").mkdir()
    got = resolve_hermes_home(tmp_path)
    assert got == tmp_path / ".hermes"
