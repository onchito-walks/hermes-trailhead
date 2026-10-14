"""Hermetic tests for the Camofox authenticated-session tier.

Instagram profiles and Facebook pages are fetched through the local Camofox
browser server's persistent profile (logged-in session cookies). These tests
mock the Camofox HTTP client — no live browser needed.
"""
from __future__ import annotations

import json

import pytest

import hermes_trailhead.extract as ex


def test_camofox_session_fetch_formats_and_closes_tab(monkeypatch):
    calls = []

    def fake_req(path, payload=None, method="GET", timeout=20):
        calls.append((path, method))
        if path == "/tabs":
            assert payload["userId"] == ex._CAMOFOX_USER
            assert payload["sessionKey"] == ex._CAMOFOX_TAB_GROUP
            return {"tabId": "tab-1"}
        if path == "/tabs/tab-1/evaluate":
            return {"ok": True, "result": json.dumps({
                "title": "NASA (@nasa) • Instagram",
                "og": "",
                "desc": "104M Followers, 94 Following",
                "text": "Body line " * 60,
            })}
        if path.startswith("/tabs/tab-1?userId=") and method == "DELETE":
            return {"ok": True}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(ex, "_camofox_req", fake_req)
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    out = ex._camofox_session_fetch("https://www.instagram.com/nasa/")
    assert "104M Followers" in out
    assert "Body line" in out
    # tab is cleaned up afterwards
    assert calls[-1][1] == "DELETE"


def test_camofox_session_fetch_rejects_logged_out_shell(monkeypatch):
    def fake_req(path, payload=None, method="GET", timeout=20):
        if path == "/tabs":
            return {"tabId": "tab-2"}
        if path == "/tabs/tab-2/evaluate":
            return {"ok": True, "result": json.dumps({
                "title": "Instagram",
                "og": "",
                "desc": "",
                "text": "Log into Instagram\nMobile number, username or email\nPassword\nLog in",
            })}
        return {"ok": True}

    monkeypatch.setattr(ex, "_camofox_req", fake_req)
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="not logged in"):
        ex._camofox_session_fetch("https://www.instagram.com/someone/")


def test_camofox_session_fetch_raises_when_no_tab(monkeypatch):
    monkeypatch.setattr(ex, "_camofox_req", lambda path, payload=None, method="GET", timeout=20: {"error": "browser down"})
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="could not open tab"):
        ex._camofox_session_fetch("https://www.instagram.com/x/")


def test_extract_one_instagram_profile_uses_camofox(monkeypatch):
    def no_shortcode(url, timeout=20):
        raise RuntimeError("no instagram shortcode")

    monkeypatch.setattr(ex, "_fetch_instagram_embed", no_shortcode)
    monkeypatch.setattr(ex, "_get_apify_token", lambda: None)
    monkeypatch.setattr(ex, "_camofox_session_fetch", lambda url, timeout=30: "AUTHED PROFILE CONTENT " * 40)

    r = ex.extract_one("https://www.instagram.com/nasa/")
    assert r.status == "ok"
    assert "AUTHED PROFILE CONTENT" in r.content


def test_extract_one_facebook_page_uses_camofox(monkeypatch):
    monkeypatch.setattr(ex, "_get_apify_token", lambda: None)
    monkeypatch.setattr(ex, "_camofox_session_fetch", lambda url, timeout=30: "FB PAGE CONTENT " * 60)

    r = ex.extract_one("https://www.facebook.com/NASA/")
    assert r.status == "ok"
    assert "FB PAGE CONTENT" in r.content
