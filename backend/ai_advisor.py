"""
Jarvis AI advisor (briefing, chat, growth ideas, recovery copy) for Grozavu (maisongrozavu.com).

Truth rules enforced here:
  - No fabricated numbers: every store number comes from the Shopify snapshot. When
    snapshot["connected"] is not True there is NO store data and none is shown.
  - Ideas / strategy content is labelled as ideas ("kind": "ideas") and carries no metrics
    (no invented search volumes, CPC, ratings, conversion uplifts...).
  - Jarvis chat can only advise; it never claims to have changed the store or sent anything.
  - Brand facts: premium streetwear, "Designed in Spain", English storefront, markets ES + RO,
    brand name "Grozavu", never "unisex", no atelier / silk / Bucharest claims.
"""
import os
import json
import math
import re
import asyncio
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]
CANDIDATE_MODELS = list(DEFAULT_GEMINI_MODELS)  # backwards-compatible name
GEMINI_TIMEOUT = 20.0
SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
SUGGEST_TIMEOUT = 4.0
DEFAULT_SUGGEST_QUERY = "heavyweight hoodie"

BRAND = "Grozavu"
DOMAIN = "maisongrozavu.com"
SUPPORTED_LANGS = ("ro", "en", "es")
LANG_NAMES = {"ro": "Romanian", "en": "English", "es": "Spanish"}

BRAND_FACTS = f"""BRAND FACTS (the only brand facts you may state):
- Brand name in copy: "{BRAND}" (website {DOMAIN}). Premium streetwear: hoodies, crewnecks (380 g/m2), boxy tees (170 g/m2), windbreaker, pants, sling bag, cap.
- Made to order via Printful (print on demand). Origin wording: "Designed in Spain" only (never "made/crafted in Spain").
- Storefront language: English. Priority markets: Spain and Romania. The owner reads Romanian.
- Never use the word "unisex". Never mention atelier, silk, tailoring, handmade, Bucharest.
- Do not invent shipping times, return policies, reviews, ratings, stock scarcity, reserved items, discounts or sales figures."""

CAPABILITIES = """CAPABILITIES: You can only give advice and draft texts. You cannot change the store, create discounts,
publish banners, send emails/WhatsApp, or browse the web. Never say you did, activated, sent, scanned or published anything.
If the owner wants something done, give the exact steps they can follow in Shopify Admin or in the Jarvis tabs.
Marketing messages may only go to customers with explicit consent (unknown consent = no consent)."""


class GeminiUnavailable(Exception):
    pass


_real_sleep = asyncio.sleep  # bound at import: unaffected by tests that patch asyncio.sleep globally


# ── helpers ───────────────────────────────────────────────────────────────────

def get_gemini_models() -> List[str]:
    """Model order: env GEMINI_MODEL (comma-separated allowed) first, then the defaults."""
    env = os.getenv("GEMINI_MODEL", "") or ""
    out: List[str] = []
    for m in [x.strip() for x in env.split(",") if x.strip()] + DEFAULT_GEMINI_MODELS:
        if m not in out:
            out.append(m)
    return out


def normalize_lang(lang: Optional[str], default: Optional[str] = "ro") -> Optional[str]:
    code = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LANGS else default


def is_connected(snap: Any) -> bool:
    """Only snapshots explicitly marked connected=True carry real store data."""
    return isinstance(snap, dict) and snap.get("connected") is True


def _to_float(token: str) -> Optional[float]:
    """'2500.50'->2500.5, '2.500,50'->2500.5, '2,500.50'->2500.5, '2.500'->2500, '1,5'->1.5."""
    t = (token or "").strip().strip(".,")
    if not t:
        return None
    if "." in t and "," in t:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        thou = "," if dec == "." else "."
        t = t.replace(thou, "").replace(dec, ".")
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        parts = t.split(sep)
        if len(parts) > 2:
            t = "".join(parts)  # several separators => thousands
        else:
            left, right = parts
            if len(right) == 3 and 1 <= len(left) <= 3:
                t = left + right  # "2.500" / "2,500" => thousands
            else:
                t = f"{left}.{right}"
    try:
        return float(t)
    except ValueError:
        return None


_NUM_RE = r"\d[\d.,]*"


def parse_amount(text: str) -> Optional[float]:
    """First money amount in text (supports decimals, thousand separators and a 'k' suffix)."""
    m = re.search(rf"({_NUM_RE})\s*(k\b)?", text or "", flags=re.I)
    if not m:
        return None
    val = _to_float(m.group(1))
    if val is None:
        return None
    if m.group(2):
        val *= 1000
    return round(val, 2)


def parse_goal_message(message: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """'/goal 2.500,50 EUR aov 65' -> (2500.5, 65.0, 'EUR')."""
    text = message or ""
    aov = None
    m = re.search(rf"\b(?:aov|valoare\s+medie|ticket\s+medio)\s*[:=]?\s*({_NUM_RE})", text, flags=re.I)
    if m:
        aov = _to_float(m.group(1))
        text = text[: m.start()] + " " + text[m.end():]
    target = parse_amount(text)
    curr = None
    if re.search(r"\b(ron|lei)\b", text, re.I):
        curr = "RON"
    elif re.search(r"\b(eur|euro|euros)\b|€", text, re.I):
        curr = "EUR"
    elif re.search(r"\b(usd|dolari|dollars?)\b|\$", text, re.I):
        curr = "USD"
    return target, aov, curr


def _fmt_money(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


_UNAVAILABLE = {"ro": "indisponibil", "en": "unavailable", "es": "no disponible"}


def _val(v: Any, lang: str) -> str:
    return _UNAVAILABLE.get(lang, "unavailable") if v is None else str(v)


def _customer_brand(shop_name: Optional[str]) -> str:
    name = (shop_name or "").strip()
    if not name or "grozavu" in name.lower() or name.endswith(".myshopify.com"):
        return BRAND
    return name


def _pick(texts: Dict[str, str], lang: str) -> str:
    return texts.get(lang) or texts.get("en") or next(iter(texts.values()))


_FORBIDDEN_RECOVERY_RE = re.compile(
    r"reserv|rezerv|riserv|réserv|\bunisex\b|\bstock\b|\bstoc\b|\bSTOP\b|maison\s+grozavu|countdown|deadline|"
    r"expire|expira|scade|last chance|ultima șansă|only \d+ left|\d+\s*(hours?|ore|horas|ore)\s*(left|rămase|restantes)",
    re.IGNORECASE)
_CODE_RE = re.compile(r"\b[A-Z]{2,}[0-9]{1,3}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def validate_recovery_copy(copy: Dict[str, str], url: str, code: Optional[str]) -> Optional[str]:
    """Return a reason if AI-written customer copy must not be sent, else None.
    Customer-facing text is checked because it goes to real shoppers unattended."""
    text = " ".join(str(copy.get(k) or "") for k in ("subject", "body", "whatsapp_message"))
    if "{{" in text or "}}" in text:
        return "unfilled placeholder"
    prose = _URL_RE.sub(" ", text)  # links are checked separately; their tokens are not wording/codes
    m = _FORBIDDEN_RECOVERY_RE.search(prose)
    if m:
        return f"forbidden wording '{m.group(0)}'"
    for found in _URL_RE.findall(text):
        if url and found.rstrip(".,;:!?") != url:
            return "unexpected link"
        if not url:
            return "link without a checkout URL"
    if url and (url not in copy.get("body", "") or url not in copy.get("whatsapp_message", "")):
        return "checkout link missing"
    codes = set(_CODE_RE.findall(prose))
    allowed = {code.upper()} if code else set()
    if codes - allowed:
        return f"unexpected code {sorted(codes - allowed)}"
    if code and code.upper() not in codes:
        return "discount code missing"
    if not code and "%" in prose:
        return "discount mentioned without a code"
    return None


class AIAdvisor:
    def __init__(self):
        self.api_key = GEMINI_API_KEY

    def _get_api_key(self) -> str:
        return (os.getenv("GEMINI_API_KEY") or self.api_key or "").strip()

    # ── snapshot → prompt context ─────────────────────────────────────────────

    def _snapshot_to_text(self, snap: Dict, lang: str = "en") -> str:
        if not is_connected(snap):
            reason = (snap or {}).get("data_error") if isinstance(snap, dict) else None
            return ("NO STORE DATA: Shopify is not connected"
                    + (f" ({reason})" if reason else "")
                    + ". You do not know any orders, revenue, customers, carts, stock or products. "
                      "Do not invent or estimate any store number; if asked, say the data is unavailable.")

        cur = snap.get("currency") or "EUR"

        def v(key):
            return "unavailable" if snap.get(key) is None else snap.get(key)

        lines = [
            f"Store: {snap.get('shop_name') or BRAND} (real data from Shopify, fetched {snap.get('fetched_at') or datetime.now().isoformat(timespec='minutes')})",
            f"- Orders last 24h: {v('orders_today')} | revenue last 24h: {v('revenue_today')} {cur}",
            f"- Orders last 30 days: {v('orders_30d')} | revenue last 30 days: {v('revenue_30d')} {cur}",
            f"- Average order value (30d): {v('aov')} {cur}",
            f"- Abandoned checkouts (7 days): {v('abandoned_carts')}",
            f"- New customers (24h): {v('new_customers_24h')}",
            f"- Unique buyers (30d): {v('total_unique_customers')} | repeat buyers: {v('repeat_customers')}",
            f"- Active products: {v('active_products_count')} | average active product price: {v('avg_product_price')} {cur}",
        ]
        top = snap.get("top_products") or []
        if top:
            lines.append("- Top products (30d units): " + ", ".join(f"{p.get('name')} ({p.get('units')})" for p in top[:5]))
        low = snap.get("low_stock_items")
        if low:
            lines.append("- Low stock (tracked variants): " + ", ".join(
                f"{i.get('product')} {i.get('variant') or ''} ({i.get('qty')})".strip() for i in low[:5]))
        if snap.get("unavailable"):
            lines.append("- Could not read: " + ", ".join(sorted(snap["unavailable"].keys())))
        return "\n".join(lines)

    # ── Gemini ────────────────────────────────────────────────────────────────

    async def _call_gemini(self, prompt: str, json_mode: bool = False, max_tokens: int = 1200,
                           temperature: float = 0.7) -> str:
        """
        Call Gemini generateContent via REST. The API key goes in the `x-goog-api-key` header
        (never in the URL). Tries models from get_gemini_models() in order.
        Raises GeminiUnavailable when no key / every model failed.
        """
        key = self._get_api_key()
        if len(key) < 10:
            raise GeminiUnavailable("GEMINI_API_KEY not configured")
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        last_error = ""
        for model in get_gemini_models():
            gen_cfg: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
            if json_mode:
                gen_cfg["responseMimeType"] = "application/json"
            if model.startswith("gemini-2.5"):
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
            else:
                gen_cfg["maxOutputTokens"] = max(max_tokens, 4096)
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
            url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
                        res = await client.post(url, json=payload, headers=headers)
                except httpx.HTTPError as e:
                    last_error = f"{model}: {type(e).__name__}"
                    break  # network/timeout: next model
                if res.status_code == 200:
                    try:
                        data = res.json()
                    except ValueError:
                        last_error = f"{model}: invalid JSON"
                        break
                    text = self._extract_gemini_text(data)
                    if text:
                        return text
                    last_error = f"{model}: empty response"
                    break
                if res.status_code in (401, 403):
                    raise GeminiUnavailable(f"Gemini rejected the API key ({res.status_code})")
                if res.status_code in (429, 500, 503) and attempt == 0:
                    last_error = f"{model} ({res.status_code})"
                    await _real_sleep(1.0)
                    continue
                last_error = f"{model} ({res.status_code})"
                break
        raise GeminiUnavailable(f"Gemini unavailable ({last_error})")

    @staticmethod
    def _extract_gemini_text(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for cand in data.get("candidates") or []:
            parts = ((cand or {}).get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
            if text.strip():
                return text.strip()
        return ""

    @staticmethod
    def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        start, end = text.find("{"), text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end])
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None

    # ── Google Suggest ────────────────────────────────────────────────────────

    async def fetch_google_suggest(self, query: str = DEFAULT_SUGGEST_QUERY, lang: str = "en") -> Dict[str, Any]:
        """
        Google Autocomplete suggestions (no search volumes exist in this source).
        Returns {"query", "results", "count", "source": "google_suggest"|"unavailable", "error"?}.
        On any failure results is [] — never invented suggestions.
        """
        clean_q = (query or "").strip()
        clean_q = re.sub(r"^/?browser\s*", "", clean_q, flags=re.I).strip()
        clean_q = re.sub(r"^[^\w]+", "", clean_q).strip()[:120]
        if len(clean_q) < 2:
            clean_q = DEFAULT_SUGGEST_QUERY
        hl = normalize_lang(lang, "en")
        params = {"client": "firefox", "q": clean_q, "hl": hl}
        try:
            async with httpx.AsyncClient(timeout=SUGGEST_TIMEOUT) as client:
                res = await client.get(SUGGEST_URL, params=params,
                                       headers={"User-Agent": "Mozilla/5.0 (Jarvis for Shopify)"})
            if res.status_code != 200:
                raise ValueError(f"HTTP {res.status_code}")
            data = res.json()
            if not (isinstance(data, list) and len(data) > 1 and isinstance(data[1], list)):
                raise ValueError("unexpected response format")
            results = [str(x) for x in data[1] if isinstance(x, str) and x.strip()][:10]
            return {"query": clean_q, "results": results, "count": len(results),
                    "source": "google_suggest", "language": hl,
                    "note": "Sugestii Google Autocomplete — fără volume de căutare."}
        except Exception as e:
            print(f"[Google Suggest unavailable]: {type(e).__name__}: {str(e)[:120]}")
            return {"query": clean_q, "results": [], "count": 0, "source": "unavailable",
                    "language": hl, "error": f"{type(e).__name__}"}

    async def fetch_live_google_trends(self, query: str = DEFAULT_SUGGEST_QUERY) -> List[str]:
        """Backwards-compatible list form of fetch_google_suggest ([] when unavailable)."""
        return (await self.fetch_google_suggest(query))["results"]

    # ── Briefing ──────────────────────────────────────────────────────────────

    def _metrics(self, snap: Dict) -> Dict[str, Any]:
        keys = ("orders_today", "orders_30d", "revenue_today", "revenue_30d", "aov", "abandoned_carts",
                "new_customers_24h", "total_unique_customers", "repeat_customers", "active_products_count",
                "avg_product_price", "currency")
        return {k: snap.get(k) for k in keys}

    def _facts_summary(self, snap: Dict, lang: str) -> Tuple[str, str]:
        """Deterministic (summary, voice_script) built only from snapshot numbers."""
        cur = snap.get("currency") or "EUR"
        o30, r30 = _val(snap.get("orders_30d"), lang), snap.get("revenue_30d")
        o1, r1 = _val(snap.get("orders_today"), lang), snap.get("revenue_today")
        carts = _val(snap.get("abandoned_carts"), lang)
        prods = snap.get("active_products_count")
        no_sales = snap.get("orders_30d") == 0
        r30s = _val(None if r30 is None else _fmt_money(r30), lang)
        r1s = _val(None if r1 is None else _fmt_money(r1), lang)
        if lang == "ro":
            s = (f"Date reale Shopify — ultimele 30 de zile: {o30} comenzi ({r30s} {cur}); ultimele 24h: {o1} comenzi "
                 f"({r1s} {cur}); coșuri abandonate în 7 zile: {carts}.")
            if prods is not None:
                s += f" Produse active: {prods}."
            if no_sales:
                s += " Nu există vânzări în ultimele 30 de zile — prioritatea este traficul calificat către paginile de produs."
            voice = f"Iată datele reale: {o1} comenzi în ultimele 24 de ore, {o30} în ultimele 30 de zile și {carts} coșuri abandonate."
        elif lang == "es":
            s = (f"Datos reales de Shopify — últimos 30 días: {o30} pedidos ({r30s} {cur}); últimas 24 h: {o1} pedidos "
                 f"({r1s} {cur}); carritos abandonados en 7 días: {carts}.")
            if prods is not None:
                s += f" Productos activos: {prods}."
            if no_sales:
                s += " No hay ventas en los últimos 30 días: la prioridad es atraer tráfico cualificado a las fichas de producto."
            voice = f"Estos son los datos reales: {o1} pedidos en las últimas 24 horas, {o30} en 30 días y {carts} carritos abandonados."
        else:
            s = (f"Real Shopify data — last 30 days: {o30} orders ({r30s} {cur}); last 24h: {o1} orders "
                 f"({r1s} {cur}); abandoned checkouts in 7 days: {carts}.")
            if prods is not None:
                s += f" Active products: {prods}."
            if no_sales:
                s += " No sales in the last 30 days — the priority is qualified traffic to the product pages."
            voice = f"Here is the real data: {o1} orders in the last 24 hours, {o30} in the last 30 days and {carts} abandoned checkouts."
        return s, voice

    def _data_alerts(self, snap: Dict, lang: str) -> List[Dict[str, str]]:
        alerts = []
        carts = snap.get("abandoned_carts")
        if isinstance(carts, int) and carts > 0:
            alerts.append({"type": "warning", "message": _pick({
                "ro": f"{carts} coșuri abandonate în ultimele 7 zile.",
                "en": f"{carts} abandoned checkouts in the last 7 days.",
                "es": f"{carts} carritos abandonados en los últimos 7 días.",
            }, lang), "action": _pick({
                "ro": "Verifică tabul Pilot Automat — mesajele pleacă doar către clienții cu consimțământ de marketing.",
                "en": "Check the Autopilot tab — messages only go to customers with marketing consent.",
                "es": "Revisa la pestaña Piloto automático: los mensajes solo van a clientes con consentimiento de marketing.",
            }, lang)})
        low = snap.get("low_stock_items")
        if low:
            alerts.append({"type": "danger", "message": _pick({
                "ro": f"{len(low)} variante cu stoc urmărit de Shopify sunt la 5 bucăți sau mai puțin.",
                "en": f"{len(low)} Shopify-tracked variants are at 5 units or fewer.",
                "es": f"{len(low)} variantes con inventario de Shopify tienen 5 unidades o menos.",
            }, lang), "action": _pick({
                "ro": "Verifică stocul în Shopify → Products → Inventory.",
                "en": "Review stock in Shopify → Products → Inventory.",
                "es": "Revisa el stock en Shopify → Productos → Inventario.",
            }, lang)})
        if snap.get("unavailable"):
            names = ", ".join(sorted(snap["unavailable"].keys()))
            alerts.append({"type": "info", "message": _pick({
                "ro": f"Unele date nu au putut fi citite din Shopify: {names}.",
                "en": f"Some data could not be read from Shopify: {names}.",
                "es": f"No se pudieron leer algunos datos de Shopify: {names}.",
            }, lang), "action": _pick({
                "ro": "Verifică permisiunile aplicației (scopes) sau reîncearcă mai târziu.",
                "en": "Check the app permissions (scopes) or retry later.",
                "es": "Revisa los permisos de la app (scopes) o inténtalo más tarde.",
            }, lang)})
        return alerts

    def _default_tasks(self, snap: Dict, lang: str) -> List[Dict[str, Any]]:
        tasks = []
        carts = snap.get("abandoned_carts") if is_connected(snap) else None
        if isinstance(carts, int) and carts > 0:
            tasks.append({"task": _pick({
                "ro": f"Verifică cele {carts} coșuri abandonate în tabul Pilot Automat.",
                "en": f"Review the {carts} abandoned checkouts in the Autopilot tab.",
                "es": f"Revisa los {carts} carritos abandonados en la pestaña Piloto automático.",
            }, lang), "why": _pick({
                "ro": "Sunt oameni care au ajuns până la checkout; contactează-i doar dacă au dat consimțământ.",
                "en": "These shoppers reached checkout; contact them only if they gave consent.",
                "es": "Llegaron al checkout; contáctalos solo si dieron su consentimiento.",
            }, lang), "icon": "🛒"})
        tasks.append({"task": _pick({
            "ro": "Postează un Reel/TikTok de 15–20 s care arată grosimea crewneck-ului de 380 g/m² și fit-ul boxy al tricourilor.",
            "en": "Post a 15–20s Reel/TikTok showing the 380 g/m² crewneck fabric and the boxy tee fit.",
            "es": "Publica un Reel/TikTok de 15–20 s mostrando el tejido de 380 g/m² de la crewneck y el fit boxy de las camisetas.",
        }, lang), "why": _pick({
            "ro": "Idee: conținutul care arată materialul real răspunde la întrebarea principală a cumpărătorului online.",
            "en": "Idea: showing the real fabric answers the main question online shoppers have.",
            "es": "Idea: enseñar el tejido real responde a la principal duda del comprador online.",
        }, lang), "icon": "📱"})
        tasks.append({"task": _pick({
            "ro": "Deschide tabul SEO și aplică manual propunerile care ți se par corecte (titluri, descrieri, ALT).",
            "en": "Open the SEO tab and manually apply the proposals you agree with (titles, descriptions, ALT).",
            "es": "Abre la pestaña SEO y aplica a mano las propuestas que te convenzan (títulos, descripciones, ALT).",
        }, lang), "why": _pick({
            "ro": "Jarvis doar propune; modificările le faci tu în Shopify Admin.",
            "en": "Jarvis only proposes; you make the changes in Shopify Admin.",
            "es": "Jarvis solo propone; los cambios los haces tú en Shopify Admin.",
        }, lang), "icon": "🔍"})
        tasks.append({"task": _pick({
            "ro": "Verifică sesiunile din ultimele 7 zile în Shopify → Analytics.",
            "en": "Check the last 7 days of sessions in Shopify → Analytics.",
            "es": "Revisa las sesiones de los últimos 7 días en Shopify → Analytics.",
        }, lang), "why": _pick({
            "ro": "Jarvis nu citește traficul; fără vizitatori nu pot exista comenzi.",
            "en": "Jarvis doesn't read traffic; without visitors there can be no orders.",
            "es": "Jarvis no lee el tráfico; sin visitas no puede haber pedidos.",
        }, lang), "icon": "📈"})
        for i, t in enumerate(tasks[:3]):
            t["priority"] = i + 1
        return tasks[:3]

    def _disconnected_briefing(self, snap: Dict, lang: str) -> Dict[str, Any]:
        reason = (snap or {}).get("data_error") if isinstance(snap, dict) else None
        reason_txt = f" ({reason})" if reason else ""
        texts = {
            "ro": {
                "greeting": "Salut! Shopify nu este conectat, așa că nu am date despre magazin.",
                "voice": "Shopify nu este conectat. Nu pot raporta comenzi, venituri sau coșuri până nu reconectezi aplicația.",
                "summary": f"Shopify nu este conectat{reason_txt}. Nu afișez comenzi, venituri, clienți sau coșuri — fără conexiune nu există date reale.",
                "t1": "Reconectează Shopify: deschide Jarvis din Shopify Admin → Apps sau reinstalează aplicația.",
                "w1": "Fără un token valid nu pot citi comenzi, produse sau coșuri abandonate.",
                "t2": "După reconectare, revino la acest briefing pentru cifrele reale.",
                "w2": "Briefingul folosește doar date din Shopify.",
                "t3": "Între timp verifică DNS-ul de email (SPF, DKIM, DMARC) în tabul Livrabilitate.",
                "w3": "Verificarea DNS nu depinde de conexiunea cu Shopify.",
                "alert": "Shopify nu este conectat — nu există date despre magazin.",
                "action": "Reconectează aplicația din Shopify Admin.",
                "tip": "Idee: un clip scurt care arată materialul și fit-ul pieselor este cel mai simplu conținut de început.",
            },
            "es": {
                "greeting": "¡Hola! Shopify no está conectado, así que no tengo datos de la tienda.",
                "voice": "Shopify no está conectado. No puedo informar de pedidos, ingresos ni carritos hasta que vuelvas a conectar la app.",
                "summary": f"Shopify no está conectado{reason_txt}. No muestro pedidos, ingresos, clientes ni carritos: sin conexión no hay datos reales.",
                "t1": "Vuelve a conectar Shopify: abre Jarvis desde Shopify Admin → Apps o reinstala la app.",
                "w1": "Sin un token válido no puedo leer pedidos, productos ni carritos abandonados.",
                "t2": "Tras reconectar, vuelve a este briefing para ver las cifras reales.",
                "w2": "El briefing solo usa datos de Shopify.",
                "t3": "Mientras tanto, revisa el DNS del email (SPF, DKIM, DMARC) en la pestaña Entregabilidad.",
                "w3": "La revisión DNS no depende de la conexión con Shopify.",
                "alert": "Shopify no está conectado: no hay datos de la tienda.",
                "action": "Vuelve a conectar la app desde Shopify Admin.",
                "tip": "Idea: un clip corto mostrando el tejido y el fit es el contenido más fácil para empezar.",
            },
            "en": {
                "greeting": "Hi! Shopify is not connected, so I have no store data.",
                "voice": "Shopify is not connected. I can't report orders, revenue or carts until you reconnect the app.",
                "summary": f"Shopify is not connected{reason_txt}. No orders, revenue, customers or carts are shown — without a connection there is no real data.",
                "t1": "Reconnect Shopify: open Jarvis from Shopify Admin → Apps or reinstall the app.",
                "w1": "Without a valid token I can't read orders, products or abandoned checkouts.",
                "t2": "After reconnecting, come back to this briefing for the real numbers.",
                "w2": "The briefing only uses Shopify data.",
                "t3": "Meanwhile, check the email DNS (SPF, DKIM, DMARC) in the Deliverability tab.",
                "w3": "The DNS check does not depend on the Shopify connection.",
                "alert": "Shopify is not connected — there is no store data.",
                "action": "Reconnect the app from Shopify Admin.",
                "tip": "Idea: a short clip showing the fabric and fit is the easiest content to start with.",
            },
        }[lang]
        return {
            "kind": "briefing",
            "connected": False,
            "data_source": "none",
            "source": "system",
            "health_score": None,
            "metrics": None,
            "greeting": texts["greeting"],
            "voice_script": texts["voice"],
            "summary": texts["summary"],
            "top_tasks": [
                {"priority": 1, "task": texts["t1"], "why": texts["w1"], "icon": "🔌"},
                {"priority": 2, "task": texts["t2"], "why": texts["w2"], "icon": "📊"},
                {"priority": 3, "task": texts["t3"], "why": texts["w3"], "icon": "✉️"},
            ],
            "alerts": [{"type": "danger", "message": texts["alert"], "action": texts["action"]}],
            "traffic_tip": texts["tip"],
            "motivation": "",
            "lang": lang,
        }

    def _fallback_briefing(self, snap: Dict, lang: str = "ro") -> Dict[str, Any]:
        """Deterministic briefing (no Gemini). Never contains invented numbers."""
        lang = normalize_lang(lang, "ro")
        if not is_connected(snap):
            return self._disconnected_briefing(snap, lang)
        summary, voice = self._facts_summary(snap, lang)
        return {
            "kind": "briefing",
            "connected": True,
            "data_source": snap.get("data_source") or "shopify",
            "source": "fallback",
            "health_score": None,
            "metrics": self._metrics(snap),
            "greeting": _pick({"ro": "Salut! Iată situația reală a magazinului.",
                               "en": "Hi! Here is the real state of the store.",
                               "es": "¡Hola! Esta es la situación real de la tienda."}, lang),
            "voice_script": voice,
            "summary": summary,
            "top_tasks": self._default_tasks(snap, lang),
            "alerts": self._data_alerts(snap, lang),
            "traffic_tip": _pick({
                "ro": "Idee: arată în primele 2 secunde ale clipului textura materialului, apoi piesa purtată — link direct către produs.",
                "en": "Idea: show the fabric texture in the first 2 seconds, then the piece worn — link straight to the product.",
                "es": "Idea: enseña la textura del tejido en los 2 primeros segundos y luego la prenda puesta, con enlace directo al producto.",
            }, lang),
            "motivation": "",
            "ideas_label": _pick({"ro": "Sarcinile și sfaturile sunt idei, nu date.",
                                  "en": "Tasks and tips are ideas, not data.",
                                  "es": "Las tareas y consejos son ideas, no datos."}, lang),
            "lang": lang,
        }

    @staticmethod
    def _clean_str(v: Any, limit: int = 500) -> str:
        return str(v).strip()[:limit] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""

    def _validate_ai_briefing(self, raw: Any) -> Dict[str, Any]:
        """Keep only well-formed fields from the model output (frontend-safe shapes)."""
        out: Dict[str, Any] = {}
        if not isinstance(raw, dict):
            return out
        for key in ("greeting", "traffic_tip", "motivation"):
            s = self._clean_str(raw.get(key), 400)
            if s:
                out[key] = s
        tasks_raw = raw.get("top_tasks")
        if isinstance(tasks_raw, (str, dict)):
            tasks_raw = [tasks_raw]
        tasks = []
        if isinstance(tasks_raw, list):
            for item in tasks_raw:
                if isinstance(item, str):
                    task, why, icon = item.strip(), "", "•"
                elif isinstance(item, dict):
                    task = self._clean_str(item.get("task") or item.get("title"), 300)
                    why = self._clean_str(item.get("why") or item.get("reason"), 300)
                    icon = self._clean_str(item.get("icon"), 4) or "•"
                else:
                    continue
                if task:
                    tasks.append({"priority": len(tasks) + 1, "task": task[:300], "why": why, "icon": icon})
                if len(tasks) >= 5:
                    break
        if tasks:
            out["top_tasks"] = tasks
        return out

    async def generate_briefing(self, snapshot: Dict, lang: str = "ro") -> Dict:
        """Daily briefing. Numbers/alerts are deterministic from Shopify; Gemini only adds ideas."""
        lang = normalize_lang(lang, "ro")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        base = self._fallback_briefing(snapshot, lang)
        if not is_connected(snapshot):
            return base

        prompt = f"""You are Jarvis, the AI assistant of the {BRAND} Shopify store ({DOMAIN}).
{BRAND_FACTS}
{CAPABILITIES}

STORE DATA (real, from Shopify — the ONLY numbers you may use):
{self._snapshot_to_text(snapshot)}

Write today's briefing ideas in {LANG_NAMES[lang]}. Return ONLY a JSON object:
{{"greeting": "one short friendly sentence",
  "top_tasks": [{{"task": "concrete action for the owner", "why": "short reason", "icon": "one emoji"}}],
  "traffic_tip": "one concrete content or SEO idea for this streetwear brand",
  "motivation": "one short sentence"}}
Rules: exactly 3 top_tasks; do not output any score; do not invent numbers, results or statistics;
tasks are things the owner does (Jarvis cannot act on the store)."""
        try:
            text = await self._call_gemini(prompt, json_mode=True, max_tokens=900)
            ai = self._validate_ai_briefing(self._parse_json_object(text))
        except Exception as e:
            print(f"[Briefing] Gemini unavailable, deterministic briefing used: {str(e)[:120]}")
            ai = {}
        if ai:
            base.update(ai)
            base["source"] = "gemini"
        base["health_score"] = None
        return base

    # ── Chat ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_lang(message: str) -> str:
        m = (message or "").lower()
        ro = ["salut", "bună", "buna", "vreau", "magazin", "vânzări", "vanzari", "comenzi", "mulțumesc",
              "multumesc", "te rog", "ajută", "ajuta", "clienți", "clienti", "de ce", "cum fac", "coș"]
        es = ["hola", "quiero", "tienda", "ventas", "pedidos", "gracias", "por favor", "ayuda", "clientes",
              "por qué", "cómo", "carrito"]
        if any(k in m for k in ro):
            return "ro"
        if any(k in m for k in es):
            return "es"
        return "en"

    def _data_line(self, snap: Dict, lang: str) -> str:
        if not is_connected(snap):
            return _pick({
                "ro": "⚠️ Shopify nu este conectat — nu am date reale despre magazin, așa că nu afișez cifre.",
                "en": "⚠️ Shopify is not connected — I have no real store data, so no numbers are shown.",
                "es": "⚠️ Shopify no está conectado: no tengo datos reales de la tienda, así que no muestro cifras.",
            }, lang)
        cur = snap.get("currency") or "EUR"
        o30 = _val(snap.get("orders_30d"), lang)
        carts = _val(snap.get("abandoned_carts"), lang)
        rev = snap.get("revenue_30d")
        revs = _val(None if rev is None else _fmt_money(rev), lang)
        return _pick({
            "ro": f"📊 Date reale Shopify: {o30} comenzi în 30 de zile ({revs} {cur}), {carts} coșuri abandonate în 7 zile.",
            "en": f"📊 Real Shopify data: {o30} orders in 30 days ({revs} {cur}), {carts} abandoned checkouts in 7 days.",
            "es": f"📊 Datos reales de Shopify: {o30} pedidos en 30 días ({revs} {cur}), {carts} carritos abandonados en 7 días.",
        }, lang)

    async def chat(self, shop_name: str, snapshot: Dict, history: List[Dict], message: str, lang: str = "ro") -> str:
        """Advisor chat. Respects `lang` (ro/en/es); never claims actions; no invented store numbers."""
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        msg = message or ""
        eff_lang = normalize_lang(lang, None) or self._detect_lang(msg)

        clean_input = re.sub(r"^[^\w/]+", "", msg.lower().strip()).strip()
        if clean_input.startswith("/boost") or clean_input.startswith("boost"):
            return self._build_boost_response(snapshot, shop_name, eff_lang, msg)
        if (clean_input.startswith("/browser") or clean_input.startswith("browser")
                or any(k in clean_input for k in ["radar trafic", "caută clienți", "găsește clienți", "gaseste clienti"])):
            return await self._build_radar_response(snapshot, shop_name, eff_lang, msg)
        if (clean_input.startswith("/goal") or clean_input.startswith("goal")
                or any(k in clean_input for k in ["simulator profit", "obiectiv vanzari", "țintă vanzari", "tinta vanzari"])):
            return self._build_goal_response(snapshot, shop_name, eff_lang, msg)

        history_str = ""
        for h in (history or [])[-6:]:
            if not isinstance(h, dict):
                continue
            role = "Owner" if h.get("role") == "user" else "Jarvis"
            history_str += f"{role}: {str(h.get('content') or '')[:1500]}\n"

        prompt = f"""You are Jarvis, the AI assistant inside the Shopify admin of {BRAND} ({DOMAIN}).
{BRAND_FACTS}
{CAPABILITIES}

STORE DATA:
{self._snapshot_to_text(snapshot)}

RULES: Use only numbers that appear in STORE DATA (earlier Jarvis messages may contain outdated or wrong numbers — ignore them). Present ideas as ideas, not as results.
No made-up statistics, benchmarks presented as facts, reviews, ratings, delivery times or return policies.
Reply in {LANG_NAMES[eff_lang]}, concise and structured (bullets, concrete steps, copy-ready texts when useful).

CONVERSATION:
{history_str}Owner: {msg[:4000]}
Jarvis:"""
        try:
            reply = await self._call_gemini(prompt, max_tokens=1200)
            if reply and len(reply.strip()) > 20:
                return reply.strip()
        except Exception as e:
            print(f"[Chat] Gemini unavailable, offline reply used: {str(e)[:120]}")

        return await self._autonomous_brain_reply(shop_name, snapshot, msg, eff_lang)

    async def _autonomous_brain_reply(self, shop_name: str, snapshot: Dict, message: str, lang: str = "ro") -> str:
        """Offline replies (no Gemini). Templates are ideas; store numbers only from the snapshot."""
        lang = normalize_lang(lang, "ro")
        msg_l = (message or "").lower()
        data_line = self._data_line(snapshot, lang)
        carts = snapshot.get("abandoned_carts") if is_connected(snapshot) else None
        carts_txt = _val(carts, lang) if is_connected(snapshot) else _pick(
            {"ro": "necunoscut (Shopify neconectat)", "en": "unknown (Shopify not connected)",
             "es": "desconocido (Shopify no conectado)"}, lang)
        offline_note = _pick({
            "ro": "\n\n_Răspuns offline (Gemini indisponibil). Conținutul de mai sus sunt idei, nu date._",
            "en": "\n\n_Offline reply (Gemini unavailable). The content above is ideas, not data._",
            "es": "\n\n_Respuesta sin conexión (Gemini no disponible). Lo anterior son ideas, no datos._",
        }, lang)

        def has(*keys):
            return any(k in msg_l for k in keys)

        # 1. No sales / how to sell
        if has("de ce nu am vanzari", "de ce nu am vânzări", "fara vanzari", "fără vânzări", "nu vând", "nu vand",
               "nu am comenzi", "nu se vinde", "cum fac vanzari", "cum fac vânzări", "cum aduc vanzari",
               "cum aduc vânzări", "cum cresc vanzarile", "cum cresc vânzările", "cum fac bani",
               "no sales", "why no sales", "how do i sell", "how to sell", "no tengo ventas", "sin ventas",
               "cómo vender", "como vender"):
            return _pick({
                "ro": f"""### 🧠 Diagnostic Imediat Vânzări
{data_line}

Vânzări = Trafic × Rata de conversie × Valoarea medie a comenzii. Verifică pe rând:

1. **Trafic** — Shopify → Analytics → Sesiuni. Jarvis nu citește sesiunile; dacă sunt puține, problema principală e traficul.
2. **Pagina de produs** — fotografii clare (inclusiv purtat), ghid de mărimi cu măsuri reale, gramajul (ex. 380 g/m² la crewneck), politica reală de livrare și retur din Shopify → Policies.
3. **Coșuri abandonate** — în 7 zile: {carts_txt}. Secvența Jarvis scrie doar clienților cu consimțământ de marketing.
4. **Încredere** — linkuri vizibile către politici, date de contact (info@maisongrozavu.com), recenzii doar dacă sunt reale.

### Plan de Acțiune în 3 Pași
1. Verifică sesiunile din ultimele 7 zile în Shopify Analytics.
2. Publică un clip scurt cu materialul și fit-ul unei piese, cu link direct către produs.
3. Deschide tabul SEO și aplică manual propunerile pentru produsele principale.{offline_note}""",
                "en": f"""### 🧠 Sales diagnosis
{data_line}

Sales = Traffic × Conversion rate × Average order value. Check in order:

1. **Traffic** — Shopify → Analytics → Sessions. Jarvis doesn't read sessions; if they are low, traffic is the main issue.
2. **Product page** — clear photos (including worn), size guide with real measurements, fabric weight (e.g. 380 g/m² crewneck), your real shipping and returns policy from Shopify → Policies.
3. **Abandoned checkouts** — last 7 days: {carts_txt}. Jarvis only messages customers with marketing consent.
4. **Trust** — visible policy links, contact details, reviews only if they are real.

### 3-step action plan
1. Check the last 7 days of sessions in Shopify Analytics.
2. Post a short clip showing the fabric and fit of one piece, linking straight to the product.
3. Open the SEO tab and manually apply the proposals for your main products.{offline_note}""",
                "es": f"""### 🧠 Diagnóstico de ventas
{data_line}

Ventas = Tráfico × Tasa de conversión × Ticket medio. Revisa por orden:

1. **Tráfico** — Shopify → Analytics → Sesiones. Jarvis no lee las sesiones; si son pocas, el problema principal es el tráfico.
2. **Ficha de producto** — fotos claras (también puestas), guía de tallas con medidas reales, gramaje (p. ej. 380 g/m² en la crewneck), tu política real de envíos y devoluciones de Shopify → Políticas.
3. **Carritos abandonados** — últimos 7 días: {carts_txt}. Jarvis solo escribe a clientes con consentimiento de marketing.
4. **Confianza** — enlaces visibles a las políticas, datos de contacto, reseñas solo si son reales.

### Plan de 3 pasos
1. Revisa las sesiones de los últimos 7 días en Shopify Analytics.
2. Publica un clip corto con el tejido y el fit de una prenda, con enlace directo al producto.
3. Abre la pestaña SEO y aplica a mano las propuestas para tus productos principales.{offline_note}""",
            }, lang)

        # 2. TikTok / Reels script
        if has("tiktok", "reels", "reel", "video viral", "script"):
            return _pick({
                "ro": f"""### 🎬 Script TikTok / Reels (idee, 20–30 s) — {BRAND}

- **0–3 s (hook):** prim-plan cu mâna care strânge materialul crewneck-ului. Text: „380 g/m². Așa arată un crewneck greu.”
- **3–10 s:** piesa purtată, din față și din spate; se vede logo-ul și fit-ul.
- **10–20 s:** detalii reale — gramaj, croială boxy la tricou (170 g/m²), cum cade la mișcare.
- **20–30 s (CTA):** „Designed in Spain. Link în bio.” — link direct către produs.

**Descriere (EN, pentru public ES/RO):** "Heavyweight 380 g/m² crewneck. Designed in Spain. Link in bio. #streetwear #heavyweight #grozavu"
Nu menționa reduceri sau stoc limitat decât dacă sunt reale.{offline_note}""",
                "en": f"""### 🎬 TikTok / Reels script (idea, 20–30s) — {BRAND}

- **0–3s (hook):** close-up of a hand squeezing the crewneck fabric. On-screen: "380 g/m². This is what heavyweight means."
- **3–10s:** the piece worn, front and back; logo and fit visible.
- **10–20s:** real details — weight, boxy tee fit (170 g/m²), how it moves.
- **20–30s (CTA):** "Designed in Spain. Link in bio." — link straight to the product.

**Caption:** "Heavyweight 380 g/m² crewneck. Designed in Spain. Link in bio. #streetwear #heavyweight #grozavu"
Only mention discounts or limited stock if they are real.{offline_note}""",
                "es": f"""### 🎬 Guion TikTok / Reels (idea, 20–30 s) — {BRAND}

- **0–3 s (gancho):** primer plano de una mano apretando el tejido de la crewneck. Texto: "380 g/m². Esto es una sudadera gruesa."
- **3–10 s:** la prenda puesta, de frente y de espaldas; se ven el logo y el fit.
- **10–20 s:** detalles reales — gramaje, fit boxy de la camiseta (170 g/m²), cómo cae al moverse.
- **20–30 s (CTA):** "Designed in Spain. Link en la bio." — enlace directo al producto.

**Descripción:** "Crewneck de 380 g/m². Designed in Spain. Link en la bio. #streetwear #grozavu"
Menciona descuentos o stock limitado solo si son reales.{offline_note}""",
            }, lang)

        # 3. Abandoned-cart recovery copy
        if has("recuperare", "abandonat", "abandonate", "email cos", "email coș", "recovery", "abandoned",
               "carrito abandonado", "recuperar"):
            return _pick({
                "ro": f"""### 📧 Email & WhatsApp de Recuperare (șablon, în engleză pentru magazin)
{data_line}

**Subiect:** "Your {BRAND} cart is still here"
**Email:**
> Hi [Name],
> You left [items] in your cart at {BRAND}. You can pick up where you left off here: [checkout link]
> Questions about sizing or shipping? Just reply to this email.
> — The {BRAND} team

**WhatsApp (doar cu consimțământ explicit pentru WhatsApp/SMS):**
> Hi [Name], it's {BRAND}. Your cart is saved here if you still want it: [checkout link]. Reply if you need help with sizing.

Reguli: nu promite că produsele sunt ținute deoparte pentru client și nu scrie că stocul e limitat (Shopify nu blochează stocul pentru coșurile abandonate). Codul MG10 folosit în pașii 2–3 ai secvenței Jarvis trebuie să existe în Shopify → Discounts. Emailurile Jarvis includ automat linkul de dezabonare.{offline_note}""",
                "en": f"""### 📧 Cart recovery email & WhatsApp (template)
{data_line}

**Subject:** "Your {BRAND} cart is still here"
> Hi [Name], you left [items] in your cart at {BRAND}. You can pick up where you left off here: [checkout link]. Questions about sizing or shipping? Just reply. — The {BRAND} team

**WhatsApp (only with explicit WhatsApp/SMS consent):**
> Hi [Name], it's {BRAND}. Your cart is saved here if you still want it: [checkout link].

Rules: don't promise items are held for the customer or that stock is limited (Shopify does not hold stock for abandoned checkouts). The MG10 code used in steps 2–3 of the Jarvis sequence must exist in Shopify → Discounts.{offline_note}""",
                "es": f"""### 📧 Email y WhatsApp de recuperación (plantilla)
{data_line}

**Asunto:** "Tu carrito de {BRAND} sigue aquí"
> Hola [Nombre], dejaste [productos] en tu carrito de {BRAND}. Puedes retomarlo aquí: [enlace]. ¿Dudas con la talla o el envío? Responde a este correo. — El equipo de {BRAND}

**WhatsApp (solo con consentimiento explícito):**
> Hola [Nombre], somos {BRAND}. Tu carrito sigue guardado aquí si lo quieres: [enlace].

Reglas: no prometas que los productos están apartados para el cliente ni que queda poco stock (Shopify no bloquea stock en carritos abandonados). El código MG10 de los pasos 2–3 debe existir en Shopify → Descuentos.{offline_note}""",
            }, lang)

        # 4. CRO audit
        if has("audit", "conversie", "cro", "imbunatatiri", "îmbunătățiri", "conversion", "conversión"):
            return _pick({
                "ro": f"""### 🔍 Audit Rapid de Conversie (listă de verificat)
{data_line}

1. **Trust sub butonul „Add to cart”:** linkuri către politica reală de livrare și retur (Shopify → Policies) și contact. Nu adăuga termene sau garanții care nu sunt în politici.
2. **Ghid de mărimi** cu măsuri reale pentru fit-ul boxy/oversized; gramajul în descriere (380 g/m² crewneck, 170 g/m² tee).
3. **Fotografii:** produs fără persoane + 4 fotografii cu model, verticale 4:5, cu logo-ul fidel produsului.
4. **Titluri și descrieri:** vezi propunerile din tabul SEO (doar previzualizare, le aplici tu).
5. **Checkout:** testează o comandă de probă de pe mobil.{offline_note}""",
                "en": f"""### 🔍 Quick conversion audit (checklist)
{data_line}

1. **Trust under "Add to cart":** links to your real shipping and returns policy (Shopify → Policies) and contact. Don't add delivery times or guarantees that aren't in your policies.
2. **Size guide** with real measurements for the boxy/oversized fit; fabric weight in the description (380 g/m² crewneck, 170 g/m² tee).
3. **Photos:** product shots without people + model photos, vertical 4:5, logo faithful to the product.
4. **Titles & descriptions:** see the SEO tab proposals (preview only, you apply them).
5. **Checkout:** place a test order from mobile.{offline_note}""",
                "es": f"""### 🔍 Auditoría rápida de conversión (lista)
{data_line}

1. **Confianza bajo "Añadir al carrito":** enlaces a tu política real de envíos y devoluciones (Shopify → Políticas) y contacto. No añadas plazos ni garantías que no estén en tus políticas.
2. **Guía de tallas** con medidas reales para el fit boxy/oversize; gramaje en la descripción (380 g/m² crewneck, 170 g/m² camiseta).
3. **Fotos:** producto sin personas + fotos con modelo, verticales 4:5, con el logo fiel al producto.
4. **Títulos y descripciones:** revisa las propuestas de la pestaña SEO (solo vista previa).
5. **Checkout:** haz un pedido de prueba desde el móvil.{offline_note}""",
            }, lang)

        # 5. VIP / loyalty
        if has("vip", "fidelizare", "clienti fideli", "clienți fideli", "loyalty", "fidelización"):
            repeat = snapshot.get("repeat_customers") if is_connected(snapshot) else None
            none_yet = _pick({
                "ro": "Încă nu există clienți recurenți în datele Shopify." if repeat == 0 else "",
                "en": "There are no repeat customers in the Shopify data yet." if repeat == 0 else "",
                "es": "Todavía no hay clientes recurrentes en los datos de Shopify." if repeat == 0 else "",
            }, lang)
            return _pick({
                "ro": f"""### 👑 Email de Fidelizare (șablon, EN)
{data_line} {none_yet}

**Subiect:** "Thank you for being one of the first {BRAND} customers"
> Hi [Name], thank you for your order. As a thank-you, here is code MGVIP15 for your next order. Wear it, enjoy it, and tell us what you think — just reply to this email.
> — The {BRAND} team

Codul MGVIP15 (folosit de automatizarea Jarvis post-livrare) trebuie creat în Shopify → Discounts. Reducerea nu se condiționează de o recenzie; trimite doar clienților cu consimțământ.{offline_note}""",
                "en": f"""### 👑 Loyalty email (template)
{data_line} {none_yet}

**Subject:** "Thank you for being one of the first {BRAND} customers"
> Hi [Name], thank you for your order. As a thank-you, here is code MGVIP15 for your next order. Tell us what you think — just reply. — The {BRAND} team

MGVIP15 (used by the Jarvis post-delivery automation) must exist in Shopify → Discounts. Never make the discount conditional on a review; send only to customers with consent.{offline_note}""",
                "es": f"""### 👑 Email de fidelización (plantilla)
{data_line} {none_yet}

**Asunto:** "Gracias por ser de los primeros clientes de {BRAND}"
> Hola [Nombre], gracias por tu pedido. Como agradecimiento, aquí tienes el código MGVIP15 para tu próximo pedido. Cuéntanos qué te parece respondiendo a este correo. — El equipo de {BRAND}

MGVIP15 debe existir en Shopify → Descuentos. El descuento nunca depende de una reseña; envía solo a clientes con consentimiento.{offline_note}""",
            }, lang)

        # 6. Post-purchase / reviews
        if has("post-cumparare", "post-cumpărare", "post livrare", "post-livrare", "recenzie", "review", "reseña", "post-compra"):
            return _pick({
                "ro": f"""### 📦 Secvență Post-Livrare (șablon, EN) — Recenzie opțională, separată de reducere
**Subiect:** "How is your {BRAND} piece?"
> Hi [Name], your order arrived a few days ago — we hope it fits the way you wanted.
> Care tip: wash inside out at 30°C and don't tumble dry to keep the print and the fabric in shape.
> If you have a minute, an honest review helps us a lot: [review link]
> — The {BRAND} team

Recenzia este opțională și nu se răsplătește condiționat (nu „5 stele pentru cod”). Verifică instrucțiunile de îngrijire pe eticheta reală a produsului.{offline_note}""",
                "en": f"""### 📦 Post-delivery email (template) — optional review, separate from any discount
**Subject:** "How is your {BRAND} piece?"
> Hi [Name], your order arrived a few days ago — we hope it fits the way you wanted. Care tip: wash inside out at 30°C, no tumble dryer. If you have a minute, an honest review helps a lot: [review link]. — The {BRAND} team

Reviews are optional and never rewarded conditionally (no "5 stars for a code"). Check care instructions against the real product label.{offline_note}""",
                "es": f"""### 📦 Email post-entrega (plantilla) — reseña opcional, separada de cualquier descuento
**Asunto:** "¿Qué tal tu prenda {BRAND}?"
> Hola [Nombre], tu pedido llegó hace unos días; esperamos que te quede como querías. Consejo: lávala del revés a 30 °C y sin secadora. Si tienes un minuto, una reseña sincera nos ayuda mucho: [enlace]. — El equipo de {BRAND}

La reseña es opcional y nunca se premia de forma condicionada. Comprueba las instrucciones de lavado en la etiqueta real.{offline_note}""",
            }, lang)

        # 7. Traffic / customers -> radar
        if has("trafic", "clienti", "clienți", "vizitatori", "aduc clienti", "aducem clienti", "traffic",
               "visitors", "tráfico", "trafico", "clientes"):
            return await self._build_radar_response(snapshot, shop_name, lang, message)

        # 8. Pricing / offers -> boost
        if has("pret", "preț", "reducere", "oferta", "ofertă", "bundle", "aov", "cos ", "coș", "discount",
               "price", "offer", "precio", "oferta", "descuento"):
            return self._build_boost_response(snapshot, shop_name, lang, message)

        # 9. SEO
        if has("seo", "google", "cuvinte cheie", "ranking", "indexare", "snippets", "keywords", "palabras clave"):
            seo = self.generate_seo_strategy(shop_name, DOMAIN)
            kws = "\n".join(f"  • {k['keyword']} ({k['market']})" for k in seo["keywords"][:8])
            return _pick({
                "ro": f"""### 🌐 Strategie Google SEO (idei)

**Cuvinte cheie de testat** (fără volume — verifică-le în Google Keyword Planner sau Search Console):
{kws}

**Date structurate:** majoritatea temelor Shopify generează deja date structurate Product. Nu lipi cod JSON-LD manual în `theme.liquid` — verifică o pagină de produs cu Google Rich Results Test; nu adăuga niciodată rating-uri sau recenzii care nu există.

**Pași:** titluri și descrieri din tabul SEO (previzualizare, le aplici tu); sitemap-ul magazinului: https://{DOMAIN}/sitemap.xml — trimite-l în Google Search Console.{offline_note}""",
                "en": f"""### 🌐 Google SEO strategy (ideas)

**Keywords to test** (no volumes — check them in Google Keyword Planner or Search Console):
{kws}

**Structured data:** most Shopify themes already output Product structured data. Don't paste JSON-LD into `theme.liquid` by hand — test a product page with Google's Rich Results Test, and never add ratings or reviews that don't exist.

**Steps:** titles and descriptions from the SEO tab (preview, you apply them); sitemap: https://{DOMAIN}/sitemap.xml — submit it in Google Search Console.{offline_note}""",
                "es": f"""### 🌐 Estrategia SEO en Google (ideas)

**Palabras clave para probar** (sin volúmenes — compruébalas en Google Keyword Planner o Search Console):
{kws}

**Datos estructurados:** la mayoría de temas de Shopify ya generan datos estructurados de producto. No pegues JSON-LD a mano en `theme.liquid`; prueba una ficha con Rich Results Test de Google y nunca añadas valoraciones que no existan.

**Pasos:** títulos y descripciones desde la pestaña SEO (vista previa); sitemap: https://{DOMAIN}/sitemap.xml — envíalo en Google Search Console.{offline_note}""",
            }, lang)

        # 10. Ads copy
        if has("reclama", "reclame", "ad copy", "facebook ads", "meta ads", "facebook", "instagram ads", "anuncio", "ads"):
            return _pick({
                "ro": f"""### 🎯 Texte pentru reclame Meta (idei, în engleză pentru ES/RO)

**Unghi 1 — Material:**
- Text: "Heavyweight 380 g/m² crewneck. Boxy fit. Designed in Spain."
- Titlu: "{BRAND} — Premium streetwear"
- CTA: Shop now

**Unghi 2 — Fit:**
- Text: "Boxy tees cut to sit right. 170 g/m² cotton, designed in Spain."
- Titlu: "The boxy tee by {BRAND}"

Testează fiecare unghi cu buget mic și urmărește rezultatele reale în Meta Ads Manager. Nu promite termene de livrare sau reduceri care nu există.{offline_note}""",
                "en": f"""### 🎯 Meta ad copy (ideas)

**Angle 1 — Fabric:** "Heavyweight 380 g/m² crewneck. Boxy fit. Designed in Spain." · Headline: "{BRAND} — Premium streetwear" · CTA: Shop now
**Angle 2 — Fit:** "Boxy tees cut to sit right. 170 g/m², designed in Spain." · Headline: "The boxy tee by {BRAND}"

Test each angle with a small budget and judge by real results in Ads Manager. Don't promise delivery times or discounts that don't exist.{offline_note}""",
                "es": f"""### 🎯 Textos para anuncios de Meta (ideas)

**Ángulo 1 — Tejido:** "Crewneck de 380 g/m². Fit boxy. Designed in Spain." · Título: "{BRAND} — Streetwear premium" · CTA: Comprar
**Ángulo 2 — Fit:** "Camisetas boxy de 170 g/m², designed in Spain." · Título: "La camiseta boxy de {BRAND}"

Prueba cada ángulo con poco presupuesto y decide con los resultados reales de Ads Manager. No prometas plazos ni descuentos que no existan.{offline_note}""",
            }, lang)

        # Default
        return _pick({
            "ro": f"""{data_line}

Pot să te ajut cu idei și texte (nu pot modifica magazinul sau trimite mesaje):
1. **/boost** — idei de ofertă și pachete (le creezi tu în Shopify).
2. **/browser** — sugestii Google Autocomplete pentru un termen + idei de conținut.
3. **/goal 2500** — calculul comenzilor și vizitatorilor necesari pentru o țintă (ex. /goal 2500 aov 70).

Spune-mi ce vrei să lucrăm.{offline_note}""",
            "en": f"""{data_line}

I can help with ideas and copy (I can't change the store or send messages):
1. **/boost** — offer and bundle ideas (you create them in Shopify).
2. **/browser** — Google Autocomplete suggestions for a term + content ideas.
3. **/goal 2500** — orders and visitors needed for a target (e.g. /goal 2500 aov 70).

What would you like to work on?{offline_note}""",
            "es": f"""{data_line}

Puedo ayudarte con ideas y textos (no puedo modificar la tienda ni enviar mensajes):
1. **/boost** — ideas de ofertas y packs (los creas tú en Shopify).
2. **/browser** — sugerencias de Google Autocomplete para un término + ideas de contenido.
3. **/goal 2500** — pedidos y visitas necesarios para un objetivo (p. ej. /goal 2500 aov 70).

¿En qué trabajamos?{offline_note}""",
        }, lang)

    # ── Slash commands ────────────────────────────────────────────────────────

    def _build_boost_response(self, snapshot: Dict, shop_name: str, lang: str = "ro", message: str = "") -> str:
        lang = normalize_lang(lang, "ro")
        plan = self.generate_boost_plan(snapshot, shop_name, lang)
        data_line = self._data_line(snapshot, lang)
        return _pick({
            "ro": f"""### ⚡ /boost — Idei de ofertă (nu sunt aplicate automat)
{data_line}

1. **Banner (Urgency bar), doar cu informații reale:** "{plan['urgency_banner']}"
2. **Cart bump:** {plan['cart_bump']['product_title']} — "{plan['cart_bump']['copy']}"
3. **Bundle:** {plan['bundle']['title']} — alegi tu reducerea; creeaz-o în Shopify → Discounts.
4. **Coșuri abandonate:** secvența Jarvis folosește codul MG10 în pașii 2–3, doar pentru clienții cu consimțământ. Verifică să existe codul în Shopify → Discounts.

Jarvis nu poate activa oferte, bannere sau reduceri — le configurezi tu în Shopify Admin (Discounts / Online Store → Themes).""",
            "en": f"""### ⚡ /boost — Offer ideas (nothing is applied automatically)
{data_line}

1. **Urgency bar, real info only:** "{plan['urgency_banner']}"
2. **Cart bump:** {plan['cart_bump']['product_title']} — "{plan['cart_bump']['copy']}"
3. **Bundle:** {plan['bundle']['title']} — you choose the discount and create it in Shopify → Discounts.
4. **Abandoned checkouts:** the Jarvis sequence uses code MG10 in steps 2–3, only for customers with consent. Make sure the code exists in Shopify → Discounts.

Jarvis can't activate offers, banners or discounts — you set them up in Shopify Admin.""",
            "es": f"""### ⚡ /boost — Ideas de oferta (no se aplica nada automáticamente)
{data_line}

1. **Barra de anuncio, solo con información real:** "{plan['urgency_banner']}"
2. **Cart bump:** {plan['cart_bump']['product_title']} — "{plan['cart_bump']['copy']}"
3. **Pack:** {plan['bundle']['title']} — eliges el descuento y lo creas en Shopify → Descuentos.
4. **Carritos abandonados:** la secuencia de Jarvis usa el código MG10 en los pasos 2–3, solo con consentimiento. Comprueba que el código existe en Shopify → Descuentos.

Jarvis no puede activar ofertas, banners ni descuentos: los configuras tú en Shopify Admin.""",
        }, lang)

    async def _build_radar_response(self, snapshot: Dict, shop_name: str, lang: str = "ro", message: str = "") -> str:
        lang = normalize_lang(lang, "ro")
        extracted = ""
        if message:
            m_clean = re.sub(r"^/?browser\s*", "", message.strip(), flags=re.I).strip()
            m_clean = re.sub(r"^[^\w\s]+", "", m_clean).strip()
            if len(m_clean) > 2 and not any(k in m_clean.lower() for k in ["radar", "clienti", "clienți", "trafic", "traffic"]):
                extracted = m_clean
        search_term = extracted or DEFAULT_SUGGEST_QUERY
        suggest = await self.fetch_google_suggest(search_term, lang)
        radar = self.generate_lead_radar(shop_name, lang)
        hooks = "\n".join(f"- **{h['title']}:** {h['script']}" for h in radar["hooks"])

        if suggest["source"] == "google_suggest" and suggest["results"]:
            sug_lines = "\n".join(f"  • „{kw}”" for kw in suggest["results"])
            sug_block = _pick({
                "ro": f"Sugestii Google Autocomplete pentru „{suggest['query']}” (fără volume de căutare):\n{sug_lines}",
                "en": f"Google Autocomplete suggestions for \"{suggest['query']}\" (no search volumes):\n{sug_lines}",
                "es": f"Sugerencias de Google Autocomplete para \"{suggest['query']}\" (sin volúmenes de búsqueda):\n{sug_lines}",
            }, lang)
        elif suggest["source"] == "google_suggest":
            sug_block = _pick({
                "ro": f"Google Autocomplete nu a returnat sugestii pentru „{suggest['query']}”.",
                "en": f"Google Autocomplete returned no suggestions for \"{suggest['query']}\".",
                "es": f"Google Autocomplete no devolvió sugerencias para \"{suggest['query']}\".",
            }, lang)
        else:
            sug_block = _pick({
                "ro": f"Google Autocomplete nu a răspuns acum pentru „{suggest['query']}” — nu afișez sugestii inventate. Încearcă din nou mai târziu.",
                "en": f"Google Autocomplete did not respond for \"{suggest['query']}\" — no invented suggestions are shown. Try again later.",
                "es": f"Google Autocomplete no respondió para \"{suggest['query']}\": no muestro sugerencias inventadas. Inténtalo más tarde.",
            }, lang)

        return _pick({
            "ro": f"""### 🌐 Radar Clienți (/browser) — {BRAND}

#### 1. 🔍 Google
{sug_block}
Folosește expresiile relevante în titlurile și descrierile produselor (tabul SEO).

#### 2. 📱 Idei TikTok / Reels
{hooks}

#### 3. 💌 Mesaj de Outreach către creatori (EN, copy-paste)
> {radar['outreach_dm']}

Acestea sunt idei; Jarvis nu trimite mesaje și nu caută clienți singur.""",
            "en": f"""### 🌐 Customer radar (/browser) — {BRAND}

#### 1. 🔍 Google
{sug_block}
Use the relevant phrases in product titles and descriptions (SEO tab).

#### 2. 📱 TikTok / Reels ideas
{hooks}

#### 3. 💌 Creator outreach message (copy-paste)
> {radar['outreach_dm']}

These are ideas; Jarvis doesn't send messages or look for customers on its own.""",
            "es": f"""### 🌐 Radar de clientes (/browser) — {BRAND}

#### 1. 🔍 Google
{sug_block}
Usa las expresiones relevantes en títulos y descripciones (pestaña SEO).

#### 2. 📱 Ideas para TikTok / Reels
{hooks}

#### 3. 💌 Mensaje para creadores (copiar y pegar)
> {radar['outreach_dm_es']}

Son ideas; Jarvis no envía mensajes ni busca clientes por su cuenta.""",
        }, lang)

    def _build_goal_response(self, snapshot: Dict, shop_name: str, lang: str = "ro", message: str = "") -> str:
        lang = normalize_lang(lang, "ro")
        target, aov_msg, curr_msg = parse_goal_message(message)
        connected = is_connected(snapshot)
        curr = curr_msg or (snapshot.get("currency") if connected else None) or "EUR"
        if not target or target <= 0:
            target = None

        aov, aov_source = None, None
        if aov_msg and aov_msg > 0:
            aov, aov_source = aov_msg, "provided"
        elif connected and (snapshot.get("orders_30d") or 0) > 0 and (snapshot.get("aov") or 0) > 0 \
                and (not curr_msg or curr_msg == snapshot.get("currency")):
            aov, aov_source = float(snapshot["aov"]), "shopify"
        elif connected and (snapshot.get("avg_product_price") or 0) > 0 \
                and (not curr_msg or curr_msg == snapshot.get("currency")):
            aov, aov_source = float(snapshot["avg_product_price"]), "avg_product_price"

        if target is None:
            return _pick({
                "ro": "### 🎯 Simulator & Obiectiv de Profit (/goal)\nScrie ținta lunară, de exemplu `/goal 2500` sau `/goal 2.500,50 EUR aov 70`.",
                "en": "### 🎯 Revenue goal (/goal)\nWrite the monthly target, e.g. `/goal 2500` or `/goal 2500.50 EUR aov 70`.",
                "es": "### 🎯 Objetivo de ingresos (/goal)\nEscribe el objetivo mensual, p. ej. `/goal 2500` o `/goal 2.500,50 EUR aov 70`.",
            }, lang)

        if aov is None:
            return _pick({
                "ro": f"""### 🎯 Simulator & Obiectiv de Profit (/goal)
Țintă: **{target:,.2f} {curr} / lună**.
Nu am o valoare medie a comenzii reală (nu există comenzi în date{'' if connected else ' — Shopify nu este conectat'}). Spune-mi ce AOV vrei să folosim, de exemplu `/goal {target:g} aov 70`.""",
                "en": f"""### 🎯 Revenue goal (/goal)
Target: **{target:,.2f} {curr} / month**.
I don't have a real average order value ({'no orders in the data' if connected else 'Shopify is not connected'}). Tell me which AOV to use, e.g. `/goal {target:g} aov 70`.""",
                "es": f"""### 🎯 Objetivo de ingresos (/goal)
Objetivo: **{target:,.2f} {curr} / mes**.
No tengo un ticket medio real ({'no hay pedidos en los datos' if connected else 'Shopify no está conectado'}). Dime qué ticket medio usar, p. ej. `/goal {target:g} aov 70`.""",
            }, lang)

        g = self.calculate_revenue_goal(target, curr, aov, 30, aov_source=aov_source)
        src_label = {
            "provided": {"ro": "valoarea dată de tine", "en": "the value you gave", "es": "el valor que indicaste"},
            "shopify": {"ro": "AOV real din Shopify (30 zile)", "en": "real Shopify AOV (30 days)", "es": "ticket medio real de Shopify (30 días)"},
            "avg_product_price": {"ro": "prețul mediu al produselor active (nu un AOV real)", "en": "average active product price (not a real AOV)", "es": "precio medio de los productos activos (no un ticket real)"},
        }[aov_source][lang]
        sc = g["scenarios"]
        return _pick({
            "ro": f"""### 🎯 Simulator & Obiectiv de Profit (/goal)

#### 📊 Ecuația Profitului
- **Țintă:** {target:,.2f} {curr} / lună
- **Valoare medie comandă:** {aov:,.2f} {curr} — sursa: {src_label}
- **Comenzi necesare:** {g['needed_orders']} / lună (~{g['daily_orders']} pe zi)
- **Vizitatori necesari** (ipoteze de conversie, nu date ale magazinului):
  • la {sc['cr_1_5']['cr']}: {sc['cr_1_5']['total_visitors']:,} / lună (~{sc['cr_1_5']['daily_visitors']:,}/zi)
  • la {sc['cr_2_0']['cr']}: {sc['cr_2_0']['total_visitors']:,} / lună (~{sc['cr_2_0']['daily_visitors']:,}/zi)
  • la {sc['cr_2_5']['cr']}: {sc['cr_2_5']['total_visitors']:,} / lună (~{sc['cr_2_5']['daily_visitors']:,}/zi)

Compară cu sesiunile reale din Shopify → Analytics ca să vezi distanța până la țintă.""",
            "en": f"""### 🎯 Revenue goal (/goal)

- **Target:** {target:,.2f} {curr} / month
- **Average order value:** {aov:,.2f} {curr} — source: {src_label}
- **Orders needed:** {g['needed_orders']} / month (~{g['daily_orders']} per day)
- **Visitors needed** (conversion-rate assumptions, not store data):
  • at {sc['cr_1_5']['cr']}: {sc['cr_1_5']['total_visitors']:,} / month (~{sc['cr_1_5']['daily_visitors']:,}/day)
  • at {sc['cr_2_0']['cr']}: {sc['cr_2_0']['total_visitors']:,} / month (~{sc['cr_2_0']['daily_visitors']:,}/day)
  • at {sc['cr_2_5']['cr']}: {sc['cr_2_5']['total_visitors']:,} / month (~{sc['cr_2_5']['daily_visitors']:,}/day)

Compare with your real sessions in Shopify → Analytics.""",
            "es": f"""### 🎯 Objetivo de ingresos (/goal)

- **Objetivo:** {target:,.2f} {curr} / mes
- **Ticket medio:** {aov:,.2f} {curr} — fuente: {src_label}
- **Pedidos necesarios:** {g['needed_orders']} / mes (~{g['daily_orders']} al día)
- **Visitas necesarias** (supuestos de conversión, no datos de la tienda):
  • al {sc['cr_1_5']['cr']}: {sc['cr_1_5']['total_visitors']:,} / mes (~{sc['cr_1_5']['daily_visitors']:,}/día)
  • al {sc['cr_2_0']['cr']}: {sc['cr_2_0']['total_visitors']:,} / mes (~{sc['cr_2_0']['daily_visitors']:,}/día)
  • al {sc['cr_2_5']['cr']}: {sc['cr_2_5']['total_visitors']:,} / mes (~{sc['cr_2_5']['daily_visitors']:,}/día)

Compáralo con tus sesiones reales en Shopify → Analytics.""",
        }, lang)

    # ── Growth endpoints (ideas, no metrics) ──────────────────────────────────

    def generate_seo_strategy(self, shop_name: str = BRAND, domain: str = DOMAIN,
                              products: Optional[List[Dict[str, Any]]] = None,
                              currency: str = "EUR", lang: str = "ro") -> Dict[str, Any]:
        """
        Keyword IDEAS (no volume / CPC / difficulty — Jarvis has no keyword data source) and, when
        real products are passed, a JSON-LD preview built from the first real product (no ratings).
        """
        kw = [
            ("heavyweight hoodie", "Comercial", "EN · ES/RO"),
            ("heavyweight crewneck sweatshirt", "Comercial", "EN · ES/RO"),
            ("oversized boxy t-shirt", "Comercial", "EN · ES/RO"),
            ("premium streetwear brand", "Informațional/Comercial", "EN"),
            ("streetwear designed in Spain", "Brand/Comercial", "EN"),
            ("sudadera oversize", "Comercial", "ES"),
            ("camiseta boxy fit", "Comercial", "ES"),
            ("hanorac oversize", "Comercial", "RO"),
            ("tricou oversize", "Comercial", "RO"),
        ]
        keywords = [{"keyword": k, "intent": i, "market": m, "volume": None, "difficulty": None, "cpc": None,
                     "source": "idea"} for k, i, m in kw]

        json_ld, json_ld_product = None, None
        real = [p for p in (products or []) if isinstance(p, dict) and p.get("id") and p.get("title")]
        if real:
            try:
                try:
                    from seo_optimizer import ProductSEOOptimizer
                except ImportError:  # pragma: no cover
                    from backend.seo_optimizer import ProductSEOOptimizer
                active = [p for p in real if str(p.get("status") or "active").lower() == "active"] or real
                json_ld_product = active[0]
                json_ld = ProductSEOOptimizer(brand_name=BRAND, domain=domain).generate_json_ld_schema(
                    json_ld_product, currency=currency)
            except Exception as e:
                print(f"[SEO strategy] JSON-LD preview failed: {e}")
                json_ld = None

        return {
            "kind": "ideas",
            "source": "template",
            "label": "Idei de cuvinte cheie — fără volume, CPC sau dificultate (nu avem o sursă de date pentru ele).",
            "keywords": keywords,
            "keyword_data_note": "Verifică volumele reale în Google Keyword Planner sau Google Search Console.",
            "json_ld": json_ld,
            "json_ld_product_id": str(json_ld_product.get("id")) if json_ld_product else None,
            "json_ld_note": ("Previzualizare din date reale de produs, fără rating-uri. Majoritatea temelor Shopify "
                             "generează deja aceste date — verifică cu Google Rich Results Test înainte să adaugi ceva; "
                             "nu lipi cod în theme.liquid fără verificare.") if json_ld else
                            "Nicio previzualizare JSON-LD: nu au fost primite produse reale din Shopify.",
            "merchant_feed_tips": [
                f"Titlu: [Brand] + [Tip produs] + [Detaliu real] + [Culoare] (ex: {BRAND} Heavyweight Crewneck Black).",
                "Imagini clare ale produsului, fără text promoțional sau watermark (cerință Google Merchant Center).",
                "Atribute: brand, condition=new, age_group, color, size, gender potrivit fiecărui produs.",
                "Prețul și disponibilitatea din feed trebuie să coincidă cu pagina de produs.",
            ],
            "sitemap_url": f"https://{domain}/sitemap.xml",
            "robots_recommendation": "Trimite sitemap-ul în Google Search Console și verifică acolo indexarea paginilor de produs.",
        }

    def generate_lead_radar(self, shop_name: str = BRAND, lang: str = "ro") -> Dict[str, Any]:
        """Content hooks, outreach templates and audience ideas — clearly labelled as ideas."""
        brand = _customer_brand(shop_name)
        hooks = [
            {"title": "Hook material (TikTok/Reels)", "duration": "15–20s",
             "script": "Prim-plan cu mâna care strânge materialul: „380 g/m². Așa arată un crewneck greu.” Apoi piesa purtată, față/spate. CTA: link în bio.",
             "best_sound": "Sunet trending din nișa streetwear (alege-l în aplicație)"},
            {"title": "Hook fit boxy", "duration": "15s",
             "script": "Tricoul boxy (170 g/m²) purtat de două persoane cu mărimi diferite — cum cade umărul și lungimea. Text: „Boxy fit, designed in Spain.”",
             "best_sound": "Beat hip-hop / lo-fi"},
            {"title": "Hook detaliu logo", "duration": "10–15s",
             "script": "Macro pe logo-ul GROZAVU, apoi tranziție la ținuta completă. Fără afirmații despre stoc sau reduceri dacă nu sunt reale.",
             "best_sound": "Sunet trending scurt"},
        ]
        outreach_dm = (
            f"Hi [Name]! I run {brand}, a streetwear brand designed in Spain. I like how you style oversized fits. "
            "Would you be open to receiving a piece from our collection? No obligation — if you like it, a story or post would mean a lot. "
            "Let me know your size and I'll send the details."
        )
        outreach_dm_es = (
            f"¡Hola [Nombre]! Llevo {brand}, una marca de streetwear diseñada en España. Me gusta cómo combinas los fits oversize. "
            "¿Te gustaría recibir una prenda de la colección? Sin compromiso: si te gusta, una story o un post nos ayudaría mucho. "
            "Dime tu talla y te paso los detalles."
        )
        outreach_dm_ro = (
            f"Salut [Nume]! Am brandul {brand}, streetwear designed in Spain. Îmi place cum stilizezi fit-urile oversized. "
            "Ai vrea să primești o piesă din colecție? Fără obligații — dacă îți place, un story sau o postare ne-ar ajuta mult. "
            "Spune-mi ce mărime porți și îți trimit detaliile."
        )
        personas = [
            {"name": "Fan streetwear urban (Spania, 18–30)",
             "interests": "Fit-uri oversized/boxy, materiale groase, branduri mici",
             "trigger": "Ipoteză: calitatea materialului vizibilă în clip și fit-ul corect."},
            {"name": "Public streetwear din România (18–30)",
             "interests": "Hanorace și tricouri oversize, logo discret",
             "trigger": "Ipoteză: piese care arată bine în poze și sunt ușor de combinat."},
        ]
        return {
            "kind": "ideas",
            "source": "template",
            "label": "Idei de conținut și outreach — nu sunt date; rezultatele trebuie măsurate.",
            "hooks": hooks,
            "outreach_dm": outreach_dm,
            "outreach_dm_es": outreach_dm_es,
            "outreach_dm_ro": outreach_dm_ro,
            "personas": personas,
            "active_channels": ["Google Search", "Instagram Reels", "TikTok", "Pinterest"],
        }

    def generate_boost_plan(self, snapshot: Dict, shop_name: str = BRAND, lang: str = "ro") -> Dict[str, Any]:
        """Offer ideas the owner may create in Shopify. No prices, discounts or savings are invented."""
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        connected = is_connected(snapshot)
        return {
            "kind": "ideas",
            "source": "template",
            "connected": connected,
            "label": "Idei — Jarvis nu aplică nimic în magazin. Creezi ofertele în Shopify Admin → Discounts.",
            "abandoned_carts": snapshot.get("abandoned_carts") if connected else None,
            "urgency_banner": "NEW DROP — Heavyweight 380 g/m² crewnecks. Designed in Spain.",
            "urgency_banner_note": "Folosește doar informații adevărate (fără „stoc limitat” sau termene inventate).",
            "cart_bump": {
                "product_title": "Șapcă sau sling bag (alege un produs real din magazin)",
                "copy": f"Complete the fit with the {BRAND} cap.",
                "regular_price": None,
                "bump_price": None,
                "discount": None,
            },
            "bundle": {
                "title": "Pachet hoodie + șapcă (idee)",
                "copy": f"Hoodie + cap — the full {BRAND} fit.",
                "discount_pct": None,
                "promo_code": None,
                "savings": None,
            },
            "recovery_promo": {
                "code": "MG10",
                "discount": None,
                "urgency_hours": None,
                "note": "Codul folosit de secvența Jarvis în pașii 2–3; trebuie să existe în Shopify → Discounts. "
                        "Se trimite doar clienților cu consimțământ.",
            },
        }

    def calculate_revenue_goal(self, target_amount: float = 10000.0, currency: str = "EUR",
                               current_aov: Optional[float] = None, days: int = 30,
                               aov_source: Optional[str] = None) -> Dict[str, Any]:
        """Math only. Without a real/provided AOV nothing is computed (no invented default AOV)."""
        days = max(1, int(days or 30))
        try:
            target = float(target_amount or 0)
        except (TypeError, ValueError):
            target = 0.0
        try:
            aov = float(current_aov) if current_aov is not None else None
        except (TypeError, ValueError):
            aov = None
        if not aov or aov <= 0 or target <= 0:
            return {
                "target_amount": target, "currency": currency, "days": days,
                "aov": None, "aov_source": "unavailable",
                "needed_orders": None, "daily_orders": None,
                "scenarios": {}, "channel_split": {},
                "note": "Nu există o valoare medie a comenzii reală — introdu un AOV ca să calculez planul.",
            }

        def ceil_safe(x: float) -> int:
            return int(math.ceil(round(x, 6)))

        needed_orders = max(1, ceil_safe(target / aov))
        daily_orders = round(needed_orders / days, 1)
        scenarios = {}
        for key, cr in (("cr_1_5", 0.015), ("cr_2_0", 0.020), ("cr_2_5", 0.025)):
            total = ceil_safe(needed_orders / cr)
            scenarios[key] = {"cr": f"{cr * 100:.1f}%", "total_visitors": total,
                              "daily_visitors": ceil_safe(total / days)}
        target_daily = scenarios["cr_2_0"]["daily_visitors"]
        channel_split = {
            "google_search": {"share": "40%", "visitors_day": int(target_daily * 0.4)},
            "tiktok_reels": {"share": "40%", "visitors_day": int(target_daily * 0.4)},
            "email_retention": {"share": "20%", "visitors_day": int(target_daily * 0.2)},
        }
        return {
            "target_amount": target,
            "currency": currency,
            "aov": aov,
            "aov_source": aov_source or "provided",
            "days": days,
            "needed_orders": needed_orders,
            "daily_orders": daily_orders,
            "scenarios": scenarios,
            "channel_split": channel_split,
            "assumptions": {
                "conversion_rates": "Ipoteze (1,5% / 2% / 2,5%), nu date ale magazinului.",
                "channel_split": "Exemplu ilustrativ de împărțire a traficului, nu date.",
            },
        }

    # ── Abandoned cart recovery copy ──────────────────────────────────────────

    async def generate_autonomous_recovery(self, shop_name: str, checkout: Dict, lang: str = "ro",
                                           discount_code: Optional[str] = "MG10",
                                           discount_percent: Optional[int] = None) -> Dict:
        """
        Personalised recovery copy (email subject/body + WhatsApp text) in the customer's language.
        Never claims items are reserved or stock is low (Shopify does not reserve stock and the
        brand is made to order). Mentions a discount only when `discount_code` is given.
        """
        checkout = checkout if isinstance(checkout, dict) else {}
        detected_lang = (lang or checkout.get("detected_lang") or "en").lower()[:2]
        lang_names = {"it": "Italian", "es": "Spanish", "de": "German", "fr": "French", "ro": "Romanian", "en": "English"}
        lang_name = lang_names.get(detected_lang, "English")
        brand = _customer_brand(shop_name)
        items = [i for i in (checkout.get("items") or []) if i and i != "Produse din coș"]
        items_default = {"it": "i tuoi articoli", "es": "tus artículos", "de": "deine Artikel",
                         "fr": "vos articles", "ro": "produsele tale", "en": "your items"}
        items_str = ", ".join(items) or items_default.get(detected_lang, "your items")
        cust_name = checkout.get("customer_name") or ""
        if cust_name in ("Client", "Cumpărător"):
            cust_name = ""
        url = checkout.get("checkout_url") or checkout.get("abandoned_checkout_url") or ""
        code = (discount_code or "").strip() or None
        pct = discount_percent if discount_percent else (10 if code and code.upper() == "MG10" else None)

        discount_rule = (f"Offer the discount code '{code}'" + (f" ({pct}% off)" if pct else "") +
                         " exactly once.") if code else "Do not mention any discount."
        prompt = f"""Write an abandoned-cart reminder for the streetwear brand "{brand}" ({DOMAIN}).
{BRAND_FACTS}
Customer first name: {'write the placeholder {{NAME}} where the first name goes' if cust_name else '(unknown — use a neutral greeting)'}; country: {checkout.get('detected_country') or 'unknown'}.
Language: write 100% in {lang_name}.
Cart items: {items_str}. Checkout link: write exactly the placeholder {{CHECKOUT_URL}} (it is replaced later; do not write any other link).
{discount_rule}
Do NOT say the items are reserved or held, do NOT mention low stock, countdowns or deadlines, do NOT invent shipping times or return policies.
Tone: friendly, short, helpful (offer help with sizing).
Return ONLY JSON: {{"subject": "max 8 words", "body": "email body with the checkout link", "whatsapp_message": "short message with the checkout link"}}"""

        try:
            text = await self._call_gemini(prompt, json_mode=True, max_tokens=700)
            parsed = self._parse_json_object(text)
            if parsed and isinstance(parsed.get("subject"), str) and isinstance(parsed.get("body"), str) \
                    and parsed["subject"].strip() and parsed["body"].strip():
                wa = parsed.get("whatsapp_message")
                candidate = {
                    "subject": parsed["subject"].strip()[:150],
                    "body": parsed["body"].strip()[:3000],
                    "whatsapp_message": (wa.strip() if isinstance(wa, str) and wa.strip() else parsed["body"].strip())[:1000],
                }
                for k in candidate:  # personal data never went to Gemini; fill it in here
                    candidate[k] = candidate[k].replace("{{NAME}}", cust_name).replace("{{CHECKOUT_URL}}", url)
                problem = validate_recovery_copy(candidate, url, code)
                if not problem:
                    candidate["source"] = "gemini"
                    return candidate
                print(f"[Recovery copy] Gemini text rejected ({problem}); template used")
        except Exception as e:
            print(f"[Recovery copy] Gemini unavailable, template used: {str(e)[:120]}")

        return self._recovery_template(detected_lang, brand, cust_name, items_str, url, code, pct)

    @staticmethod
    def _recovery_template(lang: str, brand: str, name: str, items: str, url: str,
                           code: Optional[str], pct: Optional[int]) -> Dict[str, str]:
        p = f" ({pct}%)" if pct else ""
        T = {
            "it": {"hi": f"Ciao {name}," if name else "Ciao,",
                   "subject": f"Il tuo carrello {brand} ti aspetta",
                   "line": f"hai lasciato {items} nel carrello su {brand}. Puoi riprendere da dove avevi lasciato qui:",
                   "code": f"Usa il codice {code}{p} al checkout.",
                   "help": "Hai domande su taglie o spedizione? Rispondi a questa email.",
                   "sign": f"Il team {brand}",
                   "wa": f"Ciao{(' ' + name) if name else ''}! Siamo {brand}. Il tuo carrello è qui se lo vuoi ancora:"},
            "es": {"hi": f"Hola {name}," if name else "Hola,",
                   "subject": f"Tu carrito de {brand} sigue aquí",
                   "line": f"dejaste {items} en tu carrito de {brand}. Puedes retomarlo aquí:",
                   "code": f"Usa el código {code}{p} en el checkout.",
                   "help": "¿Dudas con la talla o el envío? Responde a este correo.",
                   "sign": f"El equipo de {brand}",
                   "wa": f"¡Hola{(' ' + name) if name else ''}! Somos {brand}. Tu carrito sigue aquí si lo quieres:"},
            "de": {"hi": f"Hallo {name}," if name else "Hallo,",
                   "subject": f"Dein {brand} Warenkorb wartet",
                   "line": f"du hast {items} im Warenkorb bei {brand} gelassen. Hier kannst du weitermachen:",
                   "code": f"Nutze den Code {code}{p} an der Kasse.",
                   "help": "Fragen zu Größe oder Versand? Antworte einfach auf diese E-Mail.",
                   "sign": f"Dein {brand} Team",
                   "wa": f"Hallo{(' ' + name) if name else ''}! Hier ist {brand}. Dein Warenkorb ist noch da:"},
            "fr": {"hi": f"Bonjour {name}," if name else "Bonjour,",
                   "subject": f"Votre panier {brand} vous attend",
                   "line": f"vous avez laissé {items} dans votre panier sur {brand}. Vous pouvez reprendre ici :",
                   "code": f"Utilisez le code {code}{p} au paiement.",
                   "help": "Une question sur la taille ou la livraison ? Répondez à cet e-mail.",
                   "sign": f"L'équipe {brand}",
                   "wa": f"Bonjour{(' ' + name) if name else ''} ! C'est {brand}. Votre panier est toujours là :"},
            "ro": {"hi": f"Salut {name}," if name else "Salut,",
                   "subject": f"Coșul tău {brand} te așteaptă",
                   "line": f"ai lăsat {items} în coș la {brand}. Poți continua de unde ai rămas aici:",
                   "code": f"Folosește codul {code}{p} la finalizarea comenzii.",
                   "help": "Ai întrebări despre mărimi sau livrare? Răspunde la acest email.",
                   "sign": f"Echipa {brand}",
                   "wa": f"Salut{(' ' + name) if name else ''}! Aici {brand}. Coșul tău e aici dacă îl mai vrei:"},
            "en": {"hi": f"Hi {name}," if name else "Hi,",
                   "subject": f"Your {brand} cart is still here",
                   "line": f"you left {items} in your cart at {brand}. You can pick up where you left off here:",
                   "code": f"Use code {code}{p} at checkout.",
                   "help": "Questions about sizing or shipping? Just reply to this email.",
                   "sign": f"The {brand} team",
                   "wa": f"Hi{(' ' + name) if name else ''}! It's {brand}. Your cart is here if you still want it:"},
        }
        t = T.get(lang, T["en"])
        code_line = f"\n\n{t['code']}" if code else ""
        body = f"{t['hi']}\n\n{t['line']}\n{url}{code_line}\n\n{t['help']}\n\n{t['sign']}"
        wa = f"{t['wa']} {url}" + (f" — {t['code']}" if code else "")
        return {"subject": t["subject"], "body": body, "whatsapp_message": wa, "source": "template"}
