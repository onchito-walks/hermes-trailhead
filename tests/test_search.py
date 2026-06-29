import json

from hermes_trailhead.cli import main, search_data
from hermes_trailhead.search import execute_search, search_run, _parse_html_search_results


def _json_from_cli(capsys, argv):
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured


def test_search_json_contract_all(capsys):
    rc, data, _ = _json_from_cli(capsys, ["search", "all", "Hermes Agent discussion", "--format", "json"])

    assert rc == 0
    assert set(data) == {"query", "platform", "mode", "paid_api_required", "actions"}
    assert data["platform"] == "all"
    assert data["mode"] == "hermes_trailhead_action_plan"
    assert data["paid_api_required"] is False
    assert len(data["actions"]) == 7
    for action in data["actions"]:
        assert set(action) == {
            "platform",
            "status",
            "query",
            "recommended_tool",
            "direct_url",
            "site_query",
            "frontend_url",
            "approval_required",
            "paid_api_required",
            "evidence_needed",
            "caveat",
        }
        assert action["paid_api_required"] is False
        assert isinstance(action["evidence_needed"], list)


def test_search_help_includes_platform_choices(capsys):
    try:
        main(["search", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "source-family routes" in out
    assert "--execute" in out
    assert "{all,web,x,reddit,tiktok,instagram,youtube,github}" in out


def test_search_reddit_uses_loginless_redlib(capsys):
    rc, data, _ = _json_from_cli(capsys, ["search", "reddit", "Hermes Agent", "--format", "json"])

    assert rc == 0
    action = data["actions"][0]
    assert action["platform"] == "reddit"
    assert "redlib.perennialte.ch" in action["direct_url"]
    assert action["approval_required"] is False
    assert action["paid_api_required"] is False


def test_reddit_backend_filters_non_discussion_noise(monkeypatch, capsys):
    reddit_html = """
<a href="https://www.reddit.com/search?q=VORON+3D+Printer+Stealthchanger+Build">Search</a>
<a href="https://www.reddit.com/r/VORONDesign/comments/abc123/stealthchanger_build/">Thread</a>
<a href="https://www.youtube.com/watch?v=abc123">Noise</a>
"""

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: reddit_html)
    rc, data, _ = _json_from_cli(capsys, ["search", "reddit", "VORON 3D Printer Stealthchanger Build", "--execute", "--limit", "1", "--format", "json"])

    assert rc == 0
    execution = data["executions"][0]
    assert execution["status"] == "ok"
    assert execution["result_count"] == 1
    assert execution["hits"][0]["url"] == "https://www.reddit.com/r/VORONDesign/comments/abc123/stealthchanger_build/"


def test_search_tiktok_marks_gap_not_fake_coverage(capsys):
    rc, data, _ = _json_from_cli(capsys, ["search", "tiktok", "Hermes Agent", "--format", "json"])

    assert rc == 0
    action = data["actions"][0]
    assert action["platform"] == "tiktok"
    assert action["status"] == "gap"
    assert action["approval_required"] is True
    assert "site:tiktok.com" in action["site_query"]


def test_search_python_api_returns_structured_run():
    run = search_data("github", "Hermes Agent")

    assert run.platform == "github"
    assert run.paid_api_required is False
    assert run.actions[0].platform == "github"
    assert run.actions[0].recommended_tool.startswith("GitHub MCP")


def test_search_run_all_never_requires_paid_api_by_default():
    run = search_run("all", "Hermes Agent")

    assert run.paid_api_required is False
    assert all(action.paid_api_required is False for action in run.actions)


def test_execute_search_parses_real_hits_from_fetcher():
    markdown = """
# Results

## [Prusa KB — PLA](https://help.prusa3d.com/article/pla_2062)
PLA is easy to print and low warping.

## [Prusa Forum](https://forum.prusa3d.com/forum/example/)
Forum thread about curling.
"""

    def fake_fetch(url, timeout):
        assert "duckduckgo.com/html" in url
        assert timeout == 20
        return markdown

    executed = execute_search("web", "Prusa XL PLA curling", limit=2, fetch=fake_fetch)

    assert executed.plan.mode == "hermes_trailhead_action_plan"
    assert len(executed.executions) == 1
    execution = executed.executions[0]
    assert execution.status == "ok"
    assert execution.result_count == 2
    assert execution.hits[0].title == "Prusa KB — PLA"
    assert execution.hits[0].url == "https://help.prusa3d.com/article/pla_2062"


def test_execute_search_json_contract_with_monkeypatch(monkeypatch, capsys):
    markdown = """
## [Only Result](https://example.com/result)
Useful snippet.
"""

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: markdown)
    rc, data, _ = _json_from_cli(capsys, ["search", "web", "test query", "--execute", "--limit", "1", "--format", "json"])

    assert rc == 0
    assert set(data) == {"plan", "executions"}
    assert data["plan"]["mode"] == "hermes_trailhead_action_plan"
    assert data["executions"][0]["status"] == "ok"
    assert data["executions"][0]["result_count"] == 1
    assert data["executions"][0]["hits"][0]["url"] == "https://example.com/result"


def test_execute_search_defaults_extract_limit_to_requested_hit_limit(monkeypatch, capsys):
    from hermes_trailhead.extract import ExtractedHit, ExtractionResult

    markdown = """
## [First](https://example.com/1)
## [Second](https://example.com/2)
## [Third](https://example.com/3)
## [Fourth](https://example.com/4)
## [Fifth](https://example.com/5)
"""

    def fake_extract(hits, limit, timeout):
        return [ExtractedHit(title=hit.title, url=hit.url, snippet=hit.snippet, extraction=ExtractionResult(status="ok", content="fake extracted content " * 5, content_length=120)) for hit in hits[:limit]]

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: markdown)
    monkeypatch.setattr("hermes_trailhead.cli.extract_hits", fake_extract)
    rc, data, _ = _json_from_cli(capsys, ["search", "web", "test query", "--execute", "--limit", "5", "--extract", "--format", "json"])

    assert rc == 0
    assert len(data["executions"][0]["extracted"]) == 5


def test_execute_search_honors_explicit_extract_limit(monkeypatch, capsys):
    from hermes_trailhead.extract import ExtractedHit, ExtractionResult

    markdown = """
## [First](https://example.com/1)
## [Second](https://example.com/2)
## [Third](https://example.com/3)
## [Fourth](https://example.com/4)
## [Fifth](https://example.com/5)
"""

    def fake_extract(hits, limit, timeout):
        return [ExtractedHit(title=hit.title, url=hit.url, snippet=hit.snippet, extraction=ExtractionResult(status="ok", content="fake extracted content " * 5, content_length=120)) for hit in hits[:limit]]

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: markdown)
    monkeypatch.setattr("hermes_trailhead.cli.extract_hits", fake_extract)
    rc, data, _ = _json_from_cli(capsys, ["search", "web", "test query", "--execute", "--limit", "5", "--extract", "--extract-limit", "2", "--format", "json"])

    assert rc == 0
    assert len(data["executions"][0]["extracted"]) == 2
    assert [hit["url"] for hit in data["executions"][0]["extracted"]] == ["https://example.com/1", "https://example.com/2"]


def test_execute_search_extracts_all_returned_hits_by_default(monkeypatch, capsys):
    from hermes_trailhead.extract import ExtractedHit, ExtractionResult

    markdown = """
## [First Result](https://example.com/1)
One.
## [Second Result](https://example.com/2)
Two.
## [Third Result](https://example.com/3)
Three.
"""

    def fake_extract(hits, limit, timeout):
        return [ExtractedHit(title=hit.title, url=hit.url, snippet=hit.snippet, extraction=ExtractionResult(status="ok", content="fake extracted content " * 5, content_length=120)) for hit in hits[:limit]]

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: markdown)
    monkeypatch.setattr("hermes_trailhead.cli.extract_hits", fake_extract)
    rc, data, _ = _json_from_cli(capsys, ["search", "web", "test query", "--execute", "--extract", "--score", "--limit", "3", "--format", "json"])

    assert rc == 0
    extracted = data["executions"][0]["extracted"]
    assert len(extracted) == 3
    assert [hit["url"] for hit in extracted] == ["https://example.com/1", "https://example.com/2", "https://example.com/3"]


def test_execute_gap_lane_keeps_discovery_only_caveat(monkeypatch, capsys):
    markdown = """
## [Creator demo](https://www.tiktok.com/@example/video/123)
Public search result only.
"""

    monkeypatch.setattr("hermes_trailhead.search._fetch_text", lambda url, timeout: markdown)
    rc, data, _ = _json_from_cli(capsys, ["search", "tiktok", "Hermes Agent", "--execute", "--limit", "1", "--format", "json"])

    assert rc == 0
    execution = data["executions"][0]
    assert execution["status"] == "ok"
    assert execution["action_status"] == "gap"
    assert execution["approval_required"] is True
    assert execution["evidence_state"] == "discovered_links_only"
    assert "No dedicated TikTok reader" in execution["caveat"]


def test_parse_html_search_results_handles_duckduckgo_lite_redirects():
    html = '''
    <html><body>
      <a href="/l/?uddg=https%3A%2F%2Fgithub.com%2Fonchito-walks%2Fhermes-trailhead">Hermes Trailhead GitHub</a>
      <a href="https://duckduckgo.com/html/">DuckDuckGo</a>
      <a href="https://example.com/post">Example Post</a>
    </body></html>
    '''
    hits = _parse_html_search_results(html, limit=2)
    assert len(hits) == 2
    assert hits[0].url == "https://github.com/onchito-walks/hermes-trailhead"
    assert hits[0].title == "Hermes Trailhead GitHub"
    assert hits[1].url == "https://example.com/post"
