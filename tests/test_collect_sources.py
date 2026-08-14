import csv
import http.client
import io
import pathlib
import sys
import unittest
from unittest import mock


SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from collect_sources import (  # noqa: E402
    MAX_BYTES,
    FetchError,
    FetchResult,
    SchemaError,
    SafeRedirectHandler,
    collect_requested,
    decode_utf8,
    fetch_url,
    main,
    parse_rssapp_csv,
    parse_trump_rss,
    parse_vix_csv,
)


NOW = "2026-08-15T04:42:00Z"
RSS_HEADER = (
    "ID,Feed URL,Feed Link,Feed Title,Feed Description,Feed Icon,Title,Link,"
    "Description,Image,Plain Description,Author,Date"
)
RSS_ROW = (
    '1,https://feed.example,https://feed.example,Example,,,Headline,https://article.example,'
    '"<p>fallback <b>summary</b></p>",,,Alice,"Fri, 15 Aug 2026 04:00:00 +0000"'
)
TRUMP_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><item><title>A tariff statement</title>
<link>https://trumpstruth.org/post/1</link><guid>post-1</guid>
<description><![CDATA[<p>I will raise the tariff.</p>]]></description>
<pubDate>Fri, 15 Aug 2026 04:00:00 +0000</pubDate></item></channel></rss>"""
TRUMP_REPOST_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:truth="https://trumpstruth.org/ns" version="2.0"><channel><item>
<title>RT @marketwatch: Rate decision is due.</title>
<link>https://trumpstruth.org/statuses/2</link><guid>post-2</guid>
<description><![CDATA[<p>RT: https://truthsocial.com/@marketwatch/123</p>]]></description>
<pubDate>Fri, 15 Aug 2026 04:00:00 +0000</pubDate>
<truth:originalUrl>https://truthsocial.com/@marketwatch/123</truth:originalUrl>
</item></channel></rss>"""
TRUMP_DIRECT_URL_XML = TRUMP_XML.replace(
    "</pubDate>", "</pubDate><originalUrl>https://truthsocial.com/@realDonaldTrump/123</originalUrl>", 1,
)
TRUMP_NON_TRUMP_URL_XML = TRUMP_XML.replace(
    "</pubDate>", "</pubDate><originalUrl>https://truthsocial.com/@marketwatch/123</originalUrl>", 1,
)
TRUMP_EVIL_URL_XML = TRUMP_XML.replace(
    "</pubDate>", "</pubDate><originalUrl>https://evil.example/@marketwatch/123</originalUrl>", 1,
)
VIX_CSV_WITHOUT_TIME = "Symbol,Value\nVIX9D,11.00\nVIX,14.38\nVIX3M,18.50\nVIX6M,20.84\n"
VIX_CSV_SHEET = "상품명,,가격,변동\nVIX 9일,VIX9D,10.96,-3.61%\nVIX지수,VIX,14.32,-2.12%\nVIX 3개월 선물,VIX3M,18.47,-0.75%\nVIX 6개월 선물,VIX6M,20.81,-0.57%\n"


class _Response:
    def __init__(self, body, url="https://rss.app/feeds/test.csv", content_type="text/csv"):
        self._body = body
        self._read = False
        self.url = url
        self.headers = {"Content-Type": content_type}

    def read(self, size=-1):
        if self._read:
            return b""
        self._read = True
        return self._body

    def geturl(self):
        return self.url

    def close(self):
        return None


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class _ReadErrorResponse(_Response):
    def __init__(self, error):
        super().__init__(b"")
        self.error = error

    def read(self, size=-1):
        raise self.error


class _SourceOpener:
    def open(self, request, timeout):
        if "rss.app" in request.full_url:
            return _ReadErrorResponse(ConnectionResetError("connection reset"))
        return _Response(VIX_CSV_WITHOUT_TIME.encode("utf-8"), url=request.full_url)


class CollectorParserTests(unittest.TestCase):
    def test_rssapp_requires_exact_header(self):
        with self.assertRaises(SchemaError):
            parse_rssapp_csv("Title,Link\nA,https://example.com", "reuters", NOW)

    def test_rssapp_bom_and_html_fallback_are_normalized(self):
        items = parse_rssapp_csv("\ufeff" + RSS_HEADER + "\n" + RSS_ROW, "reuters", NOW)
        self.assertEqual(items[0]["summary"], "fallback summary")
        self.assertEqual(items[0]["observed_at"], NOW)
        self.assertEqual(items[0]["url"], "https://article.example")

    def test_rssapp_leaves_event_cluster_uncomputed_for_distinct_feed_items(self):
        second_row = (
            RSS_ROW.replace("1,", "2,", 1)
            .replace("Headline", "Another headline")
            .replace("https://article.example", "https://article-2.example")
        )
        items = parse_rssapp_csv(
            RSS_HEADER + "\n" + RSS_ROW + "\n" + second_row,
            "reuters",
            NOW,
        )
        self.assertEqual([item["source_cluster"] for item in items], [None, None])

    def test_rssapp_rejects_malformed_row(self):
        with self.assertRaises(SchemaError):
            parse_rssapp_csv(RSS_HEADER + "\n1,https://feed.example\n", "reuters", NOW)

    def test_rssapp_rejects_non_http_or_hostless_item_urls(self):
        for invalid_url in ("javascript:alert(1)", "https:/missing-host"):
            with self.subTest(invalid_url=invalid_url):
                payload = (RSS_HEADER + "\n" + RSS_ROW).replace("https://article.example", invalid_url)
                with self.assertRaises(SchemaError):
                    parse_rssapp_csv(payload, "reuters", NOW)

    def test_rssapp_normalizes_publication_time_and_freshness(self):
        items = parse_rssapp_csv(RSS_HEADER + "\n" + RSS_ROW, "reuters", NOW)
        self.assertEqual(items[0]["published_at_raw"], "Fri, 15 Aug 2026 04:00:00 +0000")
        self.assertEqual(items[0]["published_at"], "2026-08-15T04:00:00Z")
        self.assertEqual(items[0]["freshness"], "fresh")

    def test_rssapp_rejects_invalid_publication_time(self):
        payload = (RSS_HEADER + "\n" + RSS_ROW).replace("Fri, 15 Aug 2026 04:00:00 +0000", "not-a-date")
        with self.assertRaises(SchemaError):
            parse_rssapp_csv(payload, "reuters", NOW)

    def test_rssapp_classifies_recent_stale_and_future_publication_times(self):
        for raw_time, expected in (
            ("2026-08-14T12:42:00Z", "recent"),
            ("2026-08-14T03:00:00Z", "stale"),
            ("2026-08-15T05:00:00Z", "future"),
        ):
            with self.subTest(raw_time=raw_time):
                payload = (RSS_HEADER + "\n" + RSS_ROW).replace("Fri, 15 Aug 2026 04:00:00 +0000", raw_time)
                self.assertEqual(parse_rssapp_csv(payload, "reuters", NOW)[0]["freshness"], expected)

    def test_trump_statement_is_retained_as_observed(self):
        items = parse_trump_rss(TRUMP_XML, NOW)
        self.assertEqual(items[0]["verification_status"], "statement_observed")
        self.assertEqual(items[0]["summary"], "I will raise the tariff.")
        self.assertEqual(items[0]["statement_kind"], "original")
        self.assertIsNone(items[0]["original_author"])
        self.assertEqual(items[0]["published_at"], "2026-08-15T04:00:00Z")
        self.assertEqual(items[0]["freshness"], "fresh")

    def test_trump_rejects_malformed_xml(self):
        with self.assertRaises(SchemaError):
            parse_trump_rss("<rss><channel><item></rss>", NOW)

    def test_trump_rejects_invalid_publication_time(self):
        with self.assertRaises(SchemaError):
            parse_trump_rss(TRUMP_XML.replace("Fri, 15 Aug 2026 04:00:00 +0000", "not-a-date"), NOW)

    def test_trump_rejects_dtd_and_entity_payloads_before_xml_parse(self):
        for declaration in ("<!DOCTYPE rss [<!ENTITY x 'expanded'>]>", "<!dOcTyPe rss [<!eNtItY x 'expanded'>]>"):
            payload = TRUMP_XML.replace("?>", "?>\n" + declaration, 1).replace("A tariff statement", "&x;")
            with self.subTest(declaration=declaration):
                with self.assertRaises(SchemaError):
                    parse_trump_rss(payload, NOW)

    def test_trump_rejects_non_http_or_hostless_item_urls(self):
        for invalid_url in ("javascript:alert(1)", "https:/missing-host"):
            with self.subTest(invalid_url=invalid_url):
                with self.assertRaises(SchemaError):
                    parse_trump_rss(TRUMP_XML.replace("https://trumpstruth.org/post/1", invalid_url), NOW)

    def test_trump_repost_uses_only_explicit_author_and_origin_url(self):
        item = parse_trump_rss(TRUMP_REPOST_XML, NOW)[0]
        self.assertEqual(item["statement_kind"], "repost")
        self.assertEqual(item["original_author"], "marketwatch")
        self.assertEqual(item["original_url"], "https://truthsocial.com/@marketwatch/123")

    def test_trump_rt_author_wins_over_a_trump_wrapper_url(self):
        item = parse_trump_rss(TRUMP_REPOST_XML.replace(
            "https://truthsocial.com/@marketwatch/123", "https://truthsocial.com/@realDonaldTrump/123",
        ), NOW)[0]
        self.assertEqual(item["statement_kind"], "repost")
        self.assertEqual(item["original_author"], "marketwatch")
        self.assertEqual(item["truth_social_url"], "https://truthsocial.com/@realDonaldTrump/123")
        self.assertIsNone(item["original_url"])

    def test_trump_non_trump_truth_url_without_rt_is_a_repost(self):
        item = parse_trump_rss(TRUMP_NON_TRUMP_URL_XML, NOW)[0]
        self.assertEqual(item["statement_kind"], "repost")
        self.assertEqual(item["original_author"], "marketwatch")
        self.assertEqual(item["original_url"], "https://truthsocial.com/@marketwatch/123")

    def test_trump_direct_truth_url_remains_original(self):
        item = parse_trump_rss(TRUMP_DIRECT_URL_XML, NOW)[0]
        self.assertEqual(item["statement_kind"], "original")
        self.assertIsNone(item["original_author"])
        self.assertIsNone(item["original_url"])
        self.assertEqual(item["truth_social_url"], "https://truthsocial.com/@realDonaldTrump/123")

    def test_trump_arbitrary_host_never_yields_an_original_author(self):
        item = parse_trump_rss(TRUMP_EVIL_URL_XML, NOW)[0]
        self.assertEqual(item["statement_kind"], "original")
        self.assertIsNone(item["original_author"])
        self.assertIsNone(item["original_url"])
        self.assertEqual(item["truth_social_url"], "https://evil.example/@marketwatch/123")

    def test_vix_missing_source_time_is_explicit(self):
        items = parse_vix_csv(VIX_CSV_WITHOUT_TIME, NOW)
        self.assertIsNone(items[0]["published_at"])
        self.assertEqual(items[0]["observed_at"], NOW)
        self.assertEqual([item["symbol"] for item in items], ["VIX9D", "VIX", "VIX3M", "VIX6M"])
        self.assertTrue(all(item["freshness"] == "unknown" for item in items))

    def test_vix_rejects_missing_required_symbol(self):
        with self.assertRaises(SchemaError):
            parse_vix_csv("Symbol,Value\nVIX9D,11\nVIX,14\nVIX3M,18\n", NOW)

    def test_vix_parses_the_registered_public_sheet_layout(self):
        items = parse_vix_csv(VIX_CSV_SHEET, NOW)
        self.assertEqual([item["value"] for item in items], [10.96, 14.32, 18.47, 20.81])
        self.assertTrue(all(item["source_time_available"] is False for item in items))

    def test_vix_rejects_non_finite_values(self):
        for invalid_value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(invalid_value=invalid_value):
                payload = VIX_CSV_WITHOUT_TIME.replace("VIX,14.38", "VIX," + invalid_value)
                with self.assertRaises(SchemaError):
                    parse_vix_csv(payload, NOW)


class HttpBoundaryTests(unittest.TestCase):
    def test_utf8_bom_decodes_and_invalid_utf8_is_rejected(self):
        self.assertEqual(decode_utf8(b"\xef\xbb\xbfhello"), "hello")
        with self.assertRaises(FetchError):
            decode_utf8(b"\xff")

    def test_fetch_rejects_non_https_before_request(self):
        with self.assertRaises(FetchError):
            fetch_url("http://rss.app/feeds/test.csv")

    def test_fetch_rejects_response_larger_than_five_mib(self):
        response = _Response(b"x" * (MAX_BYTES + 1))
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            with self.assertRaises(FetchError):
                fetch_url("https://rss.app/feeds/test.csv")

    def test_fetch_rejects_unexpected_content_type(self):
        response = _Response(b"{}", content_type="application/json")
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            with self.assertRaises(FetchError):
                fetch_url("https://rss.app/feeds/test.csv")

    def test_fetch_accepts_csv_served_as_plain_text(self):
        response = _Response(b"a,b\n", content_type="text/plain")
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            result = fetch_url("https://rss.app/feeds/test.csv")
        self.assertEqual(result.text, "a,b\n")

    def test_redirect_to_unapproved_host_is_rejected(self):
        handler = SafeRedirectHandler({"rss.app"})
        request = __import__("urllib.request", fromlist=["Request"]).Request("https://rss.app/a")
        with self.assertRaises(FetchError):
            handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://evil.example/a")

    def test_fetch_accepts_registered_google_sheets_download_host(self):
        response = _Response(
            b"Symbol,Value\nVIX9D,11\n",
            url="https://doc-04-1s-sheets.googleusercontent.com/export/file.csv",
        )
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            result = fetch_url("https://docs.google.com/spreadsheets/d/test/export?format=csv")
        self.assertEqual(result.final_url, "https://doc-04-1s-sheets.googleusercontent.com/export/file.csv")

    def test_fetch_accepts_safe_google_sheets_download_host_variant(self):
        response = _Response(
            b"Symbol,Value\nVIX9D,11\n",
            url="https://doc-77-preview-s-sheets.googleusercontent.com/export/file.csv",
        )
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            result = fetch_url("https://docs.google.com/spreadsheets/d/test/export?format=csv")
        self.assertEqual(result.final_url, "https://doc-77-preview-s-sheets.googleusercontent.com/export/file.csv")

    def test_fetch_wraps_transport_read_errors(self):
        for error in (ConnectionResetError("connection reset"), http.client.IncompleteRead(b"partial", 4)):
            with self.subTest(error=type(error).__name__):
                with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(_ReadErrorResponse(error))):
                    with self.assertRaises(FetchError):
                        fetch_url("https://rss.app/feeds/test.csv")

    def test_rss_fetch_rejects_redirect_to_another_registered_source_host(self):
        response = _Response(
            b"Symbol,Value\nVIX9D,11\n",
            url="https://docs.google.com/spreadsheets/d/test/export?format=csv",
        )
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_Opener(response)):
            with self.assertRaises(FetchError):
                fetch_url("https://rss.app/feeds/test.csv")


class AggregationTests(unittest.TestCase):
    def test_one_source_failure_is_returned_without_aborting_successes(self):
        def fake_fetch(url, **_kwargs):
            if "rss.app" in url:
                raise FetchError("temporary failure")
            return FetchResult(
                text=VIX_CSV_WITHOUT_TIME,
                final_url="https://docs.google.com/spreadsheets/d/test/export?format=csv",
                content_type="text/csv",
                byte_count=len(VIX_CSV_WITHOUT_TIME),
            )

        envelope = collect_requested(("rss-reuters", "vix"), NOW, fetcher=fake_fetch)
        self.assertEqual(list(envelope["sources"]), ["vix"])
        self.assertIn("rss-reuters", envelope["errors"])
        self.assertEqual(envelope["sources"]["vix"][0]["symbol"], "VIX9D")

    def test_oversized_csv_field_is_isolated_to_its_source(self):
        oversized_field = "x" * (csv.field_size_limit() + 1)
        row = [
            "1", "https://feed.example", "https://feed.example", "Example", "", "", "Headline",
            "https://article.example", oversized_field, "", "", "", "2026-08-15T04:00:00Z",
        ]
        rss_payload = RSS_HEADER + "\n" + ",".join(row) + "\n"

        def fake_fetch(url, **_kwargs):
            payload = rss_payload if "rss.app" in url else VIX_CSV_WITHOUT_TIME
            return FetchResult(payload, url, "text/csv", len(payload))

        envelope = collect_requested(("rss-reuters", "vix"), NOW, fetcher=fake_fetch)
        self.assertEqual(list(envelope["sources"]), ["vix"])
        self.assertIn("rss-reuters", envelope["errors"])

    def test_transport_read_error_is_isolated_to_its_source(self):
        with mock.patch("collect_sources.urllib.request.build_opener", return_value=_SourceOpener()):
            envelope = collect_requested(("rss-reuters", "vix"), NOW)
        self.assertEqual(list(envelope["sources"]), ["vix"])
        self.assertIn("connection reset", envelope["errors"]["rss-reuters"]["error"])

    def test_cli_refuses_non_standard_nan_json_if_an_internal_bug_leaks_one(self):
        envelope = {"fetched_at": NOW, "sources": {"vix": [{"value": float("nan")}]} , "errors": {}}
        with mock.patch("collect_sources.collect_requested", return_value=envelope):
            with self.assertRaises(ValueError):
                main(["--source", "vix"])


if __name__ == "__main__":
    unittest.main()
