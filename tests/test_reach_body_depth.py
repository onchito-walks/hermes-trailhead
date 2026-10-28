"""Regression tests: bounded full-body preservation for forwarded reads.

The behaviour under test
------------------------
``reach_backend._normalize_items`` used to clip *every* item's ``text`` to
``MAX_TEXT_CHARS`` (4000).  For discovery that bound is right — a snippet is a
lead.  For ``BODY_READ_ACTIONS`` it was the whole artifact: a V2EX topic was cut
mid-reply and a README mid-tail, so the forwarded item was partial by
construction no matter what the caller did.

Body reads now preserve the complete upstream-returned text under one shared
``MAX_TOTAL_BODY_CHARS`` budget, derived from the existing ``MAX_OUTPUT_BYTES``
subprocess capture cap.  Nothing larger is captured: the runner still refuses
more than 4 MB of stdout.  The budget is sized for the *escape-worst* JSON form
(``ensure_ascii=True`` turns a non-BMP codepoint into a 12-byte surrogate pair),
so the forwarded body alone costs at most ~3 MB; metadata keeps its own
per-field bounds.  That is a forwarding bound, not an envelope-size guarantee.

These tests pin, with no network and no real Agent Reach install:

* a body past 4000 characters arrives whole (ASCII and multibyte), and the
  per-item ``body`` metadata reports upstream chars, returned chars and local
  truncation truthfully;
* local truncation happens only at the shared budget, is flagged per item, and
  the serialised body stays well inside ``MAX_OUTPUT_BYTES`` even when every
  forwarded character is a 12-byte surrogate-pair escape;
* 50 items with large metadata plus a full emoji body stay under the cap in
  compact, pretty, ``ensure_ascii=True`` and ``ensure_ascii=False`` forms;
* discovery snippet text keeps ``MAX_TEXT_CHARS`` and gains no body metadata;
* shell classification judges the entire bounded body, so a marker in a short
  prefix cannot condemn a real document;
* a genuine short shell is still withheld on the body path;
* malformed item types never raise and never inflate the envelope;
* upstream continuation is reported as *unknown* (never complete, never
  "exhausted"), including when pagination-shaped or zero-valued cursor fields
  appear; an explicit ``truncated`` bool is echoed and never followed.
"""
from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from hermes_trailhead import reach_backend as reach
from hermes_trailhead.extract import classify_page_shell

V2EX_URL = "https://www.v2ex.com/t/1"
BACKEND = "v2ex-api"


# ── fixtures ──────────────────────────────────────────────────────────────


def _param(name: str, *, required: bool = False, ptype: str = "str") -> dict:
    return {"name": name, "help": "", "required": required, "type": ptype, "default": None}


def registry_payload() -> dict:
    """Minimal shape-accurate ``agent-reach channels`` payload (v1.6.0)."""
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {"read": "agent-reach read <url>", "action": "agent-reach <channel> <action>"},
        "channels": [
            {
                "name": "v2ex",
                "description": "V2EX 节点、主题与回复",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "hot",
                        "help": "Hot topics",
                        "usage": "agent-reach v2ex hot [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": [BACKEND],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a topic and its replies",
                        "usage": "agent-reach v2ex read <target>",
                        "params": [_param("target", required=True)],
                        "backends": [BACKEND],
                        "public_web": [],
                    },
                ],
            }
        ],
        "meta": {"elapsed_ms": 3, "attempts": []},
    }


def envelope(channel: str, action: str, *, items, backend: str = BACKEND, **extra) -> dict:
    payload = {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": backend,
        "items": items,
        "meta": {"elapsed_ms": 41, "attempts": [{"backend": backend, "result": "ok"}]},
        "error": None,
    }
    payload.update(extra)
    return payload


def item(text, *, title="topic", url=V2EX_URL, author="someone",
         published_at="2026-01-01T00:00:00Z", raw=None) -> dict:
    return {
        "title": title,
        "url": url,
        "author": author,
        "published_at": published_at,
        "text": text,
        "raw": raw,
    }


class Runner:
    """Replays one queued upstream response; records every argv it was given."""

    def __init__(self, action_response):
        self.action_response = action_response
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, timeout, env):
        self.calls.append(list(argv))
        if list(argv)[1:] == ["channels"]:
            body = json.dumps(registry_payload(), ensure_ascii=False)
        elif isinstance(self.action_response, str):
            body = self.action_response
        else:
            body = json.dumps(self.action_response, ensure_ascii=False)
        return SimpleNamespace(returncode=0, stdout=body, stderr="")

    @property
    def action_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call[1:2] != ["channels"]]


@pytest.fixture()
def backend_factory(tmp_path_factory):
    stub = tmp_path_factory.mktemp("agent-reach") / "agent-reach"
    stub.write_text("#!/usr/bin/env python3\n")
    stub.chmod(0o755)

    def make(action_response):
        runner = Runner(action_response)
        return reach.AgentReachBackend(str(stub), runner=runner), runner

    return make


def read(backend, max_items=None):
    return backend.execute("v2ex", "read", {"target": V2EX_URL}, max_items=max_items)


# ── depth: the body is the artifact ───────────────────────────────────────


def test_body_read_preserves_text_past_the_old_snippet_bound(backend_factory):
    body = "".join(f"reply line {index:04d}: some reasoning about the topic\n" for index in range(400))
    body = body[:11_500] + "\nTAIL-MARKER"
    assert len(body) > reach.MAX_TEXT_CHARS * 2

    backend, _ = backend_factory(envelope("v2ex", "read", items=[item(body)]))
    result = read(backend)

    assert result.ok is True
    forwarded = result.items[0]
    assert len(forwarded["text"]) == len(body)
    assert forwarded["text"] == body
    assert forwarded["text"].endswith("TAIL-MARKER")
    assert forwarded["text_truncated"] is False
    assert forwarded["body"] == {
        "upstream_chars": len(body),
        "returned_chars": len(body),
        "local_truncated": False,
        "upstream_truncated": None,
        "upstream_complete": None,
    }


def test_body_read_preserves_multibyte_text_without_slicing_bytes(backend_factory):
    body = "".join(f"第{index}楼：这里是一段中文回复，带有表情🙂和标点。" for index in range(300))
    body = body + "\n最后一行"
    encoded_len = len(body.encode("utf-8"))
    assert len(body) > reach.MAX_TEXT_CHARS
    assert encoded_len > len(body)  # multibyte: a byte-based slice would corrupt it

    backend, _ = backend_factory(envelope("v2ex", "read", items=[item(body)]))
    result = read(backend)

    forwarded = result.items[0]
    assert forwarded["text"] == body
    assert forwarded["text"].encode("utf-8") == body.encode("utf-8")
    assert "\ufffd" not in forwarded["text"]
    assert forwarded["body"]["upstream_chars"] == len(body)
    assert forwarded["body"]["returned_chars"] == len(body)
    assert forwarded["body"]["local_truncated"] is False


def test_body_budget_cuts_locally_and_withholds_what_it_cannot_carry(backend_factory):
    budget = reach.MAX_TOTAL_BODY_CHARS
    first = "a" * (budget - 100)
    second = "b" * 5_000
    third = "c" * 5_000
    items = [item(first, title="one"), item(second, title="two"), item(third, title="three")]

    backend, _ = backend_factory(envelope("v2ex", "read", items=items))
    result = read(backend)

    assert result.ok is True
    assert len(result.items) == 2
    one, two = result.items
    assert one["text"] == first
    assert one["body"]["returned_chars"] == budget - 100
    assert one["body"]["local_truncated"] is False
    # The second body is cut at the shared budget, not at a 4000-char bound.
    assert len(two["text"]) == 100
    assert two["text"] == second[:100]
    assert two["body"] == {
        "upstream_chars": 5_000,
        "returned_chars": 100,
        "local_truncated": True,
        "upstream_truncated": None,
        "upstream_complete": None,
    }
    assert two["text_truncated"] is True
    # The third item is withheld rather than forwarded as an empty read.
    assert any("body budget" in line for line in result.limitations)
    assert any("were withheld because the shared" in line for line in result.limitations)
    assert json.dumps(result.to_dict(), ensure_ascii=False)  # serialisable


def test_combined_serialised_body_stays_inside_the_capture_cap(backend_factory):
    # Worst case for the JSON we emit: ensure_ascii=True turns a non-BMP
    # codepoint into a surrogate-pair escape (12 bytes), which is worse than a
    # control character's 6-byte \u0000 and a plain 4-byte UTF-8 codepoint.
    assert reach.MAX_TOTAL_BODY_CHARS * 12 <= reach.MAX_OUTPUT_BYTES
    blob = "\U0001F642" * (reach.MAX_TOTAL_BODY_CHARS + 5_000)
    items = [item(blob, title=f"blob {index}") for index in range(3)]
    backend, _ = backend_factory(envelope("v2ex", "read", items=items))
    result = read(backend)

    assert result.ok is True
    forwarded = sum(len(row["text"]) for row in result.items)
    assert forwarded == reach.MAX_TOTAL_BODY_CHARS
    assert result.items[-1]["body"]["local_truncated"] is True
    assert sum(row["body"]["returned_chars"] for row in result.items) == reach.MAX_TOTAL_BODY_CHARS
    payload = result.to_dict()
    for wire in (
        json.dumps(payload, ensure_ascii=True),
        json.dumps(payload, indent=2, ensure_ascii=True),
        json.dumps(payload, ensure_ascii=False),
    ):
        assert len(wire.encode("utf-8")) <= reach.MAX_OUTPUT_BYTES


def test_fifty_items_with_large_metadata_stay_inside_the_capture_cap(backend_factory):
    """The default item budget is 50; metadata bounds must not blow the cap."""
    per_body = reach.MAX_TOTAL_BODY_CHARS // 50
    items = [
        item(
            "\U0001F642" * per_body,
            title="t" * reach.MAX_VALUE_CHARS,
            author="a" * reach.MAX_VALUE_CHARS,
            published_at="p" * reach.MAX_VALUE_CHARS,
            url="https://example.com/" + "u" * (reach.MAX_URL_CHARS - 20),
            raw={"blob": "r" * 1_500},
        )
        for _ in range(50)
    ]
    backend, _ = backend_factory(envelope("v2ex", "read", items=items))
    result = read(backend)

    assert result.ok is True
    assert len(result.items) == 50
    assert sum(row["body"]["returned_chars"] for row in result.items) == reach.MAX_TOTAL_BODY_CHARS
    assert all(row["raw"] == {"blob": "r" * 1_500} for row in result.items)
    payload = result.to_dict()
    for wire in (
        json.dumps(payload, ensure_ascii=True),
        json.dumps(payload, indent=2, ensure_ascii=True),
        json.dumps(payload, ensure_ascii=False),
    ):
        assert len(wire.encode("utf-8")) <= reach.MAX_OUTPUT_BYTES


# ── discovery keeps its snippet bound ─────────────────────────────────────


def test_discovery_snippets_keep_the_snippet_bound(backend_factory):
    body = "s" * 9_000
    backend, _ = backend_factory(envelope("v2ex", "hot", items=[item(body)]))
    result = backend.execute("v2ex", "hot", {}, max_items=3)

    forwarded = result.items[0]
    assert len(forwarded["text"]) == reach.MAX_TEXT_CHARS
    assert forwarded["text_truncated"] is True
    assert "body" not in forwarded
    assert set(forwarded) == {
        "title",
        "url",
        "url_rejected",
        "author",
        "published_at",
        "text",
        "text_truncated",
        "raw",
    }


# ── shell classification sees the whole body ──────────────────────────────


def test_shell_marker_in_a_short_prefix_does_not_condemn_a_real_document(backend_factory):
    body = "Page not found\n" + "Real article prose about HTTP status codes and debugging. " * 120
    assert len(body) > reach.MAX_TEXT_CHARS
    # Baseline: the same text cut to a short prefix *is* a missing-page shell.
    assert classify_page_shell(body[:300]) == "missing_page"
    assert classify_page_shell(body) is None

    backend, _ = backend_factory(envelope("v2ex", "read", items=[item(body)]))
    result = read(backend)

    assert result.ok is True
    assert result.items[0]["text"] == body


def test_a_real_short_shell_is_still_withheld_on_the_body_path(backend_factory):
    shell = "B O S S\n正在加载中...\n© copyright BOSS直聘 京ICP备14013441号-5"
    assert classify_page_shell(shell) == "blocked"
    backend, _ = backend_factory(envelope("v2ex", "read", items=[item(shell, title="请稍候")]))
    result = read(backend)

    assert result.ok is False
    assert result.error["code"] == "content_unusable"
    assert result.error["reasons"] == ["blocked"]
    assert result.items == ()


# ── malformed upstream shapes ─────────────────────────────────────────────


def test_malformed_item_types_are_tolerated_and_bounded():
    raw_items = [
        None,
        7,
        "just a string",
        {},
        {"text": None},
        {"text": 5},
        {"text": ["a", "b"]},
        {"text": {"a": 1}},
        {"text": "ok body", "url": 5, "title": ["not", "a", "string"]},
    ]
    items, dropped_raw, rejected_urls, withheld, clipped = reach._normalize_items(
        raw_items, 5, body_read=True
    )

    assert len(items) == 1
    assert items[0]["text"] == "ok body"
    assert items[0]["url"] is None
    assert items[0]["url_rejected"] is True
    assert items[0]["title"] is None
    assert items[0]["body"]["upstream_chars"] == 7
    assert rejected_urls == 1
    assert withheld.count("empty_body") == 5
    assert dropped_raw is False
    assert clipped == 0
    assert json.dumps(items)


def test_malformed_entries_next_to_a_valid_body_still_forward_that_body(backend_factory):
    items = [None, {"text": 12}, item("x" * 6_000), {"text": ""}]
    backend, _ = backend_factory(envelope("v2ex", "read", items=items))
    result = read(backend)

    assert result.ok is True
    assert len(result.items) == 1
    assert len(result.items[0]["text"]) == 6_000
    assert any("empty_body" in line for line in result.limitations)


# ── upstream continuation / truncation truth ──────────────────────────────


def test_absent_upstream_signals_are_unknown_not_complete(backend_factory):
    backend, _ = backend_factory(envelope("v2ex", "read", items=[item("x" * 5_000)]))
    result = read(backend)

    assert result.ok is True
    assert result.upstream == {
        "truncated": None,
        "continuation": {"state": "unknown", "source": "absent", "next_offset": None},
        "note": reach.UPSTREAM_SIGNAL_NOTE,
    }
    # Full local return is not a completeness proof.
    assert result.items[0]["body"]["local_truncated"] is False
    assert result.items[0]["body"]["upstream_complete"] is None
    assert result.items[0]["body"]["upstream_truncated"] is None


def test_explicit_envelope_truncated_bool_is_echoed_but_never_followed(backend_factory):
    payload = envelope("v2ex", "read", items=[item("x" * 5_000)], truncated=True)
    backend, runner = backend_factory(payload)
    result = read(backend)

    assert result.ok is True
    assert result.upstream["truncated"] is True
    assert result.upstream["continuation"] == {
        "state": "unknown",
        "source": "absent",
        "next_offset": None,
    }
    # The flag reaches the item metadata too, and nothing was fetched twice.
    assert result.items[0]["body"]["upstream_truncated"] is True
    assert result.items[0]["body"]["upstream_complete"] is None
    assert len(runner.action_calls) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"pagination": {"more": False}},
        {"pagination": {"more": False, "next_offset": 0}},
        {"pagination": {"more": True, "next_offset": 25}},
        {"pagination": {"next_offset": None}},
        {"pagination": "not-a-mapping"},
        {"meta": {"elapsed_ms": 1, "attempts": [], "pagination": {"more": True, "next_offset": "SECRET"}}},
    ],
)
def test_pagination_shaped_fields_never_claim_exhaustion(backend_factory, extra):
    """The pinned envelope has no cursor: guessing one could fake "exhausted"."""
    backend, runner = backend_factory(envelope("v2ex", "read", items=[item("x" * 4_000)], **extra))
    result = read(backend)

    assert result.ok is True
    assert result.upstream["truncated"] is None
    assert result.upstream["continuation"] == {
        "state": "unknown",
        "source": "absent",
        "next_offset": None,
    }
    assert result.items[0]["body"]["upstream_complete"] is None
    assert len(runner.action_calls) == 1


def test_upstream_signals_are_absent_on_discovery(backend_factory):
    backend, _ = backend_factory(envelope("v2ex", "hot", items=[item("snippet")]))
    result = backend.execute("v2ex", "hot", {})
    assert result.upstream is None
