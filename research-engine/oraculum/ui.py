"""Dependency-free, accessible shell for the local research desk."""
import html
import math
from datetime import date
from urllib.parse import urlencode, urlsplit

from .contracts import IST, timestamp


def esc(value):
    return html.escape(str(value), quote=True)


def date_text(value):
    if not value:
        return "Not available"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(value)


def time_text(value):
    if not value:
        return "Not recorded"
    try:
        return timestamp(value, "time").astimezone(IST).strftime("%d %b %Y, %H:%M IST")
    except (ValueError, TypeError):
        return str(value)


def number(value, places=1, suffix=""):
    try:
        n = float(value)
        return f"{n:,.{places}f}{suffix}" if math.isfinite(n) else "Unavailable"
    except (ValueError, TypeError):
        return "Unavailable"


def money(value):
    return "₹" + number(value, 2) if value is not None else "Unavailable"


def percent(value):
    try:
        n = float(value)
        return f"{n:+.2%}" if math.isfinite(n) else "Unavailable"
    except (ValueError, TypeError):
        return "Unavailable"


def link(path, **query):
    return esc(path + ("?" + urlencode({k: v for k, v in query.items() if v is not None}) if query else ""))


def source_link(uri, label):
    try:
        parts = urlsplit(str(uri))
    except ValueError:
        return esc(label) + " (source URL unavailable)"
    if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
        return f'<a href="{esc(uri)}" rel="noreferrer">{esc(label)} ↗</a>'
    return esc(label) + " (source URL unavailable)"


def badge(label, tone="neutral"):
    tone = tone if tone in ("neutral", "good", "warn", "bad") else "neutral"
    return f'<span class="badge {tone}">{esc(label)}</span>'


def cards(items):
    return '<div class="stats">' + ''.join(
        f'<div class="stat"><span class="eyebrow">{esc(label)}</span><strong>{esc(value)}</strong><small>{esc(note)}</small></div>'
        for label, value, note in items) + '</div>'


def empty_state(title, message, action=""):
    return f'<div class="empty"><span class="empty-mark" aria-hidden="true">○</span><h2>{esc(title)}</h2><p>{esc(message)}</p>{action}</div>'


from .terminal_theme import CSS, icon


def research_tabs(active="briefs", report=None):
    return '<nav class="research-tabs" aria-label="Research views">' + ''.join(
        f'<a href="{link(path, **({"report": report} if report else {}))}"' + (' aria-current="page"' if key == active else '') + f'>{label}</a>'
        for key, path, label in (("briefs", "/research", "Evidence & AI briefs"), ("news", "/news", "News & announcements"))) + '</nav>'


def document(title, content, *, active="today", subtitle="", standalone=False):
    links = (("today", "/", "Overview"), ("explore", "/explore", "Explore"),
             ("research", "/research", "Research"), ("paper", "/sandbox", "Demo trading"),
             ("history", "/research-history", "History"), ("coverage", "/coverage", "Coverage"),
             ("system", "/system", "System"))
    current = "research" if active in ("news", "briefs", "research") else active
    nav = '' if standalone else '<nav class="navigation" aria-label="Main navigation">' + ''.join(
        ('<span class="nav-group">Data &amp; system</span>' if key == 'coverage' else '') +
        f'<a href="{path}"' + (' aria-current="page"' if key == current else '') + f'>{icon(key)}<span>{label}</span></a>'
        for key, path, label in links) + '</nav>'
    brand_inner = '<span class="brand-mark" aria-hidden="true">O</span>Oraculum'
    brand = f'<span class="brand">{brand_inner}</span>' if standalone else f'<a class="brand" href="/">{brand_inner}</a>'
    advanced = '' if standalone else '<a href="/advanced">Advanced</a>'
    topbar = '' if standalone else '''<div class="workspace-topbar"><form class="global-search" method="get" action="/explore" role="search"><label class="sr-only" for="global-search">Search latest report by stock, company or ISIN</label><input id="global-search" type="search" name="q" maxlength="100" placeholder="Search a stock, company or ISIN…"><button type="submit">Search</button></form><span class="topbar-label"><strong>Research workspace</strong> &nbsp; / &nbsp; End-of-day</span></div>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} | Oraculum</title><style>{CSS}</style></head>
<body class="{'standalone' if standalone else 'workspace'}"><a class="skip" href="#main">Skip to content</a><header class="app-header"><div class="header-inner">{brand}{nav}<span class="header-note">Local · Paper research</span></div></header>{topbar}
<main id="main"><header class="page-heading"><h1>{esc(title)}</h1>{('<p>'+esc(subtitle)+'</p>') if subtitle else ''}</header>{content}
<footer class="app-footer"><p>Oraculum local 0.8.4 · Virtual money only. Scores are unvalidated research rankings, not probabilities or expected returns. Manual trades use virtual money only; no brokerage connection.</p>{advanced}</footer></main></body></html>'''
