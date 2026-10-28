"""Reader status must never be inferred from a document title or body."""
from hermes_trailhead.extract import _reader_upstream_status


def test_reader_document_title_is_not_transport_status():
    payload = (
        "Title: Target URL returned error 404: Not Found — troubleshooting\n"
        "URL Source: https://example.org/troubleshooting\n"
        "Markdown Content:\n"
        "A technical explanation of how to recover a missing page.\n"
    )
    assert _reader_upstream_status(payload) is None


def test_warning_immediately_after_markdown_boundary_is_document_body():
    payload = (
        "Title: Debugging readers\n"
        "URL Source: https://example.org/troubleshooting\n"
        "Markdown Content:\n"
        "Warning: Target URL returned error 404: Not Found\n"
        "This is the diagnostic text users will encounter.\n"
    )
    assert _reader_upstream_status(payload) is None
