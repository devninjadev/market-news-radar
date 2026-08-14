#!/usr/bin/env python3
"""Collect fixed public market-news sources through a constrained HTTPS boundary."""

import argparse
import csv
import http.client
import html
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from io import StringIO


MAX_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset({
    "text/csv", "text/plain", "application/csv", "text/xml", "application/xml", "application/rss+xml",
})
REDIRECT_HOSTS_BY_ORIGIN = {
    "rss.app": frozenset({"rss.app"}),
    "trumpstruth.org": frozenset({"trumpstruth.org", "www.trumpstruth.org"}),
    "www.trumpstruth.org": frozenset({"trumpstruth.org", "www.trumpstruth.org"}),
    "docs.google.com": frozenset({"docs.google.com"}),
}
VIX_DOWNLOAD_HOST = re.compile(r"^doc-[a-z0-9][a-z0-9-]*s-sheets\.googleusercontent\.com$", re.ASCII)
RSSAPP_HEADER = (
    "ID", "Feed URL", "Feed Link", "Feed Title", "Feed Description",
    "Feed Icon", "Title", "Link", "Description", "Image",
    "Plain Description", "Author", "Date",
)
VIX_SYMBOLS = ("VIX9D", "VIX", "VIX3M", "VIX6M")

RSS_REUTERS_URL = "https://rss.app/feeds/_fSiPEQ8FZXQdj4js.csv"
RSS_DOW_JONES_URL = "https://rss.app/feeds/_m6HwVpkVbkV6H1V6.csv"
RSS_BLOOMBERG_URL = "https://rss.app/feeds/_t07deORnyZW90CjC.csv"
TRUMP_RSS_URL = "https://trumpstruth.org/feed"
VIX_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/15xqjZq8di2UqrePpYR_p72j5FCj-WTEDC4rdjZSqc_w/"
    "export?format=csv&gid=0"
)


class FetchError(RuntimeError):
    """A network boundary rejected a request or response."""


class SchemaError(ValueError):
    """A source did not match its published machine-readable contract."""


@dataclass(frozen=True)
class FetchResult:
    text: str
    final_url: str
    content_type: str
    byte_count: int


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")


def html_to_text(value):
    parser = _TextExtractor()
    parser.feed(value or "")
    parser.close()
    return " ".join(html.unescape("".join(parser.parts)).split())


def decode_utf8(payload):
    try:
        return payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise FetchError("response is not valid UTF-8") from exc


def _hostname(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower()


def _validate_https_url(url, allowed_hosts):
    scheme, host = _hostname(url)
    if scheme != "https":
        raise FetchError("only HTTPS URLs are allowed")
    is_vix_download = "docs.google.com" in allowed_hosts and bool(VIX_DOWNLOAD_HOST.fullmatch(host))
    if not host or (host not in allowed_hosts and not is_vix_download):
        raise FetchError("URL host is not allowlisted")


def _allowed_hosts_for_url(url):
    scheme, host = _hostname(url)
    if scheme != "https" or host not in REDIRECT_HOSTS_BY_ORIGIN:
        raise FetchError("URL host is not allowlisted")
    return REDIRECT_HOSTS_BY_ORIGIN[host]


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate every redirect target before urllib follows it."""

    def __init__(self, allowed_hosts):
        super().__init__()
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_https_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _content_type(response):
    headers = response.headers
    if hasattr(headers, "get_content_type"):
        return headers.get_content_type()
    value = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
    return value.split(";", 1)[0].strip().lower()


def _read_limited(response, max_bytes):
    chunks = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("response exceeds maximum size")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(url, *, timeout=15.0, max_bytes=MAX_BYTES):
    """Fetch one allowlisted HTTPS URL, including only safe redirects."""
    source_hosts = _allowed_hosts_for_url(url)
    _validate_https_url(url, source_hosts)
    opener = urllib.request.build_opener(SafeRedirectHandler(source_hosts))
    request = urllib.request.Request(url, headers={"User-Agent": "market-news-radar/0.1"})
    try:
        response = opener.open(request, timeout=timeout)
        try:
            final_url = response.geturl()
            _validate_https_url(final_url, source_hosts)
            content_type = _content_type(response)
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise FetchError("unexpected response content type: " + (content_type or "missing"))
            body = _read_limited(response, max_bytes)
            return FetchResult(
                text=decode_utf8(body),
                final_url=final_url,
                content_type=content_type,
                byte_count=len(body),
            )
        finally:
            response.close()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise FetchError(str(exc)) from exc


def _base_item(**values):
    return {
        "entities": [],
        "tickers": [],
        "themes": [],
        "freshness": "unknown",
        "source_cluster": values.get("url") or values.get("id"),
        **values,
    }


def _validate_item_url(value, label):
    url = (value or "").strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SchemaError(label + " must be an HTTP(S) URL with a host")
    return url


def _parse_timestamp(value, label):
    raw = (value or "").strip()
    if not raw:
        raise SchemaError(label + " is missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError) as exc:
            raise SchemaError(label + " is invalid") from exc
    if parsed.tzinfo is None:
        raise SchemaError(label + " must include a timezone")
    return parsed.astimezone(timezone.utc)


def _publication_fields(raw_value, fetched_at):
    raw = (raw_value or "").strip()
    if not raw:
        return {"published_at": None, "published_at_raw": None, "freshness": "unknown"}
    published = _parse_timestamp(raw, "published_at")
    observed = _parse_timestamp(fetched_at, "fetched_at")
    age_seconds = (observed - published).total_seconds()
    if age_seconds < 0:
        freshness = "future"
    elif age_seconds <= 6 * 60 * 60:
        freshness = "fresh"
    elif age_seconds <= 24 * 60 * 60:
        freshness = "recent"
    else:
        freshness = "stale"
    return {
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "published_at_raw": raw,
        "freshness": freshness,
    }


def parse_rssapp_csv(text, source_key, fetched_at):
    reader = csv.reader(StringIO(text.lstrip("\ufeff")))
    try:
        header = tuple(next(reader))
    except StopIteration as exc:
        raise SchemaError("RSS.app CSV is empty") from exc
    if header != RSSAPP_HEADER:
        raise SchemaError("RSS.app CSV header does not match expected schema")
    items = []
    for row_number, row in enumerate(reader, start=2):
        if len(row) != len(RSSAPP_HEADER):
            raise SchemaError("RSS.app CSV row %d has %d columns" % (row_number, len(row)))
        values = dict(zip(RSSAPP_HEADER, row))
        if not values["ID"] or not values["Title"] or not values["Link"]:
            raise SchemaError("RSS.app CSV row %d is missing an item identifier, title, or link" % row_number)
        url = _validate_item_url(values["Link"], "RSS.app CSV row %d item URL" % row_number)
        summary = values["Plain Description"].strip() or html_to_text(values["Description"])
        items.append(_base_item(
            id=values["ID"], source_name=source_key, source_type="rssapp_csv",
            title=values["Title"].strip(), summary=summary, url=url,
            observed_at=fetched_at, verification_status="source_claim", source_cluster=None,
            source_feed_url=values["Feed URL"].strip() or None,
            **_publication_fields(values["Date"], fetched_at),
        ))
    return items


def _node_text(item, name):
    for child in item:
        if child.tag.rsplit("}", 1)[-1] == name:
            return (child.text or "").strip()
    return ""


def _truth_author_from_url(url):
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in {"truthsocial.com", "www.truthsocial.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or not parts[0].startswith("@"):
        return None
    return parts[0][1:] or None


RT_AUTHOR = re.compile(r"^\s*RT\s+@(?P<author>[A-Za-z0-9_]+)\b", re.IGNORECASE)


def _trump_statement_metadata(title, description_html, supplied_original_url):
    author_match = RT_AUTHOR.search(title) or RT_AUTHOR.search(html_to_text(description_html))
    truth_social_url = _validate_item_url(supplied_original_url, "Trump archive original URL") if supplied_original_url else None
    url_author = _truth_author_from_url(truth_social_url)
    is_non_trump_url_author = bool(url_author and url_author.lower() != "realdonaldtrump")
    original_author = author_match.group("author") if author_match else (url_author if is_non_trump_url_author else None)
    if original_author or is_non_trump_url_author:
        return {
            "statement_kind": "repost",
            "original_author": original_author,
            "original_url": truth_social_url if url_author == original_author and is_non_trump_url_author else None,
            "truth_social_url": truth_social_url,
            "attribution": "third-party archive of a Trump repost; original author is retained only when explicit",
        }
    return {
        "statement_kind": "original",
        "original_author": None,
        "original_url": None,
        "truth_social_url": truth_social_url,
        "attribution": "third-party archive of a Trump public statement",
    }


def parse_trump_rss(text, fetched_at):
    if re.search(r"<!\s*(doctype|entity)\b", text, flags=re.IGNORECASE):
        raise SchemaError("Trump archive RSS rejects DTD and ENTITY declarations")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SchemaError("Trump archive RSS is malformed XML") from exc
    items = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "item":
            continue
        title, url, guid = _node_text(node, "title"), _node_text(node, "link"), _node_text(node, "guid")
        if not title or not url or not guid:
            raise SchemaError("Trump archive RSS item is missing title, link, or guid")
        url = _validate_item_url(url, "Trump archive item URL")
        description_html = _node_text(node, "description")
        items.append(_base_item(
            id=guid, source_name="trump_truth_archive", source_type="trump_rss",
            title=title, summary=html_to_text(description_html), url=url, observed_at=fetched_at,
            verification_status="statement_observed", source_cluster=guid,
            **_publication_fields(_node_text(node, "pubDate"), fetched_at),
            **_trump_statement_metadata(title, description_html, _node_text(node, "originalUrl")),
        ))
    if not items:
        raise SchemaError("Trump archive RSS contains no items")
    return items


def _normalized_headers(fieldnames):
    return {name.strip().lower(): name for name in (fieldnames or [])}


def parse_vix_csv(text, fetched_at):
    clean_text = text.lstrip("\ufeff")
    raw_rows = list(csv.reader(StringIO(clean_text)))
    if not raw_rows:
        raise SchemaError("VIX CSV is empty")
    rows = {}
    if tuple(raw_rows[0]) == ("상품명", "", "가격", "변동"):
        data_rows = ((number, row, row[1] if len(row) > 1 else "", row[2] if len(row) > 2 else "", None)
                     for number, row in enumerate(raw_rows[1:], start=2))
    else:
        reader = csv.DictReader(StringIO(clean_text))
        headers = _normalized_headers(reader.fieldnames)
        symbol_key = next((headers[key] for key in ("symbol", "ticker", "index") if key in headers), None)
        value_key = next((headers[key] for key in ("value", "last", "price", "close", "latest") if key in headers), None)
        time_key = next((headers[key] for key in ("published_at", "timestamp", "time", "date", "as of") if key in headers), None)
        if not symbol_key or not value_key:
            raise SchemaError("VIX CSV requires symbol and value columns")
        data_rows = ((number, row, row.get(symbol_key), row.get(value_key), row.get(time_key) if time_key else None)
                     for number, row in enumerate(reader, start=2))
    for row_number, row, raw_symbol, raw_value, raw_time in data_rows:
        if not raw_symbol or not raw_value:
            raise SchemaError("VIX CSV row %d is malformed" % row_number)
        symbol = raw_symbol.strip().upper()
        if symbol in VIX_SYMBOLS:
            if symbol in rows:
                raise SchemaError("VIX CSV repeats %s" % symbol)
            try:
                value = float(raw_value.replace(",", "").strip())
            except ValueError as exc:
                raise SchemaError("VIX CSV row %d has a non-numeric value" % row_number) from exc
            if not math.isfinite(value):
                raise SchemaError("VIX CSV row %d has a non-finite value" % row_number)
            rows[symbol] = (value, raw_time.strip() if raw_time else None)
    missing = [symbol for symbol in VIX_SYMBOLS if symbol not in rows]
    if missing:
        raise SchemaError("VIX CSV is missing required symbols: " + ", ".join(missing))
    return [_base_item(
        id="vix:" + symbol, source_name="vix", source_type="vix_csv", title=symbol,
        summary="Public VIX CSV observation", url=VIX_CSV_URL, symbol=symbol,
        value=rows[symbol][0], published_at=rows[symbol][1] or None, observed_at=fetched_at,
        verification_status="source_claim", source_cluster="vix:" + symbol,
        source_time_available=bool(rows[symbol][1]),
    ) for symbol in VIX_SYMBOLS]


SOURCES = {
    "rss-reuters": (RSS_REUTERS_URL, lambda text, fetched_at: parse_rssapp_csv(text, "reuters", fetched_at)),
    "rss-dow-jones": (RSS_DOW_JONES_URL, lambda text, fetched_at: parse_rssapp_csv(text, "dow_jones", fetched_at)),
    "rss-bloomberg": (RSS_BLOOMBERG_URL, lambda text, fetched_at: parse_rssapp_csv(text, "bloomberg", fetched_at)),
    "trump": (TRUMP_RSS_URL, parse_trump_rss),
    "vix": (VIX_CSV_URL, parse_vix_csv),
}


def collect_requested(source_keys, fetched_at, *, fetcher=fetch_url):
    envelope = {"fetched_at": fetched_at, "sources": {}, "errors": {}}
    for source_key in source_keys:
        url, parser = SOURCES[source_key]
        try:
            fetched = fetcher(url)
            items = parser(fetched.text, fetched_at)
            for item in items:
                item["retrieved_from"] = fetched.final_url
                item["response_bytes"] = fetched.byte_count
            envelope["sources"][source_key] = items
        except (FetchError, SchemaError, UnicodeError, ValueError, csv.Error) as exc:
            envelope["errors"][source_key] = {"url": url, "error": str(exc)}
    return envelope


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=("all", *SOURCES), default=[])
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    requested = args.source or ["all"]
    if "all" in requested:
        source_keys = tuple(SOURCES)
    else:
        source_keys = tuple(dict.fromkeys(requested))
    envelope = collect_requested(source_keys, _now_utc())
    print(json.dumps(
        envelope, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True, allow_nan=False,
    ))
    return 0 if envelope["sources"] else 1


if __name__ == "__main__":
    sys.exit(main())
