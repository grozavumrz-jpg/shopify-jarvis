"""
backend/market_intel.py
Weekly market report WITH SOURCES for Grozavu: competitor prices, streetwear trends and the
real Google searches that bring people to the store.

Truthfulness rules (the whole point of this module):
  * Every competitor price and every trend carries a link and a date.
  * A competitor line is kept only if its website is one of the pages Google Search actually
    returned for that question (Gemini grounding sources) — invented shops are dropped.
  * A price counts as VERIFIED only when Jarvis opens the linked page itself and finds that
    price on it. Only verified EUR prices are used to compare with the store's prices.
  * Search Console numbers are copied as they are; nothing is estimated.
  * Read-only: nothing is written to Shopify, nothing is sent to customers.
"""

import asyncio
import html as html_lib
import ipaddress
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

try:
    from growth_studio import BRAND, DOMAIN, CATEGORY_RULES, _classify_product
except ImportError:  # pragma: no cover - package import path
    from backend.growth_studio import BRAND, DOMAIN, CATEGORY_RULES, _classify_product

REPORT_MAX_AGE_DAYS = 7
MAX_PAGE_BYTES = 1_500_000
FETCH_TIMEOUT = 8.0
RESEARCH_TIMEOUT = 75.0   # background job: Gemini + Google Search may be slow
CALL_SPACING_SECONDS = 8.0  # one Gemini search at a time, spaced: free API keys have low per-minute limits
USER_AGENT = "Mozilla/5.0 (compatible; GrozavuJarvis/1.0; +https://maisongrozavu.com)"

CATEGORY_SEARCH = {
    "hoodies": "premium heavyweight oversized hoodie",
    "tshirts": "premium heavyweight boxy t-shirt",
    "bottoms": "premium streetwear wide-leg shorts or pants",
    "outerwear": "premium streetwear jacket",
    "accessories": "premium streetwear cap or beanie",
}

_PRICE_LINE_RE = re.compile(r"^\s*PRICE\s*\|(.+)$", re.I | re.M)
_TREND_LINE_RE = re.compile(r"^\s*TREND\s*\|(.+)$", re.I | re.M)


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _domain(url: str) -> str:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _source_domains(sources: List[Dict[str, str]]) -> List[str]:
    """Gemini grounding sources: the title is normally the site's domain; the URL is a Google redirect."""
    out: List[str] = []
    for s in sources or []:
        for cand in (str(s.get("title") or ""), _domain(str(s.get("url") or ""))):
            d = cand.strip().lower()
            d = d[4:] if d.startswith("www.") else d
            if d and "." in d and " " not in d and "vertexaisearch" not in d and d not in out:
                out.append(d)
    return out


def _cited(url: str, domains: List[str]) -> bool:
    d = _domain(url)
    return bool(d) and any(d == s or d.endswith("." + s) or s.endswith("." + d) for s in domains)


def _parse_price(raw: str) -> Optional[float]:
    txt = str(raw or "").strip().replace("€", "").replace("£", "").replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d{1,4}([.,]\d{1,2})?", txt):
        return float(txt.replace(",", "."))
    return None


def price_on_page(page_text: str, price: float) -> bool:
    """True when the price appears on the page as a number (89 / 89.00 / 89,00 / 89.95 ...)."""
    if not page_text or price is None or price <= 0:
        return False
    whole = int(price)
    cents = int(round((price - whole) * 100))
    forms = {f"{whole}.{cents:02d}", f"{whole},{cents:02d}"}
    if cents == 0:
        forms.add(str(whole))
    for f in forms:
        if re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d])(?![.,]\d)", page_text):
            return True
    return False


async def _is_public_host(host: str) -> bool:
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # raw IP addresses are never fetched
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return False
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        except ValueError:
            return False
    return bool(infos)


async def fetch_page_text(url: str) -> Optional[str]:
    """Download a public https page (size/time limited, SSRF-safe) and return its visible text + JSON-LD."""
    if not str(url or "").startswith("https://"):
        return None
    current = url
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=False,
                                     headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,en;q=0.8"}) as client:
            for _ in range(4):
                host = urllib.parse.urlparse(current).hostname or ""
                if not await _is_public_host(host):
                    return None
                async with client.stream("GET", current) as res:
                    if res.status_code in (301, 302, 303, 307, 308):
                        nxt = urllib.parse.urljoin(current, res.headers.get("location") or "")
                        if not nxt.startswith("https://"):
                            return None
                        current = nxt
                        continue
                    if res.status_code != 200:
                        return None
                    chunks, size = [], 0
                    async for chunk in res.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PAGE_BYTES:
                            break
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode(res.encoding or "utf-8", errors="ignore")
                    # keep text + structured data (prices often live in JSON-LD / meta tags)
                    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
                    return html_lib.unescape(raw)
    except (httpx.HTTPError, ValueError, OSError):
        return None
    return None


# ── competitor prices ────────────────────────────────────────────────────────

def parse_price_lines(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _PRICE_LINE_RE.finditer(text or ""):
        parts = [p.strip() for p in m.group(1).split("|")]
        if len(parts) < 5:
            continue
        brand, product, price_raw, currency, url = parts[0], parts[1], parts[2], parts[3].upper(), parts[4]
        price = _parse_price(price_raw)
        if not brand or not product or price is None or not url.startswith("https://"):
            continue
        if re.search(r"grozavu", f"{brand} {url}", re.I):
            continue
        out.append({"brand": brand[:60], "product": product[:120], "price": price,
                    "currency": currency if currency in ("EUR", "GBP", "USD") else currency[:3],
                    "url": url[:400]})
    return out


async def collect_competitor_prices(ai_advisor: Any, key: str, label: str,
                                    fetch: Callable = fetch_page_text) -> Dict[str, Any]:
    query = CATEGORY_SEARCH.get(key, label)
    prompt = (
        f"Use Google Search to find 4 to 6 CURRENT prices of {label} (\"{query}\") sold online by independent "
        f"European streetwear brands on their own websites (no marketplaces, no resellers). Exclude {BRAND}.\n"
        "Write ONE line per product, exactly in this format and nothing else:\n"
        "PRICE | brand | product name | price number | currency (EUR, GBP or USD) | full product page URL\n"
        "Only include products that appear in your search results."
    )
    g: Dict[str, Any] = {}
    text = await ai_advisor._call_gemini(prompt, max_tokens=900, temperature=0.2,
                                         use_web_search=True, grounding_out=g, timeout=RESEARCH_TIMEOUT)
    sources = g.get("sources") or []
    domains = _source_domains(sources)
    found = parse_price_lines(text)
    observations: List[Dict[str, Any]] = []
    dropped_uncited = 0
    for obs in found[:8]:
        if not _cited(obs["url"], domains):
            dropped_uncited += 1  # not among the pages Google actually returned -> could be invented
            continue
        page = await fetch(obs["url"])
        seen = bool(page and price_on_page(page, obs["price"]))
        if not seen and "/products/" in urllib.parse.urlparse(obs["url"]).path:
            # Shopify shops: the product JSON shows the price in the shop's own currency, whatever
            # country the visitor comes from (the page itself may show a converted price).
            json_url = obs["url"].split("?", 1)[0].split("#", 1)[0].rstrip("/") + ".json"
            data = await fetch(json_url)
            seen = bool(data and price_on_page(data, obs["price"]))
        obs["price_seen_on_page"] = seen
        obs["verified"] = bool(seen and obs["currency"] == "EUR")
        obs["checked_at"] = _now_iso()
        observations.append(obs)
    return {
        "label": label,
        "search": query,
        "observations": observations,
        "dropped_uncited": dropped_uncited,
        "search_queries": g.get("search_queries") or [],
        "sources": sources[:6],
        "web_grounded": bool(g.get("web_grounded")),
    }


# ── trends ───────────────────────────────────────────────────────────────────

def parse_trend_lines(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in _TREND_LINE_RE.finditer(text or ""):
        parts = [p.strip() for p in m.group(1).split("|")]
        if len(parts) < 3:
            continue
        name, desc, url = parts[0], parts[1], parts[2]
        if name and url.startswith("https://"):
            out.append({"trend": name[:80], "description": desc[:240], "url": url[:400]})
    return out


async def collect_trends(ai_advisor: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
              6: "summer", 7: "summer", 8: "summer"}.get(now.month, "autumn")
    prompt = (
        f"Use Google Search to find 5 current streetwear trends for {season} {now.year} in Spain and Europe that are "
        "relevant to hoodies, t-shirts, pants and accessories.\n"
        "Write ONE line per trend, exactly in this format and nothing else:\n"
        "TREND | short name | one sentence describing it | URL of the article where you found it\n"
        "Only include trends that appear in your search results."
    )
    g: Dict[str, Any] = {}
    text = await ai_advisor._call_gemini(prompt, max_tokens=900, temperature=0.3,
                                         use_web_search=True, grounding_out=g, timeout=RESEARCH_TIMEOUT)
    domains = _source_domains(g.get("sources") or [])
    trends = [t for t in parse_trend_lines(text) if _cited(t["url"], domains)]
    for t in trends:
        t["found_at"] = _now_iso()
    return {"trends": trends[:6], "sources": (g.get("sources") or [])[:6],
            "web_grounded": bool(g.get("web_grounded"))}


# ── Search Console (real numbers only) ──────────────────────────────────────

def search_console_section(gsc_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(gsc_report, dict) or not gsc_report.get("connected"):
        return {"connected": False, "top_queries": [], "opportunities": []}

    def pick(rows, n):
        out = []
        for q in rows or []:
            if isinstance(q, dict) and str(q.get("query") or "").strip():
                out.append({k: q.get(k) for k in ("query", "clicks", "impressions", "position")})
            if len(out) >= n:
                break
        return out
    return {"connected": True, "period": "ultimele 28 de zile",
            "top_queries": pick(gsc_report.get("top_queries"), 5),
            "opportunities": pick(gsc_report.get("opportunity_queries"), 5)}


# ── report ───────────────────────────────────────────────────────────────────

def catalog_categories(products: Optional[List[Dict[str, Any]]]) -> List[Tuple[str, str]]:
    present = {_classify_product(p) for p in (products or []) if isinstance(p, dict)
               and str(p.get("status") or "active").lower() == "active"}
    return [(k, lbl) for k, lbl, *_ in CATEGORY_RULES if k in present]


async def build_market_report(ai_advisor: Any, products: Optional[List[Dict[str, Any]]],
                              gsc_report: Optional[Dict[str, Any]],
                              fetch: Callable = fetch_page_text) -> Dict[str, Any]:
    if ai_advisor is None or len(getattr(ai_advisor, "_get_api_key", lambda: "")()) < 10:
        return {"ok": False, "error": "gemini_not_configured",
                "message": "GEMINI_API_KEY lipsește: raportul cu surse nu poate căuta pe internet."}
    cats = catalog_categories(products)
    errors: List[str] = []
    categories: Dict[str, Any] = {}
    quota_hit = False

    def _is_quota(e: Exception) -> bool:
        return "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower()

    # One search at a time with a pause between them; stop at the first "429" (API limit reached)
    # instead of hammering the key - the other Jarvis features share the same Gemini quota.
    for i, (key, label) in enumerate(cats):
        if i:
            await asyncio.sleep(CALL_SPACING_SECONDS)
        try:
            categories[key] = await collect_competitor_prices(ai_advisor, key, label, fetch=fetch)
        except Exception as e:  # noqa: BLE001 - one category failing must not stop the report
            errors.append(f"{label}: {str(e)[:140]}")
            if _is_quota(e):
                quota_hit = True
                break
    trends: Dict[str, Any] = {"trends": [], "sources": [], "web_grounded": False}
    if not quota_hit:
        try:
            if cats:
                await asyncio.sleep(CALL_SPACING_SECONDS)
            trends = await collect_trends(ai_advisor)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Trenduri: {str(e)[:140]}")
            quota_hit = quota_hit or _is_quota(e)

    verified = sum(1 for c in categories.values() for o in c["observations"] if o.get("verified"))
    found = sum(len(c["observations"]) for c in categories.values())
    ok = bool(categories or trends.get("trends"))
    if ok:
        message = None
    elif quota_hit:
        message = ("Gemini a refuzat cererile (429: limita de utilizare a cheii API Gemini a fost atinsă). "
                   "Jarvis reîncearcă automat peste câteva ore.")
    else:
        message = "Raportul nu s-a putut face: " + ("; ".join(errors)[:400] or "căutarea nu a întors niciun rezultat cu sursă")
    return {
        "ok": ok,
        "quota_hit": quota_hit,
        "message": message,
        "generated_at": _now_iso(),
        "engine": "Gemini + Google Search; Jarvis deschide fiecare link și verifică prețul pe pagină",
        "categories": categories,
        "prices_found": found,
        "prices_verified": verified,
        "trends": trends.get("trends") or [],
        "trend_sources": trends.get("sources") or [],
        "search_console": search_console_section(gsc_report),
        "errors": errors,
        "rules_ro": [
            "Fiecare preț și fiecare trend are link și dată.",
            "Un preț e „verificat” doar dacă Jarvis l-a găsit chiar pe pagina din link.",
            "La comparația cu prețurile tale intră doar prețurile verificate în EUR.",
        ],
    }


def report_is_stale(report: Optional[Dict[str, Any]], now: Optional[datetime] = None,
                    max_age_days: int = REPORT_MAX_AGE_DAYS) -> bool:
    if not isinstance(report, dict) or not report.get("generated_at"):
        return True
    try:
        ts = datetime.strptime(str(report["generated_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return ((now or datetime.now(timezone.utc)) - ts).total_seconds() >= max_age_days * 86400


def telegram_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """Short data for the merchant notification (formatted by mobile_notifier)."""
    lines: List[str] = []
    for key, cat in (report.get("categories") or {}).items():
        ver = [o for o in cat.get("observations") or [] if o.get("verified")]
        if ver:
            prices = sorted(o["price"] for o in ver)
            lines.append(f"{cat.get('label')}: {prices[0]:.0f}–{prices[-1]:.0f} EUR ({len(ver)} prețuri verificate)")
        else:
            lines.append(f"{cat.get('label')}: niciun preț verificat săptămâna asta")
    for t in (report.get("trends") or [])[:3]:
        lines.append(f"Trend: {t['trend']}")
    sc = report.get("search_console") or {}
    if sc.get("connected") and sc.get("top_queries"):
        q = sc["top_queries"][0]
        lines.append(f"Căutarea cu cele mai multe click-uri: „{q['query']}” ({q.get('clicks', 0)} click-uri)")
    return {"as_of": str(report.get("generated_at") or "")[:10], "summary_lines": lines[:10],
            "prices_verified": report.get("prices_verified", 0), "prices_found": report.get("prices_found", 0)}
