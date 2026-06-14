from hermes_reach.router import all_routes, route_for, route_for_ranked


def test_routes_have_required_fields():
    routes = all_routes()
    assert len(routes) >= 6
    for route in routes:
        assert route.key
        assert route.primary
        assert route.rationale
        assert route.evidence_needed
        assert route.competitor_lesson


def test_route_for_browser_login_requires_approval():
    route = route_for("login to a site and fill a form with browser session")
    assert route.key == "interactive-browser"
    assert route.approval_required is True


def test_route_for_known_url_prefers_extract():
    route = route_for("read this known url as markdown")
    assert route.key == "known-url-read"
    assert "web_extract" in route.primary


def test_route_for_ranked_returns_multiple():
    routes = route_for_ranked("search find fetch extract", top=3)
    assert isinstance(routes, list)
    assert len(routes) >= 2
    keys = [r.key for r in routes]
    assert "discovery-search" in keys
    assert "known-url-read" in keys


def test_route_for_ranked_top_limit():
    routes = route_for_ranked("search find fetch extract", top=2)
    assert len(routes) == 2


def test_route_for_ranked_no_match_defaults():
    routes = route_for_ranked("zzzunknownquery", top=3)
    assert len(routes) == 1
    assert routes[0].key == "discovery-search"
