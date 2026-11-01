"""Bounded public feeds. Feed metadata is evidence, never a trading signal."""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from .contracts import IST, UTC, ValidationError, iso

MAX_BYTES = 12 * 1024 * 1024
MAX_ITEMS = 20000
FEEDS = (
    {"id":"nse_announcements", "name":"NSE corporate announcements", "kind":"announcement", "format":"nse_json", "host":"www.nseindia.com", "home":"https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
    {"id":"nse_board", "name":"NSE board meetings", "kind":"board_meeting", "format":"rss", "host":"nsearchives.nseindia.com", "url":"https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml", "home":"https://www.nseindia.com/static/rss-feed"},
    {"id":"et_stocks", "name":"The Economic Times · Stocks", "kind":"news", "format":"rss", "host":"economictimes.indiatimes.com", "url":"https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", "home":"https://economictimes.indiatimes.com/rss.cms"},
)
FEED_BY_ID = {f["id"]: f for f in FEEDS}


def feed_url(feed, now):
    if feed["format"] != "nse_json":
        return feed["url"]
    end = now.astimezone(IST).date()
    return "https://www.nseindia.com/api/corporate-announcements?" + urlencode({
        "index":"equities", "from_date":(end-timedelta(days=6)).strftime("%d-%m-%Y"),
        "to_date":end.strftime("%d-%m-%Y")})


def safe_url(value, hosts):
    if not isinstance(value, str) or len(value) > 3000 or any(ord(c) < 33 for c in value):
        raise ValidationError("Invalid feed/source URL")
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.hostname not in hosts or p.username or p.password or p.port not in (None,443):
            raise ValueError()
    except ValueError as exc:
        raise ValidationError("Source URL must use HTTPS on the source's approved host") from exc
    query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid","gclid")]
    return urlunsplit(("https",p.hostname,p.path or "/",urlencode(query),""))


class FeedRedirect(HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, {self.host})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_feed(url):
    host = urlsplit(url).hostname
    if host not in {f["host"] for f in FEEDS}:
        raise ValidationError("Unknown feed host")
    safe_url(url, {host})
    request = Request(url, headers={"User-Agent":"Oraculum-local-research/0.6 (personal feed reader)",
                                   "Accept":"application/rss+xml, application/xml, application/json", "Accept-Encoding":"identity"})
    with build_opener(FeedRedirect(host)).open(request, timeout=25) as response:
        safe_url(response.geturl(), {host})
        if response.headers.get("Content-Encoding", "identity").lower() not in ("identity", ""):
            raise ValidationError("Unexpected compressed feed response")
        data = response.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValidationError("Empty response or feed exceeds 12 MiB")
    return data


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden-1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value, limit=800):
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value[:30000])
    text = " ".join(unescape("".join(parser.parts)).split())
    return text[:limit]


def published_time(value, *, nse=False):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(text)
        except (ValueError, TypeError, OverflowError):
            stamp = None
    if stamp is None and nse:
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                stamp = datetime.strptime(text, fmt).replace(tzinfo=IST)
                break
            except ValueError:
                pass
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        if not nse:
            return None
        stamp = stamp.replace(tzinfo=IST)
    return iso(stamp.astimezone(UTC))


def category(title, excerpt, kind):
    if kind == "board_meeting":
        return "Board meeting"
    text = (title + " " + excerpt).lower()
    for label, words in (
        ("Results & earnings", ("financial result", "quarterly result", "q1 result", "q2 result", "q3 result", "q4 result", "net profit", "earnings")),
        ("Dividend & capital", ("dividend", "buyback", "buy back", "bonus issue", "stock split", "rights issue", "allotment")),
        ("Governance", ("director", "resignation", "management", "auditor")),
        ("Deals & orders", ("acquisition", "merger", "contract", "order win", "incorporation")),
        ("Regulatory & legal", ("penalty", "litigation", "sebi", "regulatory", "court")),
        ("Meetings & calls", ("board meeting", "investor meet", "conference call", "con. call", "analyst")),
    ):
        if any(word in text for word in words):
            return label
    return "Other"


def item_record(feed, title, excerpt, url, publication, *, key=None, symbol=None, isin=None, company=None):
    title, excerpt = plain(title, 400), plain(excerpt, 400 if feed["kind"] == "news" else 1000)
    if not title:
        raise ValidationError("Item has no title")
    hosts = {"www.nseindia.com", "nsearchives.nseindia.com"} if feed["kind"] != "news" else {feed["host"]}
    url = safe_url(url, hosts)
    return {"feed_id":feed["id"], "source_name":feed["name"], "kind":feed["kind"],
            "title":title, "excerpt":excerpt, "url":url, "publisher_id":str(key or url)[:3000],
            "published_at":published_time(publication, nse=feed["kind"] != "news"),
            "publication_raw":str(publication or "")[:120], "reported_symbol":plain(symbol,50),
            "reported_isin":plain(isin,20), "reported_company":plain(company,200),
            "category":category(title,excerpt,feed["kind"])}


def parse_feed(raw, feed):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValidationError("Invalid feed size")
    records, skipped = [], 0
    if feed["format"] == "nse_json":
        try:
            rows = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValidationError("Invalid NSE announcement JSON") from exc
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            raise ValidationError("Unexpected NSE announcement schema or too many items")
        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise ValidationError("Invalid announcement item")
                publication = row.get("exchdisstime") or row.get("an_dt")
                records.append(item_record(feed, (row.get("sm_name") or row.get("symbol") or "") + " · " + (row.get("desc") or "Announcement"),
                    row.get("attchmntText"), row.get("attchmntFile"), publication,
                    key=row.get("seq_id"), symbol=row.get("symbol"), isin=row.get("sm_isin"), company=row.get("sm_name")))
            except (ValidationError, TypeError):
                skipped += 1
    else:
        # Reject declarations before parsing, including UTF-16 obfuscation.
        if b"\x00" in raw or re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
            raise ValidationError("XML declarations/entities are not allowed")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValidationError("Malformed RSS/Atom feed") from exc
        tag = lambda e:e.tag.rsplit("}",1)[-1]
        if tag(root) == "rss":
            channel = root.find("channel")
            if channel is None:
                raise ValidationError("RSS channel missing")
            rows = channel.findall("item")
        elif tag(root) == "feed":
            rows = [e for e in root if tag(e) == "entry"]
        else:
            raise ValidationError("Response is not RSS or Atom")
        if len(rows) > MAX_ITEMS:
            raise ValidationError("Too many feed items")
        for row in rows:
            values = {tag(e):"".join(e.itertext()) for e in row}
            url = values.get("link", "").strip()
            for e in row:
                if tag(e) == "link" and e.get("rel", "alternate") == "alternate" and e.get("href"):
                    url = e.get("href")
            try:
                records.append(item_record(feed, values.get("title"), values.get("description") or values.get("summary") or values.get("content"),
                    url, values.get("pubDate") or values.get("published") or values.get("date") or values.get("updated"),
                    # Link identity removes tracking duplicates even when GUIDs differ.
                    key=None))
            except ValidationError:
                skipped += 1
    if rows and not records:
        raise ValidationError("All feed items failed validation; cached evidence kept")
    return records, {"supplied":len(rows), "accepted":len(records), "skipped":skipped}


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold().replace("&", " and ")))


class CompanyMatcher:
    """Conservative identity joins; no bare ticker guessing or fuzzy names."""
    version = "company-match-v1"

    def __init__(self, assets):
        self.symbols = {a["symbol"]:a for a in assets}
        self.isins = {}
        names = {}
        for a in assets:
            if a.get("isin"):
                self.isins.setdefault(a["isin"], []).append(a)
            name = normalize(a.get("company_name") or "")
            base = re.sub(r"\s+(limited|ltd)$", "", name)
            for term in {name, base}:
                # Short/common brands remain unmatched without an explicit exchange identifier.
                if len(term) >= 8 and len(term.split()) >= 2:
                    names.setdefault(term, set()).add(a["symbol"])
        self.names = {k:next(iter(v)) for k,v in names.items() if len(v) == 1}
        self.pattern = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in sorted(self.names,key=len,reverse=True)) + r")(?![a-z0-9])") if self.names else None

    def match(self, item):
        if item["kind"] != "news" and (item["reported_symbol"] or item["reported_isin"]):
            symbol, isin = item["reported_symbol"], item["reported_isin"]
            asset = self.symbols.get(symbol)
            if asset and isin and asset.get("isin") != isin:
                return [], "identity_conflict"
            if not asset and isin:
                candidates = self.isins.get(isin, [])
                asset = candidates[0] if len(candidates) == 1 else None
            if asset and isin and asset.get("isin") == isin:
                return [self.reference(asset, "exchange_symbol_and_isin" if asset["symbol"] == symbol else "exchange_isin")], "matched"
            return [], "unverified_exchange_identity"
        # Publisher company mentions are tentative text matches, not issuer confirmations.
        text = normalize(item["title"] + " " + item["excerpt"])
        symbols = {}
        if self.pattern:
            for found in self.pattern.finditer(text):
                symbols[self.names[found.group()]] = "company_name_mention"
        for symbol in re.findall(r"\bNSE\s*:\s*([A-Z0-9][A-Z0-9&_.-]{0,49})\b", item["title"]+" "+item["excerpt"]):
            if symbol in self.symbols:
                symbols[symbol] = "explicit_exchange_ticker"
        return [self.reference(self.symbols[s], method) for s,method in sorted(symbols.items())], "matched" if symbols else "unmatched"

    @staticmethod
    def reference(asset, method):
        return {"symbol":asset["symbol"], "isin":asset.get("isin"), "company_name":asset.get("company_name"), "method":method}
