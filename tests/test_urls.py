"""URL validation tests."""

from url_utils import dedupe_urls, validate_url


def test_valid_https():
    assert validate_url("https://www.intercom.com/careers")
    assert validate_url("http://news.ycombinator.com/item?id=1")


def test_reject_invalid():
    assert not validate_url(None)
    assert not validate_url("")
    assert not validate_url("ftp://files.example.com/x")
    assert not validate_url("https://example.com/fake")
    assert not validate_url("https://localhost/secret")
    assert not validate_url("not a url")
    assert not validate_url("https://has spaces.com")
    assert not validate_url("https://nodot")


def test_dedupe():
    urls = ["https://Acme.IO/careers/", "https://acme.io/careers", "https://example.com/x", "bad"]
    out = dedupe_urls(urls)
    assert len(out) == 1
    assert out[0].lower().startswith("https://acme.io")

from url_utils import sanitize_url, dedupe_urls


def test_sanitize_strips_citation_glue():
    assert sanitize_url("https://news.globenewswire.com/a)[[9") == "https://news.globenewswire.com/a"
    assert "[[" not in (sanitize_url("https://www.intelligentcio.com/path)[[12") or "")


def test_dedupe_cleans_glue():
    urls = dedupe_urls(["https://bullhoundcapital.com/one)[[1", "https://bullhoundcapital.com/one", "https://bullhoundcapital.com/two"])
    assert urls == ["https://bullhoundcapital.com/one", "https://bullhoundcapital.com/two"]
