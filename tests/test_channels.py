from hermes_trailhead.channels import CHANNELS, get_channel
from hermes_trailhead import channels as channels_mod
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


# ── Live doctor checks: local Redlib + Hermes env file ───────────────────


def test_check_reddit_live_prefers_local_instance(monkeypatch):
    fake = channels_mod.IO.fake(http_get=lambda url, timeout=5: (200, "<title>Redlib</title>"))
    monkeypatch.setattr(channels_mod, "_io", fake)

    res = channels_mod.check_reddit(live=True)

    assert res.status == "ok"
    assert "127.0.0.1:8789" in res.detail


def test_check_reddit_live_falls_back_to_remote_probe(monkeypatch):
    def http_get(url, timeout=5):
        if "127.0.0.1:8789" in url:
            raise RuntimeError("connection refused")
        return (200, "ok")

    fake = channels_mod.IO.fake(http_get=http_get)
    monkeypatch.setattr(channels_mod, "_io", fake)

    res = channels_mod.check_reddit(live=True)

    assert res.status == "ok"
    assert "redlib.perennialte.ch" in res.detail


def test_check_reddit_live_warns_when_both_routes_down(monkeypatch):
    def http_get(url, timeout=8):
        raise RuntimeError("connection refused")

    fake = channels_mod.IO.fake(http_get=http_get)
    monkeypatch.setattr(channels_mod, "_io", fake)

    res = channels_mod.check_reddit(live=True)

    assert res.status == "warn"


def test_check_reddit_live_reports_throttled_local_instance(monkeypatch):
    """A local Redlib that responds but 404s (upstream throttled) must be
    reported honestly, not as a dead instance."""

    def http_get(url, timeout=8):
        if "127.0.0.1:8789" in url:
            return (404, "")
        raise RuntimeError("connection refused")

    fake = channels_mod.IO.fake(http_get=http_get)
    monkeypatch.setattr(channels_mod, "_io", fake)

    res = channels_mod.check_reddit(live=True)

    assert res.status == "warn"
    assert "not serving" in res.detail


def test_firecrawl_env_file_fallback(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("FIRECRAWL_API_KEY=placeholder\n", encoding="utf-8")

    fake = channels_mod.IO.fake(
        getenv=lambda name: None,
        exists=lambda path: path == env,
        read_text=lambda path: env.read_text(encoding="utf-8"),
    )
    monkeypatch.setattr(channels_mod, "_io", fake)
    monkeypatch.setattr(channels_mod, "HERMES_HOME", tmp_path)

    res = channels_mod.check_firecrawl()

    assert res.status == "ok"
    assert ".env" in res.detail


def test_browserbase_env_file_fallback(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("BROWSERBASE_API_KEY=placeholder\nBROWSERBASE_PROJECT_ID=placeholder\n", encoding="utf-8")

    fake = channels_mod.IO.fake(
        getenv=lambda name: None,
        exists=lambda path: path == env,
        read_text=lambda path: env.read_text(encoding="utf-8"),
    )
    monkeypatch.setattr(channels_mod, "_io", fake)
    monkeypatch.setattr(channels_mod, "HERMES_HOME", tmp_path)

    res = channels_mod.check_browserbase()

    assert res.status == "ok"
