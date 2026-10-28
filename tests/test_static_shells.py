"""Regression tests for two HTML evidence-quality defects.

Both were reproduced on public pages captured once into scratch (the full
captures are not committed; the fixtures below are short, sanitised snippets of
the same markup shape):

1. ``https://sqlite.org/lang_select.html`` — a static reference page was
   rejected as a "client-rendered app shell".  Its prose is repetitive on
   purpose (``SELECT``, ``expr``, ``row``, ``clause`` repeated for pages), so a
   unique-word ratio over the whole document fell to 0.14 — below the old 0.2
   shell threshold — even though the page ships 130 paragraphs.  Vocabulary
   diversity alone cannot separate a SQL reference from a JS shell.
2. ``https://www.sqltutorial.org/playground/`` — a query playground whose body
   is navigation, buttons, an empty editor/result pane and a loader overlay was
   accepted as usable evidence (229 chars: "Switch to dark theme … Enter Query
   … Query Result … Query History … Loading...").  Nothing in that text is
   citable, but no word list condemned it.

The fix is provenance-based, not keyword-based: the shared classifier parses
where the visible text sits in the DOM.  Text inside navigation, forms and
controls is chrome; citable prose lives in paragraph/list/table blocks outside
it.  A repetitive page with prose blocks is a document; a page whose only text
is chrome is an app surface, however its labels happen to be worded.

The markdown tier has no DOM left, so it cannot borrow that provenance.  It
therefore only condemns a body on *positive* evidence — several distinct
control labels plus an unfilled-pane placeholder — never on the absence of
English function words, which would have condemned short Chinese or Spanish
documentation for simply not being English.
"""
from __future__ import annotations

import hermes_trailhead.extract as extract_mod
from hermes_trailhead.extract import (
    _clean_html_text,
    _html_text_provenance,
    _is_interface_shell_text,
    _is_html_shell,
    _is_usable_page_text,
    _plain_text_blocks,
    _readable_page_result,
    _ui_shell_evidence,
    extract_one,
)


# ── 1. Repetitive static documentation is a document, not a shell ───────

_DOC_PARAGRAPH = (
    "The {n} clause of the SELECT statement evaluates the expression for each "
    "row of the result and returns the row when the expression is true, so the "
    "expression is evaluated as a boolean for the row and the row is returned."
)


def _repetitive_doc_html(paragraphs: int = 12) -> str:
    """Sanitised shape of sqlite.org's keyword reference pages.

    Hand-written docs markup: an unclosed ``<li>`` navigation menu, a search
    form, then long runs of narrowly worded prose plus a ``<pre>`` example.
    """
    nav = "".join(
        f'<li><a href="/{slug}.html">{label}</a>' for slug, label in (
            ("index", "Home"), ("docs", "Documentation"), ("download", "Download"),
            ("support", "Support"), ("prosupport", "Purchase"),
        )
    )
    body = "".join(f"<p>{_DOC_PARAGRAPH.format(n=n)}</p>" for n in range(1, paragraphs + 1))
    return (
        "<!DOCTYPE html><html><head><title>SELECT</title></head><body>"
        '<div class="menu"><ul>'
        f"{nav}"
        "</ul></div>"
        '<div class="searchmenu"><form method="GET" action="search">'
        '<select name="s"><option value="d">Search Documentation</option>'
        '<option value="c">Search Changelog</option></select>'
        '<input type="text" name="q" value=""></form></div>'
        "<h1>SELECT</h1>"
        "<p>The SELECT statement is used to retrieve data from one or more "
        "tables or expressions, and the expression is evaluated for each row.</p>"
        f"{body}"
        "<pre>SELECT expr FROM table WHERE expr ORDER BY expr;</pre>"
        "</body></html>"
    )


def test_repetitive_vocabulary_is_not_shell_evidence():
    """The old unique-ratio rule condemned this page; structure must not."""
    page = _repetitive_doc_html()
    cleaned = _clean_html_text(page)
    words = [w for w in cleaned.split() if any(c.isalnum() for c in w)]
    unique_ratio = len({w.lower() for w in words}) / len(words)
    assert unique_ratio < 0.2, "fixture must reproduce the low-diversity false positive"

    assert _is_html_shell(page) is False
    assert _readable_page_result(page) != ""


def test_document_provenance_counts_prose_outside_chrome():
    page = _repetitive_doc_html()
    provenance = _html_text_provenance(page)
    assert provenance is not None
    assert provenance.prose_blocks >= 10
    assert "Search Documentation" in provenance.chrome_text  # form labels are chrome
    assert "clause of the SELECT statement" in provenance.content_text
    assert provenance.is_interface_only() is False


def test_unclosed_list_items_do_not_swallow_the_page():
    """sqlite.org omits ``</li>``; the parser must still leave nav scope."""
    page = (
        "<html><body><ul><li><a href='/a'>Alpha</a>"
        "<li><a href='/b'>Beta</a>"
        "<li><a href='/c'>Gamma</a></ul>"
        "<p>Alpha entries are stored in the table and the table keeps the entry "
        "for each row, with the entry indexed by the row identifier.</p>"
        "<p>Beta entries follow the same rule, and the rule keeps each entry "
        "reachable from the table without scanning the whole table.</p>"
        "<p>Gamma entries use the same storage rule, so the entry survives a "
        "restart and the table remains readable after the restart.</p>"
        "</body></html>"
    )
    provenance = _html_text_provenance(page)
    assert provenance is not None
    assert provenance.prose_blocks == 3
    assert "Beta entries follow the same rule" in provenance.content_text
    assert _is_html_shell(page) is False


# ── 2. Query UI / loading shells are not evidence ───────────────────────


def _query_playground_html() -> str:
    """Sanitised shape of sqltutorial.org/playground: controls, no content."""
    return (
        "<!DOCTYPE html><html><head><title>SQL Playground</title></head>"
        '<body><div class="app">'
        "<header><h1>SQL Playground</h1>"
        '<button id="toggle-theme" type="button">'
        '<span class="sr-only">Switch to dark theme</span>'
        '<span class="sr-only">Switch to light theme</span></button></header>'
        '<nav><a href=""><h2>Database</h2></a>'
        '<div role="tree"><span>Tables</span><span>Views</span></div></nav>'
        '<main><h2>Enter Query</h2><div id="editor"></div>'
        '<div><button id="run" type="button">Run</button>'
        '<button id="format" type="button">Format SQL</button>'
        '<button id="share" type="button">Share</button>'
        '<button id="reset" type="button">Reset DB</button></div>'
        '<h2>Query Result</h2><div id="output"></div></main>'
        '<aside><a href=""><h2>Query History</h2></a><div id="history"></div></aside>'
        '<footer><p>Copyright &copy; 2025 by sqltutorial.org. All Rights Reserved.</p></footer>'
        "</div>"
        '<div class="loader-overlay"><div role="status" aria-label="loading">'
        '<span class="sr-only">Loading...</span></div></div>'
        "</body></html>"
    )


def test_query_playground_shell_is_rejected():
    page = _query_playground_html()
    assert _is_html_shell(page) is True
    assert _readable_page_result(page) == ""
    assert _is_usable_page_text(page) is False

    provenance = _html_text_provenance(page)
    assert provenance is not None
    assert provenance.controls >= 2
    assert provenance.is_interface_only() is True


def test_playground_extraction_reports_blocked_not_ok():
    result = extract_one(
        "https://www.sqltutorial.org/playground/",
        fetch=lambda url, timeout: _query_playground_html(),
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )
    assert result.status == "blocked"
    assert result.content == ""
    assert result.usable is False
    assert "shell" in result.error_message.lower()


# The reader tier that served the live page returns markdown, not markup.  Its
# transport header (title/source URL/cache warning) is scaffolding, not page
# text, so it must neither be counted as content nor rescue the shell.
_PLAYGROUND_MARKDOWN = """Title: SQL Playground
URL Source: https://www.sqltutorial.org/playground/
Published Time: Sun, 05 Oct 2025 05:10:20 GMT
Warning: This is a cached snapshot of the original page, consider retry with caching opt-out.
Markdown Content:
[![Image 1: SQL Playground](logo.svg)](https://www.sqltutorial.org/)Switch to dark theme Switch to light theme## [Database]

Tables

Views

## Enter Query

9

Run Format SQL Share[](https://www.sqltutorial.org/playground/)Reset DB

## Query Result

## [Query History]
Copyright \u00a9 2025 by [sqltutorial.org.](https://www.sqltutorial.org/)All Rights Reserved.

Loading...
"""


def test_playground_markdown_shell_is_rejected():
    assert _is_interface_shell_text(_PLAYGROUND_MARKDOWN) is True
    assert _readable_page_result(_PLAYGROUND_MARKDOWN) == ""


def test_playground_markdown_tier_reports_blocked(monkeypatch):
    """Direct HTML said "interface"; the markdown tier cannot upgrade it."""
    monkeypatch.setattr(extract_mod, "_fetch_jina", lambda url, timeout=30: _PLAYGROUND_MARKDOWN)
    monkeypatch.setattr(
        extract_mod, "_fetch_text_tiered",
        lambda url, timeout: (_ for _ in ()).throw(OSError("http 403")),
    )
    result = extract_one(
        "https://www.sqltutorial.org/playground/",
        extract=lambda url, timeout: (_ for _ in ()).throw(OSError("no web_extract")),
        timeout=1,
    )
    assert result.status == "blocked"
    assert result.content == ""
    assert result.usable is False


def test_markdown_article_about_a_playground_is_not_an_interface():
    markdown = (
        "Title: Why our SQL playground spins forever\n"
        "URL Source: https://example.com/blog/sql-playground-loading\n"
        "Markdown Content:\n"
        "## Why our SQL playground spins forever\n\n"
        "Our playground shows an Enter Query box and a Query Result pane, and "
        "the pane stayed on the Loading... spinner for every user.\n\n"
        "The root cause was a worker that acknowledged the query before the "
        "result row was written, so the client waited on a promise that never "
        "resolved.\n"
    )
    assert _is_interface_shell_text(markdown) is False
    readable = _readable_page_result(markdown)
    assert "Loading..." in readable
    assert _is_usable_page_text(readable) is True


# ── 3. Genuine prose that quotes UI/loading wording survives ────────────


def test_article_quoting_loading_and_query_labels_is_still_usable():
    """Loader/query wording is not a shell marker by itself — provenance is."""
    page = (
        "<!DOCTYPE html><html><body>"
        '<nav><a href="/">Home</a><a href="/blog">Blog</a></nav>'
        '<form role="search"><input type="search" name="q">'
        '<button type="submit">Search</button></form>'
        "<article>"
        "<h1>Why our SQL playground shows Loading... forever</h1>"
        "<p>Our playground renders a query editor, a Run button and a Query "
        "Result pane, and the pane stayed on the Loading... spinner for every "
        "user until we fixed the worker handshake.</p>"
        "<p>The root cause was a message queue that acknowledged the job before "
        "the result was written, so the client waited on a promise that never "
        "resolved and the spinner never cleared.</p>"
        "<p>We now wait for the result row before acknowledging, which makes the "
        "Query Result pane paint as soon as the database returns rows.</p>"
        "</article>"
        "</body></html>"
    )
    provenance = _html_text_provenance(page)
    assert provenance is not None and provenance.is_interface_only() is False
    assert _is_html_shell(page) is False
    readable = _readable_page_result(page)
    assert "Loading..." in readable
    assert "message queue" in readable
    assert _is_usable_page_text(readable) is True


def test_short_page_with_controls_and_real_prose_is_not_interface_only():
    """Chrome must dominate before a page is called an interface."""
    page = (
        "<html><body><form><input type='text' name='q'>"
        "<button>Go</button></form>"
        "<p>A short note explaining that the index rebuild keeps every row of "
        "the table reachable after the migration runs on the replica, because "
        "the rebuild copies each entry before it swaps the tree.</p>"
        "<p>The replica replays the same steps, and the entry stays readable "
        "while the tree is swapped, so no reader sees a missing row.</p>"
        "<p>Operators can re-run the rebuild at any time, and the table keeps "
        "serving reads from the old tree until the swap completes.</p>"
        "</body></html>"
    )
    provenance = _html_text_provenance(page)
    assert provenance is not None and provenance.is_interface_only() is False
    assert _is_html_shell(page) is False
    assert _readable_page_result(page) != ""


def test_plain_text_is_never_parsed_as_structure():
    assert _html_text_provenance("Plain text article about SELECT statements.") is None
    assert extract_mod._html_text_provenance("<html><body>" + "word " * 40 + "</body></html>") is not None


# ── 4. Positive UI evidence only: non-English text is never condemned ────


def test_markdown_shell_verdict_needs_controls_and_a_placeholder():
    """Both signals are required — control labels alone are not a verdict."""
    labels, empty = _ui_shell_evidence(_plain_text_blocks(_PLAYGROUND_MARKDOWN))
    assert labels >= 4, "fixture must actually show repeated control labels"
    assert empty is True, "fixture must show the unfilled-pane placeholder"

    without_loader = _PLAYGROUND_MARKDOWN.replace("Loading...", "")
    assert _is_interface_shell_text(without_loader) is False


_ZH_DOC = """Title: 快速开始
URL Source: https://example.com/zh/quickstart
Markdown Content:
## 快速开始

安装依赖：

pip install requests

然后运行下面的命令创建索引，索引会为每一行生成条目，条目写入之后即可查询。

## 常用命令

- 运行 服务
- 保存 配置
- 查询结果 导出

更多内容参见文档。
"""


def test_chinese_short_multiline_document_is_not_an_interface():
    """Han text has no spaces and no English stopwords; it is still prose."""
    assert _is_interface_shell_text(_ZH_DOC) is False
    readable = _readable_page_result(_ZH_DOC)
    assert "快速开始" in readable
    assert _is_usable_page_text(readable) is True


_ES_DOC = """Markdown Content:
## Cómo usar el panel

Ejecuta la consulta en el editor y revisa el resultado antes de compartirlo.

Guarda el informe para reutilizarlo más tarde en el historial del panel.
"""


def test_spanish_short_text_is_not_an_interface():
    """Spanish shares few of the English function words the old rule counted."""
    assert _is_interface_shell_text(_ES_DOC) is False
    readable = _readable_page_result(_ES_DOC)
    assert "Cómo usar el panel" in readable
    assert _is_usable_page_text(readable) is True


def test_code_snippet_vetoes_the_interface_verdict():
    """A shell never renders source code, so code is content evidence."""
    zh_with_code = (
        "Markdown Content:\n## 示例\n\n运行 下面的命令保存 查询结果：\n\n"
        "```python\ndef build(rows):\n    return [row for row in rows if row]\n```\n\n"
        "格式化 之后再次 分享 即可。\n"
    )
    assert extract_mod._is_code_block("def build(rows):") is True
    assert extract_mod._is_code_block("SELECT row FROM t;") is True
    assert extract_mod._is_code_block("Enter Query") is False
    assert _is_interface_shell_text(zh_with_code) is False

    playground_with_example = _PLAYGROUND_MARKDOWN.replace(
        "## Query Result\n",
        "## Query Result\n\nSELECT * FROM users WHERE id = 1;\n",
    )
    assert _is_interface_shell_text(playground_with_example) is False

