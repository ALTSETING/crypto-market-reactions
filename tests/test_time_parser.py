from datetime import timezone
from crawler.parsers.publication_time_parser import parse_publication_time

def test_jsonld_has_priority_and_normalizes_timezone():
    html = '<script type="application/ld+json">{"datePublished":"2024-01-02T10:20:30+02:00"}</script><time datetime="2023-01-01T00:00:00Z">x</time>'
    result = parse_publication_time(html)
    assert result and result.source == "json_ld" and result.published_at.hour == 8 and result.published_at.tzinfo == timezone.utc

def test_article_meta():
    result = parse_publication_time('<meta property="article:published_time" content="2024-01-02T10:00:00Z">')
    assert result and result.source == "meta_tag" and result.confidence == 0.95

def test_html_time_with_offset():
    result = parse_publication_time('<time datetime="2024-01-02T10:00:00-05:00"></time>')
    assert result and result.source == "html_time" and result.published_at.hour == 15

def test_missing_date_and_modified_only():
    assert parse_publication_time("<html><body>none</body></html>") is None
    assert parse_publication_time('<script type="application/ld+json">{"dateModified":"2024-01-02T10:00:00Z"}</script>') is None
