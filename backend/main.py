import os
import re
import json
import time
import uuid
import asyncio
import html as html_lib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

import database as db
from auth_guard import (
    AuthContext, require_auth, resolve_shop, normalize_shop, default_shop, verify_webhook_hmac,
)
from shopify_auth import verify_hmac, build_install_url, exchange_code_for_token, public_app_url
from shopify_api import ShopifyClient
from ai_advisor import AIAdvisor
from whatsapp_dispatcher import WhatsAppDispatcher
from email_dispatcher import EmailDispatcher
from cadence_manager import DripCadenceManager
from mobile_notifier import MobileNotifier
from post_delivery_service import PostDeliveryService
from google_merchant_feed import build_google_merchant_xml, build_feed_items, validate_google_merchant_feed
from seo_optimizer import ProductSEOOptimizer
from deliverability_checker import DeliverabilityChecker
import compliance_guard
from compliance_guard import is_quiet_hours, can_dispatch_to_customer, log_customer_dispatch

# ── Config ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Jarvis for Shopify")

APP_URL = public_app_url()
BRAND_NAME = os.getenv("BRAND_NAME", "Grozavu")
BRAND_DOMAIN = os.getenv("FEED_DOMAIN", "maisongrozavu.com")
BRAND_CONTACT_EMAIL = os.getenv("BRAND_CONTACT_EMAIL", "info@maisongrozavu.com")
FEED_CURRENCY = os.getenv("FEED_CURRENCY", "EUR")

_cors_origins = [o for o in {APP_URL, "https://admin.shopify.com"} if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Jarvis-Key"],
)

ai = AIAdvisor()
wa_dispatcher = WhatsAppDispatcher()
email_dispatcher = EmailDispatcher()
cadence_mgr = DripCadenceManager()
mobile_notifier = MobileNotifier()
post_delivery_service = PostDeliveryService()
seo_optimizer = ProductSEOOptimizer(brand_name=BRAND_NAME, domain=BRAND_DOMAIN)
deliverability_checker = DeliverabilityChecker()

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_dir = os.path.join(FRONTEND_DIST, "assets")
if os.path.isdir(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

PLACEHOLDER_TOKENS = {"", "shpat_live_token", "dummy", "test", "none", "null"}


def has_real_token(token: Any) -> bool:
    """True only for something that can actually be a Shopify Admin API token."""
    t = str(token or "").strip()
    return bool(t) and t.lower() not in PLACEHOLDER_TOKENS and not t.startswith("shpat_live")


def bootstrap_configured_shop() -> Optional[str]:
    """Make restarts self-healing: if SHOPIFY_ACCESS_TOKEN is set, (re)register the configured shop."""
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not has_real_token(token):
        return None
    shop = default_shop()
    try:
        existing = db.get_shop(shop)
        if existing and has_real_token(existing.get("access_token")):
            return shop  # an OAuth token is already stored; keep it
        db.upsert_shop(shop, token, BRAND_NAME)
        print(f"[Startup] Shop {shop} registered from SHOPIFY_ACCESS_TOKEN.")
        return shop
    except Exception as e:
        print(f"[Startup] Could not register {shop}: {e}")
        return None


_daemon_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def startup():
    global _daemon_task
    try:
        db.init_db()
        db_type = "SQLite (ephemeral on Render free!)" if getattr(db, "USING_SQLITE", False) else "PostgreSQL"
        print(f"[Database] Tables initialized on {db_type}.")
    except Exception as e:
        print(f"[Startup DB ERROR] Database init failed — Jarvis cannot store consent/opt-outs until this is fixed: {e}")
    bootstrap_configured_shop()
    if not os.getenv("JARVIS_ADMIN_KEY"):
        print("[Startup Warning] JARVIS_ADMIN_KEY is not set: the dashboard only works embedded in Shopify admin.")
    if os.getenv("JARVIS_DISABLE_DAEMON") != "1":
        _daemon_task = asyncio.create_task(autopilot_daemon_loop())


def daemon_running() -> bool:
    return _daemon_task is not None and not _daemon_task.done()


def autopilot_status_payload() -> Dict[str, Any]:
    status = dict(AUTOPILOT_STATUS)
    status["is_running"] = daemon_running()
    if _daemon_task is not None and _daemon_task.done() and not _daemon_task.cancelled():
        exc = _daemon_task.exception()
        if exc:
            status["last_error"] = f"Daemon stopped: {exc}"[:500]
    return status


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "Jarvis for Shopify",
        "db": "sqlite" if getattr(db, "USING_SQLITE", False) else "postgres",
        "autopilot_running": daemon_running(),
        "autopilot_last_cycle_at": AUTOPILOT_STATUS.get("last_cycle_at"),
    }


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    shop = normalize_shop(request.query_params.get("shop"))
    ancestors = f"https://{shop} https://admin.shopify.com" if shop else "https://admin.shopify.com https://*.myshopify.com"
    response.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors};"
    for h in ("x-frame-options", "X-Frame-Options"):
        if h in response.headers:
            del response.headers[h]
    return response


# ── Frontend ──────────────────────────────────────────────────────────────────

def _redirect_page(target: str, message: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><script>
var target = {json.dumps(target)};
if (window.top !== window.self) {{ window.top.location.href = target; }} else {{ window.location.href = target; }}
</script></head>
<body style="font-family: system-ui; text-align: center; padding-top: 50px;"><p>{html_lib.escape(message)}</p></body></html>""")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    raw_shop = request.query_params.get("shop")
    shop = normalize_shop(raw_shop)
    if raw_shop and shop:
        try:
            record = db.get_shop(shop)
        except Exception:
            record = None
        if not record or not has_real_token(record.get("access_token")):
            return _redirect_page(f"{APP_URL}/auth/install?shop={shop}", "Se inițializează Jarvis...")
    index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index):
        with open(index, "r", encoding="utf-8") as f:
            content = f.read()
        api_key = os.getenv("SHOPIFY_API_KEY", "").strip()
        if api_key and re.fullmatch(r"[A-Za-z0-9_-]+", api_key):
            content = re.sub(r'(<meta name="shopify-api-key" content=")[^"]*(")', rf"\g<1>{api_key}\g<2>", content)
        return HTMLResponse(content)
    return HTMLResponse("<h1>Jarvis for Shopify — backend running ✅</h1>")


# ── OAuth ─────────────────────────────────────────────────────────────────────

@app.get("/auth/install")
async def install(shop: str = Query(...)):
    clean = normalize_shop(shop)
    if not clean:
        raise HTTPException(400, "invalid_shop_domain")
    nonce = str(uuid.uuid4())
    db.store_nonce(clean, nonce)
    return RedirectResponse(build_install_url(clean, nonce))


WEBHOOK_TOPICS = {
    "orders/create": "/webhooks/orders/create",
    "orders/cancelled": "/webhooks/orders/cancelled",
    "app/uninstalled": "/webhooks/app/uninstalled",
}


async def register_webhooks(shop: str, access_token: str) -> None:
    """Subscribe to the webhooks Jarvis handles (422 = already exists, fine)."""
    version = os.getenv("SHOPIFY_API_VERSION", "2026-07")
    async with httpx.AsyncClient(timeout=15) as client:
        for topic, path in WEBHOOK_TOPICS.items():
            try:
                await client.post(
                    f"https://{shop}/admin/api/{version}/webhooks.json",
                    headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"},
                    json={"webhook": {"topic": topic, "address": f"{APP_URL}{path}", "format": "json"}},
                )
            except Exception as e:
                print(f"[Webhook register warning {topic}]: {e}")


@app.get("/auth/callback")
async def callback(request: Request):
    params = dict(request.query_params)
    shop = normalize_shop(params.get("shop", ""))
    code = params.get("code", "")
    state = params.get("state", "")
    if not shop:
        raise HTTPException(400, "invalid_shop_domain")
    if not verify_hmac(dict(params)):
        raise HTTPException(400, "Invalid HMAC signature")
    if not db.verify_and_delete_nonce(shop, state):
        raise HTTPException(400, "Invalid state/nonce")

    access_token = await exchange_code_for_token(shop, code)
    shop_name = shop
    try:
        shop_info = await ShopifyClient(shop, access_token).get_shop_info()
        shop_name = shop_info.get("name") or shop
    except Exception as e:
        print(f"[OAuth] shop info warning: {e}")
    db.upsert_shop(shop, access_token, shop_name)
    await register_webhooks(shop, access_token)

    shop_sub = shop.replace(".myshopify.com", "")
    api_key = os.getenv("SHOPIFY_API_KEY", "")
    return _redirect_page(f"https://admin.shopify.com/store/{shop_sub}/apps/{api_key}",
                          "Instalare finalizată! Se deschide Jarvis...")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_shop_or_404(shop: Optional[str]) -> Dict[str, Any]:
    """Return the stored shop record, or an unsaved 'not connected' stub. Never creates rows."""
    clean = normalize_shop(shop) or default_shop()
    record = None
    try:
        record = db.get_shop(clean)
    except Exception as e:
        print(f"[get_shop warning]: {e}")
    if record:
        return record
    return {"shop": clean, "access_token": "", "shop_name": BRAND_NAME, "plan": "free", "active": False}


def empty_snapshot(shop_name: str, reason: str) -> Dict[str, Any]:
    return {
        "shop_name": shop_name or BRAND_NAME,
        "orders_30d": 0, "orders_today": 0,
        "revenue_30d": 0.0, "revenue_today": 0.0, "aov": 0.0,
        "abandoned_carts": 0, "low_stock_items": [],
        "new_customers_24h": 0, "total_unique_customers": 0,
        "repeat_customers": 0, "returning_rate": 0.0,
        "vip_customers": [], "top_products": [],
        "currency": FEED_CURRENCY,
        "connected": False, "data_source": "none", "data_error": reason,
    }


_SNAPSHOT_CACHE: Dict[str, tuple] = {}
SNAPSHOT_TTL_SECONDS = 60


async def get_resilient_store_snapshot(shop: str, access_token: str, shop_name: str = "") -> dict:
    """Real Shopify numbers, or an explicit empty 'not connected' snapshot. Never invented data."""
    if not has_real_token(access_token):
        return empty_snapshot(shop_name, "Shopify nu este conectat: lipsește tokenul de acces. "
                                         "Reinstalează aplicația din Shopify sau setează SHOPIFY_ACCESS_TOKEN.")
    cached = _SNAPSHOT_CACHE.get(shop)
    if cached and time.time() - cached[0] < SNAPSHOT_TTL_SECONDS:
        return dict(cached[1])
    try:
        snap = await ShopifyClient(shop, access_token).get_store_snapshot()
        snap = dict(snap or {})
        snap.setdefault("connected", True)
        snap.setdefault("data_source", "shopify")
        snap.setdefault("data_error", None)
        _SNAPSHOT_CACHE[shop] = (time.time(), snap)
        return dict(snap)
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        print(f"[ShopifyClient Warning] snapshot failed for {shop}: {detail}")
        return empty_snapshot(shop_name, f"Nu am putut citi datele din Shopify: {str(detail)[:180]}")


def _loads_maybe(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/briefing")
async def get_briefing(shop: Optional[str] = Query(None), lang: str = Query("ro"),
                       auth: AuthContext = Depends(require_auth)):
    """Today's AI briefing based on real data (regenerated if older than 2h or language changed)."""
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", ""))
    plan = record.get("plan") or "free"

    try:
        cached = db.get_latest_briefing(shop)
    except Exception:
        cached = None
    if cached:
        try:
            data = _loads_maybe(cached.get("data"))
            created = datetime.fromisoformat(str(cached["created_at"]).replace("Z", "").split(".")[0])
            age_minutes = (datetime.now(timezone.utc).replace(tzinfo=None) - created).total_seconds() / 60
            if (isinstance(data, dict) and age_minutes < 120 and data.get("kind") == "briefing"
                    and data.get("_lang") == lang
                    and bool(data.get("connected")) == bool(snapshot.get("connected"))):
                return {"briefing": data, "cached": True, "snapshot": snapshot, "plan": plan}
        except Exception:
            pass

    briefing = await ai.generate_briefing(snapshot, lang=lang)
    if isinstance(briefing, dict):
        briefing["_lang"] = lang
    try:
        db.save_briefing(shop, briefing)
    except Exception as e:
        print(f"[db.save_briefing warning]: {e}")
    return {"briefing": briefing, "cached": False, "snapshot": snapshot, "plan": plan}


class PlanUpgradeRequest(BaseModel):
    shop: Optional[str] = None
    plan: str


@app.post("/api/plan/upgrade")
async def upgrade_plan(req: PlanUpgradeRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    # "pro" only comes from a Shopify-confirmed subscription (/api/billing/callback)
    if req.plan not in ("free", "trial"):
        raise HTTPException(400, "invalid_plan")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE shops SET plan=%s WHERE shop=%s", (req.plan, shop))
        conn.commit()
    return {"ok": True, "plan": req.plan}


@app.get("/api/snapshot")
async def get_snapshot(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    return await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", ""))


class ChatRequest(BaseModel):
    shop: Optional[str] = None
    message: str
    lang: Optional[str] = "ro"


@app.post("/api/chat")
async def chat(req: ChatRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    message = (req.message or "").strip()[:4000]
    if not message:
        raise HTTPException(400, "empty_message")
    try:
        db.save_message(shop, "user", message)
    except Exception as e:
        print(f"[db.save_message warning]: {e}")

    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", ""))
    try:
        history = db.get_messages(shop, limit=16)
        clean_history = history[:-1] if history else []
    except Exception:
        clean_history = []

    reply = await ai.chat(
        shop_name=record.get("shop_name") or BRAND_NAME,
        snapshot=snapshot,
        history=clean_history,
        message=message,
        lang=req.lang or "ro",
    )
    try:
        db.save_message(shop, "assistant", reply)
    except Exception as e:
        print(f"[db.save_message assistant warning]: {e}")
    return {"reply": reply, "connected": bool(snapshot.get("connected"))}


# ── Growth ideas (AI suggestions, not data) ───────────────────────────────────

@app.get("/api/growth/seo")
async def get_seo_growth(shop: Optional[str] = Query(None), lang: str = Query("ro"),
                         auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    products, _ = await load_feed_products(shop)
    return ai.generate_seo_strategy(shop_name=record.get("shop_name") or BRAND_NAME, domain=BRAND_DOMAIN,
                                    products=products or None, currency=FEED_CURRENCY, lang=lang)


@app.get("/api/growth/radar")
async def get_lead_radar(shop: Optional[str] = Query(None), lang: str = Query("ro"),
                         auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    return ai.generate_lead_radar(shop_name=record.get("shop_name") or BRAND_NAME, lang=lang)


@app.get("/api/growth/boost")
async def get_boost_growth(shop: Optional[str] = Query(None), lang: str = Query("ro"),
                           auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", ""))
    return ai.generate_boost_plan(snapshot=snapshot, shop_name=record.get("shop_name") or BRAND_NAME, lang=lang)


class GoalRequest(BaseModel):
    shop: Optional[str] = None
    target_amount: Optional[float] = 10000.0
    currency: Optional[str] = "EUR"
    days: Optional[int] = 30
    aov: Optional[float] = None  # owner-supplied assumption, used only when the store has no real AOV


@app.post("/api/growth/goal")
async def calculate_goal(req: GoalRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", ""))
    target = float(req.target_amount or 0)
    days = int(req.days or 30)
    if target <= 0 or days <= 0 or days > 366:
        raise HTTPException(400, "invalid_goal")
    aov, aov_source = None, None
    if snapshot.get("connected") and float(snapshot.get("orders_30d") or 0) > 0 and float(snapshot.get("aov") or 0) > 0:
        aov, aov_source = float(snapshot["aov"]), "shopify_orders"
    elif req.aov and req.aov > 0:
        aov, aov_source = float(req.aov), "owner_assumption"
    elif snapshot.get("connected") and float(snapshot.get("avg_product_price") or 0) > 0:
        aov, aov_source = float(snapshot["avg_product_price"]), "avg_product_price"
    return ai.calculate_revenue_goal(target_amount=target, currency=req.currency or "EUR",
                                     current_aov=aov, days=days, aov_source=aov_source)


@app.get("/api/growth/google-suggest")
async def get_google_suggest(q: str = Query("heavyweight hoodie"), lang: str = Query("en"),
                             auth: AuthContext = Depends(require_auth)):
    """Google Autocomplete suggestions for a query (no search volumes). Empty + source=unavailable on failure."""
    q = (q or "").strip()[:120] or "heavyweight hoodie"
    return await ai.fetch_google_suggest(q, lang)


@app.get("/api/history")
async def get_history(shop: Optional[str] = Query(None), limit: int = Query(30, ge=1, le=200),
                      auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    return db.get_messages(shop, limit)


@app.get("/api/status")
async def status(shop: str = Query(None)):
    if shop:
        clean = normalize_shop(shop)
        if not clean:
            raise HTTPException(400, "invalid_shop_domain")
        try:
            record = db.get_shop(clean)
        except Exception:
            record = None
        return {
            "installed": bool(record and has_real_token(record.get("access_token"))),
            "shop_name": record.get("shop_name") if record else None,
        }
    return {"status": "Jarvis for Shopify API — online ✅"}


# ── Autopilot (abandoned-cart follow-up, consent-only) ────────────────────────

AUTOPILOT_STATUS: Dict[str, Any] = {
    "is_running": False,  # live value comes from autopilot_status_payload()
    "last_cycle_at": None,
    "last_recovered_count": 0,
    "total_auto_recovered": 0,
    "interval_minutes": 5,
    "last_error": None,
}
AUTOPILOT_INTERVAL_SECONDS = 300
RETRY_AFTER_FAILURE_SECONDS = 1800
_FAILED_UNTIL: Dict[str, float] = {}
_cycle_lock: Optional[asyncio.Lock] = None


def _get_cycle_lock() -> asyncio.Lock:
    global _cycle_lock
    if _cycle_lock is None:
        _cycle_lock = asyncio.Lock()
    return _cycle_lock


STAGE1_COPY = {
    "ro": ("{greet}, ai nevoie de ajutor cu comanda?",
           "{greet},\n\nAi lăsat câteva produse în coș la {shop}. Coșul tău este salvat și îl poți finaliza oricând din linkul de mai jos.\n\nDacă ai întrebări despre mărimi sau livrare, răspunde la acest email și te ajutăm cu plăcere.\n\nFinalizează comanda: {url}\n\nEchipa {shop}",
           "{greet}! Ai lăsat câteva produse în coș la {shop}. Dacă ai întrebări despre mărimi sau livrare, răspunde aici. Finalizează comanda: {url}",
           "Salut {name}", "Salut"),
    "es": ("{greet}, ¿necesitas ayuda con tu pedido?",
           "{greet}:\n\nHas dejado algunos productos en tu carrito de {shop}. Tu carrito está guardado y puedes completarlo cuando quieras desde el enlace de abajo.\n\nSi tienes dudas sobre tallas o envíos, responde a este email y te ayudamos.\n\nCompleta tu pedido: {url}\n\nEl equipo de {shop}",
           "¡{greet}! Has dejado productos en tu carrito de {shop}. Si tienes dudas sobre tallas o envíos, responde aquí. Completa tu pedido: {url}",
           "Hola {name}", "Hola"),
    "it": ("{greet}, hai bisogno di aiuto con il tuo ordine?",
           "{greet},\n\nhai lasciato alcuni articoli nel carrello su {shop}. Il carrello è salvato e puoi completarlo quando vuoi dal link qui sotto.\n\nPer domande su taglie o spedizioni, rispondi a questa email.\n\nCompleta l'ordine: {url}\n\nIl team di {shop}",
           "{greet}! Hai lasciato degli articoli nel carrello su {shop}. Per domande su taglie o spedizioni rispondi qui. Completa l'ordine: {url}",
           "Ciao {name}", "Ciao"),
    "de": ("{greet}, brauchst du Hilfe bei deiner Bestellung?",
           "{greet},\n\ndu hast Artikel in deinem Warenkorb bei {shop} gelassen. Dein Warenkorb ist gespeichert und du kannst ihn jederzeit über den Link unten abschließen.\n\nBei Fragen zu Größen oder Versand antworte einfach auf diese E-Mail.\n\nBestellung abschließen: {url}\n\nDein {shop}-Team",
           "{greet}! Du hast Artikel im Warenkorb bei {shop}. Bei Fragen zu Größen oder Versand antworte hier. Bestellung abschließen: {url}",
           "Hallo {name}", "Hallo"),
    "fr": ("{greet}, besoin d'aide pour votre commande ?",
           "{greet},\n\nvous avez laissé des articles dans votre panier sur {shop}. Votre panier est enregistré et vous pouvez le finaliser quand vous voulez via le lien ci-dessous.\n\nPour toute question sur les tailles ou la livraison, répondez à cet e-mail.\n\nFinaliser la commande : {url}\n\nL'équipe {shop}",
           "{greet} ! Vous avez laissé des articles dans votre panier sur {shop}. Une question sur les tailles ou la livraison ? Répondez ici. Finaliser : {url}",
           "Bonjour {name}", "Bonjour"),
    "en": ("{greet}, need help with your order?",
           "{greet},\n\nYou left a few items in your cart at {shop}. Your cart is saved and you can complete it any time from the link below.\n\nIf you have questions about sizing or delivery, just reply to this email and we'll help.\n\nComplete your order: {url}\n\nThe {shop} team",
           "{greet}! You left a few items in your cart at {shop}. Questions about sizing or delivery? Reply here. Complete your order: {url}",
           "Hi {name}", "Hi"),
}


def stage1_copy(lang: str, customer_name: str, shop_name: str, url: str) -> Dict[str, str]:
    subj, body, wa, greet_named, greet_plain = STAGE1_COPY.get(lang, STAGE1_COPY["en"])
    name = (customer_name or "").strip()
    if name.lower() in ("client", "customer", "cliente", "kunde", "cumpărător"):
        name = ""
    greet = greet_named.format(name=name) if name else greet_plain
    fmt = {"greet": greet, "shop": shop_name, "url": url}
    return {"subject": subj.format(**fmt), "body": body.format(**fmt), "whatsapp_message": wa.format(**fmt)}


def _record_checkout_consent(shop: str, c: dict, email: str, phone: str) -> None:
    """Store consent exactly as Shopify reports it. Unknown (None) is never stored as consent."""
    email_consent = c.get("email_marketing_consent")
    if email_consent is None and "buyer_accepts_marketing" in c:
        email_consent = c.get("buyer_accepts_marketing")
    sms_consent = c.get("sms_marketing_consent")
    try:
        if email and email_consent is not None:
            db.record_marketing_consent(shop, email=email, accepts_marketing=bool(email_consent), source="checkout")
        if phone and sms_consent is not None:
            db.record_marketing_consent(shop, phone=phone, accepts_marketing=bool(sms_consent), source="checkout_sms")
    except Exception as e:
        print(f"[Consent record warning {c.get('id')}]: {e}")


async def process_single_checkout_recovery(shop: str, client: Optional[ShopifyClient], shop_name: str, c: dict,
                                           force: bool = False, skip_log: Optional[List[dict]] = None) -> Optional[dict]:
    """
    Evaluate one abandoned checkout and send the due drip stage, if every rule allows it.
    Returns a result dict when at least one message was really sent, otherwise None
    (the reason is appended to `skip_log`). `force` is kept for backwards compatibility
    and no longer bypasses anything: consent, opt-out, caps, quiet hours and timing always apply.
    """
    cid = str(c.get("id"))
    email = (c.get("email") or "").strip()
    phone = (c.get("phone") or "").strip()
    target = c.get("customer_name") or email or phone or cid

    def skip(reason: str) -> None:
        if skip_log is not None:
            skip_log.append({"target": target, "checkout_id": cid, "reason": reason})
        return None

    if c.get("completed_at"):
        cadence_mgr.mark_order_converted(shop, {"checkout_id": cid, "email": email, "total_price": c.get("total_price")})
        return skip("Comanda a fost finalizată")

    if _FAILED_UNTIL.get(cid, 0) > time.time():
        return skip("Ultima încercare de trimitere a eșuat; reîncerc mai târziu")

    state = db.upsert_checkout_drip_state(shop, c)
    if not state or state.get("status") != "active":
        return skip(f"Secvență închisă ({(state or {}).get('status', 'necunoscut')})")

    _record_checkout_consent(shop, c, email, phone)

    now_dt = datetime.now(timezone.utc)
    stage = cadence_mgr.evaluate_drip_stage(c, state, now_dt)
    if stage is None:
        cart_dt = DripCadenceManager.parse_datetime(c.get("created_at"))
        if cart_dt and (now_dt - cart_dt).total_seconds() > DripCadenceManager.CADENCE_CUTOFF_SECONDS:
            db.mark_drip_exhausted(cid)
            return skip("Coș mai vechi de 72h — secvență încheiată")
        return skip("Nu e încă momentul pentru următorul mesaj")

    sequence_key = DripCadenceManager.sequence_key(cid)
    message_type = f"abandoned_cart_stage_{stage}"
    email_ok, email_reason = (False, "Fără email")
    if email and "@" in email:
        email_ok, email_reason = can_dispatch_to_customer(
            shop, email=email, phone=phone, channel="email", now_dt=now_dt,
            message_type=message_type, sequence_key=sequence_key)
    wa_ok, wa_reason = (False, "Fără telefon")
    if phone:
        wa_ok, wa_reason = can_dispatch_to_customer(
            shop, email=email, phone=phone, channel="whatsapp", now_dt=now_dt,
            message_type=message_type, sequence_key=sequence_key)
    if not email_ok and not wa_ok:
        return skip(f"Email: {email_reason} | WhatsApp: {wa_reason}")

    previous_stage = int(state.get("current_stage", 0) or 0)
    if not db.claim_drip_stage(cid, previous_stage, stage):
        return skip("Mesajul pentru această etapă este deja în curs / trimis")

    meta = cadence_mgr.get_stage_metadata(stage)
    discount_code = meta.get("discount_code")
    raw_checkout_url = c.get("abandoned_checkout_url") or c.get("checkout_url") or ""
    stage_checkout_url = cadence_mgr.build_stage_checkout_url(raw_checkout_url, stage=stage)
    c_copy = dict(c)
    c_copy["checkout_url"] = stage_checkout_url
    lang = c.get("detected_lang") or "en"
    settings = db.get_shop_settings(shop)

    try:
        if stage == 1:
            recovery = stage1_copy(lang, c.get("customer_name") or "", shop_name, stage_checkout_url)
        else:
            recovery = await ai.generate_autonomous_recovery(shop_name, c_copy, lang=lang, discount_code=discount_code)

        email_result, wa_result = None, None
        if email_ok:
            html_content = EmailDispatcher.build_html_email(
                shop_name=shop_name,
                customer_name=c.get("customer_name") or "",
                items_str=", ".join(c.get("items", []) or []),
                checkout_url=stage_checkout_url,
                text_body=recovery.get("body", ""),
                line_items=c.get("line_items", []),
                discount_code=discount_code,
                lang=lang,
                customer_email=email,
                shop_domain=shop,
            )
            email_result = await email_dispatcher.send_email(
                to_email=email, subject=recovery.get("subject", ""), body_text=recovery.get("body", ""),
                body_html=html_content, settings=settings, shop_domain=shop)
        if wa_ok:
            wa_result = await wa_dispatcher.send_message(
                phone=phone, message=recovery.get("whatsapp_message") or recovery.get("body", ""),
                settings=settings, customer_name=c.get("customer_name") or "",
                shop_domain=shop, lang=lang)
    except Exception as send_err:
        db.release_drip_stage(cid, stage, previous_stage)
        _FAILED_UNTIL[cid] = time.time() + RETRY_AFTER_FAILURE_SECONDS
        return skip(f"Eroare la trimitere: {str(send_err)[:160]}")

    email_sent = bool(email_result and email_result.get("success"))
    wa_sent = bool(wa_result and wa_result.get("success"))
    rev = float(c.get("total_price") or 0.0)

    if not email_sent and not wa_sent:
        db.release_drip_stage(cid, stage, previous_stage)
        _FAILED_UNTIL[cid] = time.time() + RETRY_AFTER_FAILURE_SECONDS
        reasons = []
        if email_result:
            reasons.append(f"email: {email_result.get('reason') or 'eșuat'}")
        if wa_result:
            reasons.append(f"WhatsApp: {wa_result.get('reason') or wa_result.get('status') or 'eșuat'}")
        db.save_autopilot_log(shop=shop, action_type=f"autopilot_stage_{stage}_recovery",
                              target_name=c.get("customer_name") or "", target_email=email or phone,
                              subject=recovery.get("subject", ""), message=recovery.get("body", ""),
                              revenue=0.0, status=f"stage_{stage}_failed", checkout_id=cid,
                              country=c.get("detected_country"), lang=lang)
        return skip("Trimiterea a eșuat (" + "; ".join(reasons) + ")")

    # claim_drip_stage already advanced current_stage and stamped stage_<n>_sent_at
    if email_sent:
        log_customer_dispatch(shop, email, "email", message_type, sequence_key=sequence_key)
    if wa_sent:
        log_customer_dispatch(shop, phone, "whatsapp", message_type, sequence_key=sequence_key)

    status_label = f"stage_{stage}_sent" + ("_email" if email_sent else "") + ("_whatsapp" if wa_sent else "")
    db.save_autopilot_log(shop=shop, action_type=f"autopilot_stage_{stage}_recovery",
                          target_name=c.get("customer_name") or "", target_email=email or phone,
                          subject=recovery.get("subject", ""), message=recovery.get("body", ""),
                          revenue=rev, status=status_label, checkout_id=cid,
                          country=c.get("detected_country"), lang=lang)

    merchant_email = settings.get("merchant_notify_email") or os.getenv("MERCHANT_NOTIFY_EMAIL", "")
    if settings.get("notify_merchant_on_cart") and merchant_email and merchant_email.lower() != email.lower():
        try:
            await email_dispatcher.send_email(
                to_email=merchant_email,
                subject=f"[Jarvis] Coș abandonat {rev:.2f} {c.get('currency') or ''} — mesajul {stage} trimis",
                body_text=(f"Client: {c.get('customer_name') or '-'}\nEmail: {email or '-'}\nTelefon: {phone or '-'}\n"
                           f"Produse: {', '.join(c.get('items', []) or [])}\nValoare: {rev:.2f} {c.get('currency') or ''}\n"
                           f"Etapa: {stage} | Cod: {discount_code or 'fără'}\n"
                           f"Email trimis: {'da' if email_sent else 'nu'} | WhatsApp trimis: {'da' if wa_sent else 'nu'}\n"
                           f"Link checkout: {stage_checkout_url}"),
                settings=settings, is_internal=True)
        except Exception as notify_err:
            print(f"[Merchant Notify Error] {notify_err}")

    try:
        await mobile_notifier.notify_merchant("abandoned_cart", {
            "customer_name": c.get("customer_name") or "", "total_price": rev,
            "currency": c.get("currency") or "EUR", "items": c.get("items") or [],
            "checkout_url": stage_checkout_url, "stage": stage, "discount_code": discount_code,
            "phone": phone, "email": email,
        }, settings)
    except Exception as mobile_err:
        print(f"[Mobile Notifier Cart Error]: {mobile_err}")

    return {
        "status": "sent", "target": c.get("customer_name"), "email": email, "phone": phone,
        "stage": stage, "discount_code": discount_code, "subject": recovery.get("subject"),
        "message": recovery.get("body"), "email_sent": email_sent, "whatsapp_sent": wa_sent,
        "revenue": rev, "items": c.get("items"), "lang": lang, "country": c.get("detected_country"),
    }


def _reconcile(shop: str, order: dict) -> bool:
    """Close drip sequences for this order. True only if Jarvis had actually messaged that checkout."""
    result = cadence_mgr.reconcile_order(shop, order)
    return bool(result.get("attributed")) if isinstance(result, dict) else bool(result)


async def _notify_conversion(shop: str, order: dict) -> None:
    try:
        cust = order.get("customer") or {}
        await mobile_notifier.notify_merchant("recovery_converted", {
            "customer_name": f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Client",
            "order_number": str(order.get("order_number") or order.get("name") or order.get("id")),
            "recovered_revenue": float(order.get("total_price") or 0.0),
            "currency": order.get("currency") or "EUR",
            "discount_code": ", ".join(d.get("code") for d in order.get("discount_codes", []) if isinstance(d, dict)) or "N/A",
        }, db.get_shop_settings(shop))
    except Exception as e:
        print(f"[Mobile Conv Notify Error {shop}]: {e}")


async def run_shop_cycle(s: dict, skip_log: Optional[List[dict]] = None) -> Dict[str, Any]:
    """One autopilot pass for one shop. Never raises."""
    result: Dict[str, Any] = {"sent": 0, "items": [], "errors": []}
    shop = s.get("shop")
    token = s.get("access_token")
    shop_name = s.get("shop_name") or BRAND_NAME
    if not normalize_shop(shop) or not has_real_token(token):
        result["errors"].append(f"{shop}: Shopify nu este conectat (token lipsă)")
        return result
    client = ShopifyClient(shop, token)

    try:
        for order in await client.get_recent_orders(days=2):
            if _reconcile(shop, order):
                await _notify_conversion(shop, order)
    except Exception as e:
        result["errors"].append(f"Comenzi: {getattr(e, 'detail', e)}")

    try:
        for c in await client.get_abandoned_checkouts_detailed():
            if skip_log is None:
                res = await process_single_checkout_recovery(shop, client, shop_name, c)
            else:
                res = await process_single_checkout_recovery(shop, client, shop_name, c, skip_log=skip_log)
            if res:
                result["sent"] += 1
                result["items"].append(res)
    except Exception as e:
        result["errors"].append(f"Coșuri: {getattr(e, 'detail', e)}")

    try:
        await asyncio.to_thread(post_delivery_service.sync_fulfilled_orders, shop, 14)
    except Exception as e:
        result["errors"].append(f"VIP sync: {e}")
    try:
        settings = db.get_shop_settings(shop)
        await asyncio.to_thread(post_delivery_service.process_due_vip_automations, shop, settings)
    except Exception as e:
        result["errors"].append(f"VIP trimitere: {e}")
    return result


async def run_autopilot_cycle(only_shop: Optional[str] = None, skip_log: Optional[List[dict]] = None) -> Dict[str, Any]:
    async with _get_cycle_lock():
        totals: Dict[str, Any] = {"sent": 0, "items": [], "errors": []}
        try:
            shops = db.get_active_shops()
        except Exception as e:
            shops = []
            totals["errors"].append(f"DB: {e}")
        for s in shops:
            if only_shop and s.get("shop") != only_shop:
                continue
            try:
                r = await run_shop_cycle(s, skip_log=skip_log)
            except Exception as e:  # defensive: a shop must never kill the loop
                r = {"sent": 0, "items": [], "errors": [str(e)]}
            totals["sent"] += r["sent"]
            totals["items"].extend(r["items"])
            totals["errors"].extend(r["errors"])
        AUTOPILOT_STATUS["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
        AUTOPILOT_STATUS["last_recovered_count"] = totals["sent"]
        AUTOPILOT_STATUS["total_auto_recovered"] += totals["sent"]
        AUTOPILOT_STATUS["last_error"] = "; ".join(map(str, totals["errors"]))[:500] or None
        return totals


async def autopilot_daemon_loop():
    await asyncio.sleep(15)
    print("[AUTOPILOT] Starting autonomous follow-up engine (every 5 minutes)...")
    while True:
        try:
            await run_autopilot_cycle()
        except Exception as e:
            AUTOPILOT_STATUS["last_error"] = str(e)[:500]
            print(f"[Autopilot Daemon Loop Error]: {e}")
        await asyncio.sleep(AUTOPILOT_INTERVAL_SECONDS)


# ── Shopify webhooks (HMAC-verified) ──────────────────────────────────────────

async def _verified_webhook(request: Request) -> tuple:
    raw = await request.body()
    if not verify_webhook_hmac(raw, request.headers.get("x-shopify-hmac-sha256")):
        raise HTTPException(401, "invalid_hmac")
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    # The shop header is not covered by the HMAC; GDPR payloads carry a signed shop_domain — prefer it.
    shop = normalize_shop(body.get("shop_domain")) or normalize_shop(request.headers.get("x-shopify-shop-domain"))
    return shop, body


@app.post("/webhooks/orders/create")
async def webhook_order_created(request: Request):
    shop, body = await _verified_webhook(request)
    if shop and body:
        try:
            if _reconcile(shop, body):
                await _notify_conversion(shop, body)
        except Exception as e:
            print(f"[Webhook Order Error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/orders/cancelled")
async def webhook_order_cancelled(request: Request):
    shop, body = await _verified_webhook(request)
    order_id = str(body.get("id") or "")
    if shop and order_id:
        try:
            db.cancel_post_delivery_automation(order_id)
        except Exception as e:
            print(f"[Webhook Order Cancelled Error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/customers/data_request")
async def customer_data_request(request: Request):
    """GDPR: export what Jarvis stores about the customer and send it to the merchant."""
    shop, body = await _verified_webhook(request)
    cust = body.get("customer") or {}
    if shop:
        try:
            export = db.export_customer_data(shop, email=cust.get("email"), phone=cust.get("phone"))
            merchant = (db.get_shop_settings(shop).get("merchant_notify_email")
                        or os.getenv("MERCHANT_NOTIFY_EMAIL", ""))
            if not merchant:
                print(f"[GDPR data_request] {shop}: no merchant email configured — export not delivered")
            if merchant:
                await email_dispatcher.send_email(
                    to_email=merchant,
                    subject=f"[Jarvis] Cerere GDPR de date — {cust.get('email') or cust.get('phone') or cust.get('id')}",
                    body_text=json.dumps(export, ensure_ascii=False, indent=2, default=str),
                    settings=db.get_shop_settings(shop), is_internal=True)
        except Exception as e:
            print(f"[GDPR data_request error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/customers/redact")
async def customer_redact(request: Request):
    shop, body = await _verified_webhook(request)
    cust = body.get("customer") or {}
    if shop:
        try:
            db.redact_customer(shop, email=cust.get("email"), phone=cust.get("phone"),
                               order_ids=[str(o) for o in (body.get("orders_to_redact") or [])])
        except Exception as e:
            print(f"[GDPR customers/redact error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/shop/redact")
async def shop_redact(request: Request):
    shop, body = await _verified_webhook(request)
    target = normalize_shop(body.get("shop_domain")) or shop
    if target:
        try:
            db.purge_shop(target)
        except Exception as e:
            print(f"[GDPR shop/redact error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/app/uninstalled")
async def app_uninstalled(request: Request):
    shop, _ = await _verified_webhook(request)
    if shop:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shops SET active=FALSE WHERE shop=%s", (shop,))
            conn.commit()
    return {"ok": True}


# ── Post-delivery VIP (thank-you + next-order code) ───────────────────────────

class PostDeliverySyncRequest(BaseModel):
    shop: Optional[str] = None
    days_back: Optional[int] = 14


@app.post("/api/post-delivery/sync")
async def post_delivery_sync(req: PostDeliverySyncRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    days = max(1, min(int(req.days_back or 14), 60))
    count = await asyncio.to_thread(post_delivery_service.sync_fulfilled_orders, shop, days)
    return {"ok": True, "shop": shop, "synced_count": count}


class PostDeliveryProcessRequest(BaseModel):
    shop: Optional[str] = None


@app.post("/api/post-delivery/process")
async def post_delivery_process(req: PostDeliveryProcessRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    settings = db.get_shop_settings(shop)
    count = await asyncio.to_thread(post_delivery_service.process_due_vip_automations, shop, settings)
    return {"ok": True, "shop": shop, "dispatched_count": count}


@app.get("/api/post-delivery/queue")
async def get_post_delivery_queue_endpoint(shop: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200),
                                           auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    formatted = []
    for item in db.get_post_delivery_queue(shop, limit=limit):
        row = dict(item)
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        formatted.append(row)
    return {"ok": True, "shop": shop, "queue": formatted, "total": len(formatted)}


# ── Settings (secrets are write-only: never returned) ─────────────────────────

MASK = "••••••••"
SECRET_FIELDS = ("resend_api_key", "smtp_password", "whatsapp_api_token", "twilio_auth_token",
                 "telegram_bot_token", "discord_webhook_url", "whatsapp_webhook_url")


def mask_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings or {})
    for k in SECRET_FIELDS:
        configured = bool(out.get(k))
        out[k] = MASK if configured else ""
        out[f"{k}_configured"] = configured
    return out


def _is_masked(value: Any) -> bool:
    return isinstance(value, str) and ("••••" in value or value.strip() == "...")


URL_SETTING_FIELDS = ("discord_webhook_url", "whatsapp_webhook_url")


def _safe_public_url(value: str) -> bool:
    """Outbound webhook URLs must be public https endpoints (no localhost / private / metadata IPs)."""
    import ipaddress
    from urllib.parse import urlparse
    try:
        parsed = urlparse(value.strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        return "." in host


def _merge_settings(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for k in URL_SETTING_FIELDS:
        v = updates.get(k)
        if isinstance(v, str) and v.strip() and not _is_masked(v) and not _safe_public_url(v):
            raise HTTPException(400, f"invalid_{k}")
    for k, v in updates.items():
        if v is None or k == "shop":
            continue
        if k in SECRET_FIELDS and _is_masked(v):
            continue
        current[k] = v
    return current


@app.get("/api/settings/whatsapp")
async def get_whatsapp_settings(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    s = mask_settings(db.get_shop_settings(shop))
    keys = ("whatsapp_provider", "whatsapp_api_token", "whatsapp_api_token_configured", "whatsapp_phone_number_id",
            "twilio_account_sid", "twilio_auth_token", "twilio_auth_token_configured", "twilio_whatsapp_number",
            "whatsapp_webhook_url", "whatsapp_webhook_url_configured", "updated_at")
    out = {k: s.get(k) for k in keys}
    out["shop"] = shop
    out["whatsapp_provider"] = out.get("whatsapp_provider") or "auto"
    return out


class WhatsAppSettingsUpdateRequest(BaseModel):
    shop: Optional[str] = None
    whatsapp_provider: Optional[str] = None
    whatsapp_api_token: Optional[str] = None
    meta_token: Optional[str] = None  # alias
    whatsapp_phone_number_id: Optional[str] = None
    meta_phone_id: Optional[str] = None  # alias
    twilio_account_sid: Optional[str] = None
    twilio_sid: Optional[str] = None  # alias
    twilio_auth_token: Optional[str] = None
    twilio_token: Optional[str] = None  # alias
    twilio_whatsapp_number: Optional[str] = None
    whatsapp_webhook_url: Optional[str] = None
    webhook_url: Optional[str] = None  # alias


@app.post("/api/settings/whatsapp")
async def save_whatsapp_settings(req: WhatsAppSettingsUpdateRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    updates = {
        "whatsapp_provider": req.whatsapp_provider,
        "whatsapp_api_token": req.whatsapp_api_token if req.whatsapp_api_token is not None else req.meta_token,
        "whatsapp_phone_number_id": req.whatsapp_phone_number_id if req.whatsapp_phone_number_id is not None else req.meta_phone_id,
        "twilio_account_sid": req.twilio_account_sid if req.twilio_account_sid is not None else req.twilio_sid,
        "twilio_auth_token": req.twilio_auth_token if req.twilio_auth_token is not None else req.twilio_token,
        "twilio_whatsapp_number": req.twilio_whatsapp_number,
        "whatsapp_webhook_url": req.whatsapp_webhook_url if req.whatsapp_webhook_url is not None else req.webhook_url,
    }
    if updates["whatsapp_provider"] not in (None, "auto", "meta", "twilio", "webhook", "wa_me"):
        raise HTTPException(400, "invalid_provider")
    current = _merge_settings(db.get_shop_settings(shop), updates)
    db.save_shop_settings(shop, current)
    return {"ok": True, "message": "Setări WhatsApp salvate", "settings": mask_settings(current)}


class TestWhatsAppRequest(BaseModel):
    shop: Optional[str] = None
    to_phone: str
    message: Optional[str] = None


@app.post("/api/whatsapp/test")
async def test_whatsapp_send(req: TestWhatsAppRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    shop_name = record.get("shop_name") or BRAND_NAME
    # Fixed text: this endpoint skips marketing rules, so it must not be usable to send arbitrary messages
    test_msg = f"[Jarvis Test] Mesaj de test de la {shop_name}. Dacă îl primești, WhatsApp funcționează."
    return await wa_dispatcher.send_message(phone=req.to_phone, message=test_msg, settings=db.get_shop_settings(shop),
                                            shop_domain=shop, message_type="transactional")


@app.get("/api/settings/notifications")
async def get_notification_settings(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    s = mask_settings(db.get_shop_settings(shop))
    return {
        "shop": shop,
        "telegram_bot_token": s.get("telegram_bot_token", ""),
        "telegram_bot_token_configured": s.get("telegram_bot_token_configured", False),
        "telegram_chat_id": s.get("telegram_chat_id") or "",
        "notify_telegram": bool(s.get("notify_telegram", False)),
        "discord_webhook_url": s.get("discord_webhook_url", ""),
        "discord_webhook_url_configured": s.get("discord_webhook_url_configured", False),
        "notify_discord": bool(s.get("notify_discord", False)),
        "merchant_notify_email": s.get("merchant_notify_email") or "",
        "notify_merchant_on_cart": bool(s.get("notify_merchant_on_cart", True)),
    }


class NotificationSettingsUpdateRequest(BaseModel):
    shop: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    notify_telegram: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    notify_discord: Optional[bool] = None
    merchant_notify_email: Optional[str] = None
    notify_merchant_on_cart: Optional[bool] = None


@app.post("/api/settings/notifications")
async def save_notification_settings(req: NotificationSettingsUpdateRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    data = req.model_dump(exclude_unset=True)
    data.pop("shop", None)
    current = _merge_settings(db.get_shop_settings(shop), data)
    db.save_shop_settings(shop, current)
    return {"ok": True, "settings": mask_settings(current)}


class NotificationTestRequest(BaseModel):
    shop: Optional[str] = None
    channel: Optional[str] = "all"


@app.post("/api/notifications/test")
async def test_notification_alert(req: NotificationTestRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    sample = {
        "customer_name": "Test", "total_price": 0.0, "currency": "EUR",
        "items": ["Notificare de test Jarvis"], "checkout_url": f"https://{shop}",
        "stage": 1, "discount_code": None,
    }
    res = await mobile_notifier.notify_merchant("abandoned_cart", sample, db.get_shop_settings(shop))
    return {"ok": True, "result": res}


@app.get("/api/settings/delivery")
async def get_delivery_settings(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    return mask_settings(db.get_shop_settings(shop))


class DeliverySettingsUpdateRequest(BaseModel):
    shop: Optional[str] = None
    email_provider: Optional[str] = None
    resend_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    merchant_notify_email: Optional[str] = None
    notify_merchant_on_cart: Optional[bool] = None


@app.post("/api/settings/delivery")
async def save_delivery_settings(req: DeliverySettingsUpdateRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    data = req.model_dump(exclude_unset=True)
    data.pop("shop", None)
    if data.get("email_provider") not in (None, "resend", "smtp"):
        raise HTTPException(400, "invalid_provider")
    current = _merge_settings(db.get_shop_settings(shop), data)
    db.save_shop_settings(shop, current)
    return {"ok": True, "settings": mask_settings(current)}


class TestEmailRequest(BaseModel):
    shop: Optional[str] = None
    to_email: str


@app.post("/api/email/test")
async def test_email_send(req: TestEmailRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    shop_name = record.get("shop_name") or BRAND_NAME
    subject = f"[Jarvis Test] Email de test de la {shop_name}"
    body = (f"Salut!\n\nAcesta este un email de test trimis de Jarvis pentru {shop_name}.\n"
            f"Dacă îl citești, trimiterea emailurilor funcționează cu setările actuale.\n\nJarvis")
    html_body = EmailDispatcher.build_html_email(
        shop_name=shop_name, customer_name="", items_str="", checkout_url=f"https://{BRAND_DOMAIN}",
        text_body=body, lang="ro", customer_email=req.to_email, shop_domain=shop, is_internal=True)
    return await email_dispatcher.send_email(to_email=req.to_email, subject=subject, body_text=body,
                                             body_html=html_body, settings=db.get_shop_settings(shop),
                                             is_internal=True)


@app.get("/api/debug/shops")
async def debug_shops(auth: AuthContext = Depends(require_auth)):
    shops = db.get_active_shops()
    return [{"shop": s["shop"], "shop_name": s.get("shop_name"), "plan": s.get("plan"),
             "connected": has_real_token(s.get("access_token"))}
            for s in shops if not auth.shop or s["shop"] == auth.shop]


class AutopilotDispatchRequest(BaseModel):
    shop: Optional[str] = None
    lang: Optional[str] = "ro"


@app.get("/api/autopilot/status")
async def get_autopilot_status(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    record = get_shop_or_404(shop)
    token = record.get("access_token", "")
    connected = has_real_token(token)
    checkouts: List[dict] = []
    fetch_error = None
    if connected:
        try:
            checkouts = await ShopifyClient(shop, token).get_abandoned_checkouts_detailed()
        except Exception as e:
            fetch_error = str(getattr(e, "detail", e))[:200]

    for c in checkouts:
        try:
            state = db.get_checkout_drip_state(shop, str(c.get("id"))) or {}
        except Exception:
            state = {}
        c["stage"] = int(state.get("current_stage", 0) or 0)
        c["drip_status"] = state.get("status") or "new"

    logs = []
    try:
        logs = db.get_autopilot_logs(shop, limit=20)
    except Exception:
        pass
    return {
        "active": daemon_running(),
        "connected": connected,
        "fetch_error": fetch_error,
        "daemon": autopilot_status_payload(),
        "pending_carts_count": len(checkouts),
        "potential_revenue": round(sum(float(c.get("total_price") or 0) for c in checkouts), 2),
        "queue": checkouts,
        "logs": logs,
    }


@app.post("/api/autopilot/dispatch")
async def execute_autopilot_dispatch(req: AutopilotDispatchRequest, auth: AuthContext = Depends(require_auth)):
    """Run one normal autopilot cycle right now — every rule applies (no bypass)."""
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    if not has_real_token(record.get("access_token")):
        return {"ok": False, "dispatched_count": 0, "skipped": [], "items": [],
                "error": "Shopify nu este conectat — nu pot citi coșurile abandonate.",
                "logs": []}
    skipped: List[dict] = []
    totals = await run_autopilot_cycle(only_shop=shop, skip_log=skipped)
    logs = []
    try:
        logs = db.get_autopilot_logs(shop, limit=20)
    except Exception:
        pass
    return {
        "ok": True,
        "dispatched_count": totals["sent"],
        "dispatched_revenue": round(sum(float(i.get("revenue") or 0) for i in totals["items"]), 2),
        "items": totals["items"],
        "skipped": skipped,
        "errors": totals["errors"],
        "logs": logs,
    }


# ── Privacy Policy ────────────────────────────────────────────────────────────

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    contact = html_lib.escape(BRAND_CONTACT_EMAIL)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Policy - Jarvis for Shopify</title>
<style>body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1e293b; }} code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }}</style>
</head><body>
<h1>Privacy Policy — Jarvis for Shopify</h1>
<p><em>Last updated: October 2026</em></p>
<h2>1. What the app does</h2>
<p>Jarvis helps the merchant follow up with their own shoppers (abandoned checkouts, post-delivery thank-you messages), builds a Google Merchant product feed and shows store analytics.</p>
<h2>2. Data we process</h2>
<ul>
<li><strong>Store data</strong> via the scopes the merchant grants: shop name, products, orders, abandoned checkouts, inventory.</li>
<li><strong>Shopper contact data</strong>: name, email, phone, cart contents and the marketing-consent status recorded by Shopify — only for shoppers of the merchant's own store.</li>
<li><strong>Message history</strong>: which messages were sent, when, and opt-outs (to respect frequency limits and unsubscribes).</li>
</ul>
<p>Marketing messages are sent only to shoppers whose consent is recorded in Shopify. Every email contains an unsubscribe link; opt-outs are permanent.</p>
<h2>3. Processors</h2>
<p>Email delivery (Resend or the merchant's SMTP), optional WhatsApp providers configured by the merchant, Google Gemini for text generation: store metrics, product names and the shopper's language/country only — shopper names, emails, phones and checkout links are never sent to Gemini.</p>
<h2>4. Retention and deletion</h2>
<p>We honour Shopify's mandatory <code>customers/data_request</code>, <code>customers/redact</code> and <code>shop/redact</code> webhooks. On <code>customers/redact</code> the shopper's records are deleted (a one-way hash is kept only if they had opted out, so they are never contacted again). On <code>shop/redact</code> all of the shop's data is deleted.</p>
<h2>5. Contact</h2>
<p>{contact}</p>
</body></html>""")


# ── Official Shopify Billing API ─────────────────────────────────────────────

class BillingCreateRequest(BaseModel):
    shop: Optional[str] = None
    test: bool = True


@app.post("/api/billing/create")
async def billing_create(req: BillingCreateRequest, auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, req.shop)
    record = get_shop_or_404(shop)
    token = record.get("access_token", "")
    if not has_real_token(token):
        return {"ok": False, "demo_mode": True, "error": "Shopify nu este conectat (token lipsă)."}
    try:
        confirmation_url = await ShopifyClient(shop, token).create_app_subscription(
            return_url=f"{APP_URL}/api/billing/callback?shop={shop}", test=req.test)
        if not confirmation_url:
            return {"ok": False, "demo_mode": True, "error": "Shopify nu a returnat un link de confirmare."}
        return {"ok": True, "confirmation_url": confirmation_url}
    except Exception as e:
        print(f"[Billing Create Warning {shop}]: {e}")
        return {"ok": False, "demo_mode": True, "error": f"Shopify Billing a refuzat cererea: {str(getattr(e, 'detail', e))[:200]}"}


@app.get("/api/billing/callback")
async def billing_callback(shop: str = Query(...), charge_id: Optional[str] = Query(None)):
    """Shopify redirects here after the merchant approves. Plan changes only if Shopify confirms."""
    clean = normalize_shop(shop)
    if not clean:
        raise HTTPException(400, "invalid_shop_domain")
    record = get_shop_or_404(clean)
    token = record.get("access_token", "")
    confirmed = False
    if has_real_token(token):
        try:
            subs = await ShopifyClient(clean, token).get_active_subscriptions()
            confirmed = any(str(s.get("status", "")).upper() == "ACTIVE" for s in (subs or []))
        except Exception as e:
            print(f"[Billing callback verify warning]: {e}")
    if confirmed:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shops SET plan='pro' WHERE shop=%s", (clean,))
            conn.commit()
    shop_sub = clean.replace(".myshopify.com", "")
    msg = ("Abonament Jarvis Pro activat! Se deschide magazinul..." if confirmed
           else "Abonamentul nu a putut fi confirmat de Shopify. Se deschide magazinul...")
    return _redirect_page(f"https://admin.shopify.com/store/{shop_sub}/apps/{os.getenv('SHOPIFY_API_KEY', '')}", msg)


# ── Google Merchant Center feed (real products only) ──────────────────────────

_FEED_CACHE: Dict[str, tuple] = {}
FEED_TTL_SECONDS = 900


async def load_feed_products(shop: str) -> tuple:
    """Returns (products | None, error | None). Cached 15 min so Google fetches don't hammer Shopify."""
    cached = _FEED_CACHE.get(shop)
    if cached and time.time() - cached[0] < FEED_TTL_SECONDS:
        return cached[1], None
    record = get_shop_or_404(shop)
    token = record.get("access_token", "")
    if not has_real_token(token):
        return None, "Shopify nu este conectat (token lipsă)"
    try:
        client = ShopifyClient(shop, token)
        getter = getattr(client, "get_active_products", None)
        products = await getter() if getter else await client.get_products(limit=250)
        products = list(products or [])
        _FEED_CACHE[shop] = (time.time(), products)
        return products, None
    except Exception as e:
        return None, f"Nu am putut citi produsele din Shopify: {str(getattr(e, 'detail', e))[:180]}"


def _feed_url() -> str:
    return f"{APP_URL}/feeds/google-merchant.xml"


@app.get("/api/google/feed.xml")
@app.get("/feeds/google-merchant.xml")
async def get_google_merchant_feed(shop: Optional[str] = Query(None)):
    """Public RSS 2.0 product feed for Google Merchant Center. 503 (never fake products) when Shopify is unreachable."""
    clean = normalize_shop(shop) if shop else default_shop()
    if not clean:
        raise HTTPException(400, "invalid_shop_domain")
    products, error = await load_feed_products(clean)
    if products is None:
        return Response(content=f"Feed temporarily unavailable: {error}", status_code=503,
                        media_type="text/plain; charset=utf-8", headers={"Retry-After": "3600"})
    xml_content = build_google_merchant_xml(products=products, shop_domain=BRAND_DOMAIN,
                                            store_name=BRAND_NAME, currency=FEED_CURRENCY)
    return Response(content=xml_content, media_type="application/xml; charset=utf-8")


@app.get("/api/google/feed-validation")
async def validate_merchant_feed_endpoint(shop: Optional[str] = Query(None)):
    clean = normalize_shop(shop) if shop else default_shop()
    if not clean:
        raise HTTPException(400, "invalid_shop_domain")
    products, error = await load_feed_products(clean)
    if products is None:
        return {"valid": False, "connected": False, "items_count": 0, "product_groups": 0,
                "errors": [error], "warnings": [], "warnings_count": 0, "skipped": [],
                "feed_url": _feed_url(), "error": error}
    _, skipped = build_feed_items(products, shop_domain=BRAND_DOMAIN, brand=BRAND_NAME, currency=FEED_CURRENCY)
    xml_content = build_google_merchant_xml(products=products, shop_domain=BRAND_DOMAIN,
                                            store_name=BRAND_NAME, currency=FEED_CURRENCY)
    validation = validate_google_merchant_feed(xml_content)
    validation.update({"connected": True, "skipped": skipped, "feed_url": _feed_url(),
                       "products_in_shopify": len(products)})
    return validation


# ── Product SEO (preview only — nothing is written to Shopify) ────────────────

async def _load_seo_products(shop: str, limit: int = 250) -> tuple:
    products, error = await load_feed_products(shop)
    if products is None:
        return [], error
    return products[:limit], None


@app.get("/api/seo/audit")
async def get_seo_audit(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    products, error = await _load_seo_products(shop)
    audits = [seo_optimizer.audit_product_seo(p) for p in products]
    return {
        "shop": shop,
        "connected": error is None,
        "error": error,
        "products_audited": len(audits),
        "average_seo_score": round(sum(a["seo_score"] for a in audits) / len(audits), 1) if audits else None,
        "needs_optimization_count": sum(1 for a in audits if a.get("needs_optimization")),
        "audits": audits,
    }


class SEOOptimizeRequest(BaseModel):
    shop: Optional[str] = None


@app.post("/api/seo/optimize-now")
async def run_seo_optimization_now(req: Optional[SEOOptimizeRequest] = None, auth: AuthContext = Depends(require_auth)):
    """Generate SEO proposals for the owner to review. PREVIEW ONLY: nothing is written to Shopify."""
    shop = resolve_shop(auth, req.shop if req else None)
    products, error = await _load_seo_products(shop)
    proposals = []
    for p in products:
        proposal = seo_optimizer.propose_changes(p)
        if proposal.get("proposals"):
            proposals.append(proposal)
            for change in proposal["proposals"]:
                try:
                    db.log_seo_change(shop, str(proposal.get("product_id")), proposal.get("title") or "",
                                      change.get("field") or "", str(change.get("current") or "")[:500],
                                      str(change.get("proposed") or "")[:2000], "proposed")
                except Exception as e:
                    print(f"[SEO log warning]: {e}")
    try:
        logs = db.get_seo_logs(shop, limit=20)
    except Exception:
        logs = []
    return {
        "success": error is None,
        "error": error,
        "preview": True,
        "written_to_shopify": 0,
        "products_checked": len(products),
        "proposals": proposals,
        "recent_logs": logs,
    }


@app.get("/api/seo/logs")
async def get_seo_logs_endpoint(shop: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200),
                                auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    logs = db.get_seo_logs(shop, limit=limit)
    return {"shop": shop, "logs": logs, "count": len(logs)}


# ── Deliverability & DNS audit (public DNS data) ──────────────────────────────

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


@app.get("/api/deliverability/dns-audit")
async def get_deliverability_dns_audit(domain: str = Query(BRAND_DOMAIN)):
    clean = (domain or "").strip().lower()
    if not DOMAIN_RE.match(clean):
        raise HTTPException(400, "invalid_domain")
    return await deliverability_checker.audit_domain(clean)


# ── Consent, frequency & unsubscribe ──────────────────────────────────────────

@app.get("/api/compliance/stats")
async def get_compliance_stats(shop: Optional[str] = Query(None), auth: AuthContext = Depends(require_auth)):
    shop = resolve_shop(auth, shop)
    return {
        "shop": shop,
        "consent_stats": db.get_consent_stats(shop),
        "quiet_hours_active": is_quiet_hours(),
        "quiet_hours_label": getattr(compliance_guard, "QUIET_HOURS_LABEL", "21:00–09:00"),
        "quiet_hours_schedule": getattr(compliance_guard, "QUIET_HOURS_LABEL", "21:00–09:00"),
        "frequency_policy": getattr(compliance_guard, "FREQUENCY_POLICY", {}),
    }


UNSUB_TEXT = {
    "es": ("Te has dado de baja", "La dirección <strong>{who}</strong> ya no recibirá comunicaciones comerciales de <strong>{brand}</strong>.",
           "Enlace incompleto. Escríbenos a {contact} y te daremos de baja.", "Volver a la tienda"),
    "ro": ("Te-ai dezabonat cu succes", "Adresa <strong>{who}</strong> nu va mai primi comunicări comerciale de la <strong>{brand}</strong>.",
           "Link incomplet. Scrie-ne la {contact} și te dezabonăm.", "Înapoi la magazin"),
    "en": ("You have been unsubscribed", "<strong>{who}</strong> will no longer receive marketing messages from <strong>{brand}</strong>.",
           "This link is incomplete. Email us at {contact} and we'll unsubscribe you.", "Back to the store"),
}


def _pick_lang(request: Request, explicit: Optional[str]) -> str:
    if explicit in UNSUB_TEXT:
        return explicit
    accept = (request.headers.get("accept-language") or "").lower()
    for code in ("es", "ro", "en"):
        if accept.startswith(code) or f",{code}" in accept.replace(" ", ""):
            return code
    return "en"


@app.api_route("/api/unsubscribe", methods=["GET", "POST"], response_class=HTMLResponse)
async def handle_unsubscribe(request: Request, email: str = Query(""), phone: str = Query(""),
                             shop: str = Query(""), lang: Optional[str] = Query(None)):
    """Opt-out for links in emails (GET) and RFC 8058 one-click (POST List-Unsubscribe=One-Click)."""
    shop_n = normalize_shop(shop) or default_shop()
    clean_email = (email or "").strip()
    clean_phone = (phone or "").strip()
    recorded = False
    try:
        if clean_email and "@" in clean_email:
            recorded = bool(db.record_opt_out(shop_n, email=clean_email)) or recorded
        if clean_phone:
            recorded = bool(db.record_opt_out(shop_n, phone=clean_phone)) or recorded
    except Exception as e:
        print(f"[Unsubscribe error]: {e}")
        recorded = False

    if request.method == "POST":
        return JSONResponse({"ok": recorded}, status_code=200 if recorded else 400)

    code = _pick_lang(request, lang)
    title, ok_msg, bad_msg, back = UNSUB_TEXT[code]
    who = html_lib.escape(clean_email or clean_phone)
    brand = html_lib.escape(BRAND_NAME)
    contact = html_lib.escape(BRAND_CONTACT_EMAIL)
    text = ok_msg.format(who=who, brand=brand) if recorded else bad_msg.format(contact=contact)
    heading = title if recorded else "⚠️"
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="{code}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_lib.escape(title)} | {brand}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#181513; color:#FEF3C7; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:20px; box-sizing:border-box; }}
.card {{ background:#231F1C; border:1px solid #451A03; border-radius:16px; padding:40px; max-width:500px; text-align:center; }}
h1 {{ font-size:22px; margin-bottom:12px; color:#F59E0B; font-weight:600; }}
p {{ font-size:15px; color:#D1D5DB; line-height:1.6; margin-bottom:24px; }}
a.btn {{ display:inline-block; background:#D97706; color:#181513; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600; font-size:14px; }}
</style></head>
<body><div class="card"><h1>{html_lib.escape(heading)}</h1><p>{text}</p>
<a href="https://{html_lib.escape(BRAND_DOMAIN)}" class="btn">{html_lib.escape(back)}</a></div></body></html>""",
                        status_code=200 if recorded else 400)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"[Jarvis Server] Starting on port {port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
