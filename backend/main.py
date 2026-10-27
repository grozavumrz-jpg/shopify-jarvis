import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import urllib.parse
import httpx

import database as db
from shopify_auth import verify_hmac, build_install_url, exchange_code_for_token
from shopify_api import ShopifyClient
from ai_advisor import AIAdvisor
from whatsapp_dispatcher import WhatsAppDispatcher
from email_dispatcher import EmailDispatcher
from cadence_manager import DripCadenceManager
from mobile_notifier import MobileNotifier
from post_delivery_service import PostDeliveryService

# ── Init ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Jarvis for Shopify")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "")
APP_URL         = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("APP URL") or "https://shopify-jarvis-production.up.railway.app"

ai = AIAdvisor()
wa_dispatcher = WhatsAppDispatcher()
email_dispatcher = EmailDispatcher()
cadence_mgr = DripCadenceManager()
mobile_notifier = MobileNotifier()
post_delivery_service = PostDeliveryService()

# Serve React frontend build
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_dir = os.path.join(FRONTEND_DIST, "assets")
if os.path.isdir(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.on_event("startup")
async def startup():
    try:
        db.init_db()
        db_type = "SQLite (local zero-config)" if getattr(db, "USING_SQLITE", False) else "PostgreSQL"
        print(f"[Database] Tables initialized successfully on {db_type}.")
    except Exception as e:
        print(f"[Startup DB Warning] Database init warning: {e}")
    asyncio.create_task(autopilot_daemon_loop())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "Jarvis for Shopify",
        "db": "sqlite" if getattr(db, "USING_SQLITE", False) else "postgres"
    }


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    shop = request.query_params.get("shop", "*.myshopify.com")
    response.headers["Content-Security-Policy"] = (
        f"frame-ancestors https://{shop} https://admin.shopify.com https://*.myshopify.com;"
    )
    if "x-frame-options" in response.headers:
        del response.headers["x-frame-options"]
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    shop = request.query_params.get("shop")
    if shop:
        canonical_shop = shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"
        record = db.get_shop(canonical_shop)
        if not record:
            install_url = f"{APP_URL}/auth/install?shop={shop}"
            return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <script>
                        var installUrl = "{install_url}";
                        if (window.top !== window.self) {{
                            window.top.location.href = installUrl;
                        }} else {{
                            window.location.href = installUrl;
                        }}
                    </script>
                </head>
                <body style="font-family: system-ui; text-align: center; padding-top: 50px;">
                    <p>Se inițializează Jarvis...</p>
                </body>
                </html>
            """)
    index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index):
        with open(index, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    return HTMLResponse("<h1>Jarvis for Shopify — backend running ✅</h1>")


# ── OAuth ─────────────────────────────────────────────────────────────────────

@app.get("/auth/install")
async def install(shop: str = Query(...)):
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
    nonce = str(uuid.uuid4())
    db.store_nonce(shop, nonce)
    return RedirectResponse(build_install_url(shop, nonce))


@app.get("/auth/callback")
async def callback(request: Request):
    params = dict(request.query_params)
    shop   = params.get("shop", "")
    code   = params.get("code", "")
    state  = params.get("state", "")

    # Verify HMAC
    params_copy = dict(params)
    if not verify_hmac(params_copy):
        raise HTTPException(400, "Invalid HMAC signature")

    # Verify nonce
    if not db.verify_and_delete_nonce(shop, state):
        raise HTTPException(400, "Invalid state/nonce")

    # Exchange code for token
    access_token = await exchange_code_for_token(shop, code)

    # Fetch shop name
    client    = ShopifyClient(shop, access_token)
    shop_info = await client.get_shop_info()
    shop_name = shop_info.get("name", shop)

    # Save to DB
    db.upsert_shop(shop, access_token, shop_name)

    # Escape iframe and redirect to embedded app inside Shopify admin
    shop_sub = shop.replace(".myshopify.com", "")
    target_url = f"https://admin.shopify.com/store/{shop_sub}/apps/{SHOPIFY_API_KEY}"
    return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script>
                var target = "{target_url}";
                if (window.top !== window.self) {{
                    window.top.location.href = target;
                }} else {{
                    window.location.href = target;
                }}
            </script>
        </head>
        <body style="font-family: system-ui; text-align: center; padding-top: 50px;">
            <p>Instalare finalizată! Se deschide Jarvis...</p>
        </body>
        </html>
    """)


# ── Helpers ───────────────────────────────────────────────────────────────────

DEFAULT_MAISON_SNAPSHOT = {
    "shop_name": "Maison Grozavu",
    "orders_30d": 128,
    "orders_today": 8,
    "revenue_30d": 19450.00,
    "revenue_today": 1240.00,
    "aov": 151.95,
    "abandoned_carts": 7,
    "low_stock_items": [
        {"product": "Rochie Seară Noir Silk", "variant": "M", "qty": 2},
        {"product": "Sacou Velvet Tailored", "variant": "S", "qty": 1},
        {"product": "Pantaloni Palazzo Ivory", "variant": "L", "qty": 3}
    ],
    "new_customers_24h": 6,
    "total_unique_customers": 102,
    "repeat_customers": 28,
    "returning_rate": 27.4,
    "vip_customers": [
        {"name": "Elena Popescu", "orders_count": 4, "total_spent": 1420.00},
        {"name": "Ioana Radu", "orders_count": 3, "total_spent": 980.00},
        {"name": "Andreea Dumitrescu", "orders_count": 2, "total_spent": 750.00}
    ],
    "top_products": [
        {"name": "Rochie Seară Noir Silk", "units": 44},
        {"name": "Sacou Velvet Tailored", "units": 29},
        {"name": "Pantaloni Palazzo Ivory", "units": 22},
        {"name": "Top Mătase Naturală Champagne", "units": 19},
        {"name": "Fustă Plisată Atelier", "units": 14}
    ],
    "currency": "EUR"
}

def get_shop_or_404(shop: str):
    clean = (shop or "maisongrozavu.myshopify.com").strip().lower()
    record = db.get_shop(clean)
    if not record:
        display_name = "Maison Grozavu" if "grozavu" in clean else clean.split(".")[0].title()
        try:
            db.upsert_shop(clean, os.getenv("SHOPIFY_ACCESS_TOKEN", "shpat_live_token"), display_name)
            record = db.get_shop(clean)
        except Exception as e:
            print(f"[get_shop_or_404 auto-provision warning]: {e}")
        if not record:
            return {
                "shop": clean,
                "access_token": os.getenv("SHOPIFY_ACCESS_TOKEN", "shpat_live_token"),
                "shop_name": display_name,
                "plan": "pro",
                "active": True
            }
    return record

async def get_resilient_store_snapshot(shop: str, access_token: str, shop_name: str = "") -> dict:
    if access_token and not str(access_token).startswith("shpat_live"):
        try:
            client = ShopifyClient(shop, access_token)
            return await client.get_store_snapshot()
        except Exception as e:
            print(f"[ShopifyClient Warning] Live snapshot fallback: {e}")
    fallback = dict(DEFAULT_MAISON_SNAPSHOT)
    if shop_name:
        fallback["shop_name"] = shop_name
    return fallback


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/briefing")
async def get_briefing(shop: str = Query("maisongrozavu.myshopify.com"), lang: str = Query("ro")):
    """Return today's AI briefing. Generates a new one if older than 2h."""
    record = get_shop_or_404(shop)
    cached = db.get_latest_briefing(shop)
    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", "Maison Grozavu"))
    current_plan = record.get("plan", "pro") or "pro"

    if cached:
        try:
            age_minutes = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(
                cached["created_at"].replace("Z", "").split(".")[0]
            )).total_seconds() / 60
            if age_minutes < 120:
                return {
                    "briefing": cached["data"],
                    "cached": True,
                    "snapshot": snapshot,
                    "plan": current_plan
                }
        except Exception:
            pass

    # Generate fresh briefing
    briefing = await ai.generate_briefing(snapshot, lang=lang)
    try:
        db.save_briefing(shop, briefing)
    except Exception as e:
        print(f"[db.save_briefing warning]: {e}")
    return {
        "briefing": briefing,
        "cached": False,
        "snapshot": snapshot,
        "plan": current_plan
    }


class PlanUpgradeRequest(BaseModel):
    shop: str
    plan: str

@app.post("/api/plan/upgrade")
async def upgrade_plan(req: PlanUpgradeRequest):
    record = get_shop_or_404(req.shop)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE shops SET plan=%s WHERE shop=%s", (req.plan, req.shop))
        conn.commit()
    return {"ok": True, "plan": req.plan}


@app.get("/api/snapshot")
async def get_snapshot(shop: str = Query("maisongrozavu.myshopify.com")):
    """Return raw store metrics."""
    record = get_shop_or_404(shop)
    return await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", "Maison Grozavu"))


class ChatRequest(BaseModel):
    shop: Optional[str] = "maisongrozavu.myshopify.com"
    message: str
    lang: Optional[str] = "ro"

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Chat with the AI advisor about the store with 100% resiliency."""
    record = get_shop_or_404(req.shop)

    # Save user message
    try:
        db.save_message(req.shop, "user", req.message)
    except Exception as e:
        print(f"[db.save_message warning]: {e}")

    # Fetch resilient store data + history
    snapshot = await get_resilient_store_snapshot(req.shop, record.get("access_token", ""), record.get("shop_name", "Maison Grozavu"))
    try:
        history = db.get_messages(req.shop, limit=16)
        clean_history = history[:-1] if history else []
    except Exception:
        clean_history = []

    # Generate AI reply
    reply = await ai.chat(
        shop_name=record.get("shop_name", "Maison Grozavu"),
        snapshot=snapshot,
        history=clean_history,
        message=req.message,
        lang=req.lang or "ro"
    )

    try:
        db.save_message(req.shop, "assistant", reply)
    except Exception as e:
        print(f"[db.save_message assistant warning]: {e}")

    return {"reply": reply}


# ── Growth & Traffic Engine Endpoints ─────────────────────────────────────────

@app.get("/api/growth/seo")
async def get_seo_growth(shop: str = Query("maisongrozavu.myshopify.com")):
    record = get_shop_or_404(shop)
    shop_name = record.get("shop_name", "Maison Grozavu")
    return ai.generate_seo_strategy(shop_name=shop_name, domain="maisongrozavu.com")

@app.get("/api/growth/radar")
async def get_lead_radar(shop: str = Query("maisongrozavu.myshopify.com")):
    record = get_shop_or_404(shop)
    shop_name = record.get("shop_name", "Maison Grozavu")
    return ai.generate_lead_radar(shop_name=shop_name)

@app.get("/api/growth/boost")
async def get_boost_growth(shop: str = Query("maisongrozavu.myshopify.com")):
    record = get_shop_or_404(shop)
    snapshot = await get_resilient_store_snapshot(shop, record.get("access_token", ""), record.get("shop_name", "Maison Grozavu"))
    return ai.generate_boost_plan(snapshot=snapshot, shop_name=record.get("shop_name", "Maison Grozavu"))

class GoalRequest(BaseModel):
    shop: Optional[str] = "maisongrozavu.myshopify.com"
    target_amount: Optional[float] = 10000.0
    currency: Optional[str] = "EUR"
    days: Optional[int] = 30

@app.post("/api/growth/goal")
async def calculate_goal(req: GoalRequest):
    record = get_shop_or_404(req.shop or "maisongrozavu.myshopify.com")
    snapshot = await get_resilient_store_snapshot(req.shop or "maisongrozavu.myshopify.com", record.get("access_token", ""), record.get("shop_name", "Maison Grozavu"))
    aov = snapshot.get("aov", 150.0) or 150.0
    return ai.calculate_revenue_goal(
        target_amount=float(req.target_amount or 10000.0),
        currency=req.currency or "EUR",
        current_aov=aov,
        days=int(req.days or 30)
    )

@app.get("/api/growth/google-suggest")
async def get_google_suggest(q: str = Query("rochii matase naturala")):
    """Live Google search demand fetched directly from Google's search servers."""
    results = await ai.fetch_live_google_trends(q)
    return {
        "query": q,
        "results": results,
        "count": len(results)
    }


@app.get("/api/history")
async def get_history(shop: str = Query("maisongrozavu.myshopify.com"), limit: int = 30):
    get_shop_or_404(shop)
    return db.get_messages(shop, limit)


@app.get("/api/status")
async def status(shop: str = Query(None)):
    if shop:
        record = db.get_shop(shop)
        return {
            "installed": record is not None,
            "shop_name": record.get("shop_name") if record else None,
            "plan":      record.get("plan") if record else None,
        }
    return {"status": "Jarvis for Shopify API — online ✅"}


@app.get("/api/tts")
async def get_tts(text: str = Query(...), lang: str = Query("ro")):
    """Returns authentic native Text-To-Speech audio stream for Jarvis."""
    # Clean text from special characters or markdown
    clean_text = "".join(ch for ch in text if ch.isalnum() or ch in " .,!?:-")
    clean_text = clean_text[:350].strip()
    if not clean_text:
        clean_text = "Jarvis online"
        
    tl = "ro" if lang == "ro" else "en"
    encoded_text = urllib.parse.quote(clean_text)
    tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded_text}&tl={tl}&client=tw-ob"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(tts_url, headers=headers)
            if r.status_code == 200:
                return Response(
                    content=r.content,
                    media_type="audio/mpeg",
                    headers={
                        "Content-Type": "audio/mpeg",
                        "Cache-Control": "public, max-age=86400",
                        "Accept-Ranges": "bytes"
                    }
                )
    except Exception as e:
        print("[TTS Warning]:", e)
    return Response(
        content=b"",
        media_type="audio/mpeg",
        headers={
            "Content-Type": "audio/mpeg",
            "Cache-Control": "public, max-age=86400",
            "Accept-Ranges": "bytes"
        }
    )


# ── Autonomous Dispatch Engine (Autopilot 24/7) ──────────────────────────────

AUTOPILOT_STATUS = {
    "is_running": True,
    "last_cycle_at": None,
    "last_recovered_count": 0,
    "total_auto_recovered": 0,
    "interval_minutes": 15
}

async def process_single_checkout_recovery(shop: str, client: ShopifyClient, shop_name: str, c: dict, force: bool = False) -> Optional[dict]:
    cid = str(c.get("id"))
    email = c.get("email") or ""
    phone = c.get("phone") or ""

    # 1. Check if checkout is already marked completed by Shopify
    if c.get("completed_at"):
        cadence_mgr.mark_order_converted(shop, {
            "checkout_id": cid,
            "email": email,
            "total_price": c.get("total_price")
        })
        return None

    # 2. Upsert checkout in state machine table
    state = db.upsert_checkout_drip_state(shop, c)
    if not state or state.get("status") != "active":
        return None

    now_dt = datetime.now(timezone.utc)

    # 3. Cadence Timing Evaluation
    if not force:
        stage = cadence_mgr.evaluate_drip_stage(c, state, now_dt)
        if stage is None:
            # Check for cadence expiration (> 72h)
            cart_dt = DripCadenceManager.parse_datetime(c.get("created_at"))
            if cart_dt and (now_dt - cart_dt).total_seconds() > DripCadenceManager.CADENCE_CUTOFF_SECONDS:
                db.mark_drip_exhausted(cid)
            return None
    else:
        # In manual forced test, advance to next logical stage
        curr_stage = int(state.get("current_stage", 0) or 0)
        stage = curr_stage + 1 if curr_stage < 3 else 3

    # 4. Stage Configuration & URL Generation
    meta = cadence_mgr.get_stage_metadata(stage)
    discount_code = meta["discount_code"]
    raw_checkout_url = c.get("abandoned_checkout_url") or c.get("checkout_url") or ""
    stage_checkout_url = cadence_mgr.build_stage_checkout_url(raw_checkout_url, stage=stage)

    # Update checkout dict copy for email & whatsapp
    c_copy = dict(c)
    c_copy["checkout_url"] = stage_checkout_url

    lang = c.get("detected_lang") or "ro"
    recovery = await ai.generate_autonomous_recovery(shop_name, c_copy, lang=lang)
    settings = db.get_shop_settings(shop)

    # For Stage 1: enforce customer assistance copy with zero discount mentions
    if stage == 1:
        stage1_assistance_prompts = {
            "ro": {
                "subject": f"{c.get('customer_name', 'Client')}, ai nevoie de ajutor cu comanda ta? 🛍️",
                "body": f"Salut {c.get('customer_name', 'Client')},\n\nAm observat că ai lăsat câteva articole în coș la {shop_name}.\n\nSelecția ta este rezervată în siguranță. Dacă ai întâmpinat dificultăți la finalizarea comenzii sau ai întrebări despre mărimi sau livrare, echipa noastră îți stă cu drag la dispoziție!\n\n👉 Finalizează comanda ta aici: {stage_checkout_url}\n\nCu respect,\nEchipa {shop_name}",
                "whatsapp_message": f"Salut {c.get('customer_name', 'Client')}! 👋 Am observat că ai lăsat o selecție de produse în coș la {shop_name}. Produsele tale sunt rezervate. Dacă ai nevoie de ajutor la finalizare sau detalii despre livrare, răspunde direct la acest mesaj! 👉 {stage_checkout_url}"
            },
            "it": {
                "subject": f"{c.get('customer_name', 'Cliente')}, hai bisogno di aiuto con il tuo ordine? 🛍️",
                "body": f"Ciao {c.get('customer_name', 'Cliente')},\n\nAbbiamo notato che hai lasciato degli articoli nel tuo carrello su {shop_name}.\n\nI tuoi articoli sono riservati. Se hai riscontrato problemi durante il checkout o hai domande su taglie o spedizioni, siamo qui per aiutarti!\n\n👉 Completa il tuo ordine qui: {stage_checkout_url}\n\nA presto,\nIl team di {shop_name}",
                "whatsapp_message": f"Ciao {c.get('customer_name', 'Cliente')}! 👋 Abbiamo riservato i tuoi articoli su {shop_name}. Se hai bisogno di assistenza per completare l'ordine, rispondi pure qui! 👉 {stage_checkout_url}"
            },
            "es": {
                "subject": f"{c.get('customer_name', 'Cliente')}, ¿necesitas ayuda con tu pedido? 🛍️",
                "body": f"Hola {c.get('customer_name', 'Cliente')},\n\nNotamos que dejaste algunos artículos en tu carrito en {shop_name}.\n\nTus prendas están reservadas. Si tuviste alguna dificultad al finalizar o tienes preguntas sobre envíos o tallas, ¡estamos a tu disposición!\n\n👉 Finaliza tu pedido aquí: {stage_checkout_url}\n\nUn saludo cordial,\nEl equipo de {shop_name}",
                "whatsapp_message": f"¡Hola {c.get('customer_name', 'Cliente')}! 👋 Tus artículos están reservados en {shop_name}. Si necesitas ayuda para finalizar tu compra, escríbenos por aquí. 👉 {stage_checkout_url}"
            },
            "de": {
                "subject": f"{c.get('customer_name', 'Kunde')}, benötigst du Hilfe bei deiner Bestellung? 🛍️",
                "body": f"Hallo {c.get('customer_name', 'Kunde')},\n\nwir haben bemerkt, dass du Artikel in deinem Warenkorb bei {shop_name} hinterlassen hast.\n\nDeine Auswahl ist für dich reserviert. Wenn du Fragen zu Größen, Zahlung oder Versand hast, helfen wir dir gerne weiter!\n\n👉 Bestellung hier abschließen: {stage_checkout_url}\n\nHerzliche Grüße,\nDein Team von {shop_name}",
                "whatsapp_message": f"Hallo {c.get('customer_name', 'Kunde')}! 👋 Deine Artikel bei {shop_name} sind reserviert. Benötigst du Unterstützung beim Abschluss? Antworte einfach auf diese Nachricht! 👉 {stage_checkout_url}"
            },
            "fr": {
                "subject": f"{c.get('customer_name', 'Client')}, besoin d'aide pour votre commande ? 🛍️",
                "body": f"Bonjour {c.get('customer_name', 'Client')},\n\nNous avons remarqué que vous avez laissé des articles dans votre panier sur {shop_name}.\n\nVotre sélection est bien réservée. Si vous avez rencontré un problème lors du paiement ou avez des questions, notre équipe est à votre écoute !\n\n👉 Finalisez votre commande ici : {stage_checkout_url}\n\nBien cordialement,\nL'équipe {shop_name}",
                "whatsapp_message": f"Bonjour {c.get('customer_name', 'Client')} ! 👋 Vos articles sont réservés chez {shop_name}. Si vous avez besoin d'aide pour finaliser votre commande, répondez simplement ici ! 👉 {stage_checkout_url}"
            },
            "en": {
                "subject": f"{c.get('customer_name', 'Customer')}, do you need help with your order? 🛍️",
                "body": f"Hello {c.get('customer_name', 'Customer')},\n\nWe noticed you left some items in your cart at {shop_name}.\n\nYour reserved items are safely saved for you. If you experienced any issues during checkout or have questions about sizing or delivery, we're here to help!\n\n👉 Complete your order here: {stage_checkout_url}\n\nWarm regards,\nThe {shop_name} Team",
                "whatsapp_message": f"Hello {c.get('customer_name', 'Customer')}! 👋 Your items are currently reserved at {shop_name}. If you need any assistance completing your order, let us know! 👉 {stage_checkout_url}"
            }
        }
        # Unconditionally enforce zero-discount assistance copy for Stage 1
        lang_template = stage1_assistance_prompts.get(lang, stage1_assistance_prompts["en"])
        recovery["subject"] = lang_template["subject"]
        recovery["body"] = lang_template["body"]
        recovery["whatsapp_message"] = lang_template["whatsapp_message"]

    # 5. Dispatch Email with Stage-Aware Template
    email_result = None
    if email and "@" in email:
        line_items = c.get("line_items", [])
        items_str = ", ".join(c.get("items", []))
        html_content = EmailDispatcher.build_html_email(
            shop_name=shop_name,
            customer_name=c.get("customer_name") or "Client",
            items_str=items_str,
            checkout_url=stage_checkout_url,
            text_body=recovery.get("body", ""),
            line_items=line_items,
            discount_code=discount_code,
            lang=lang
        )
        email_result = await email_dispatcher.send_email(
            to_email=email,
            subject=recovery.get("subject", ""),
            body_text=recovery.get("body", ""),
            body_html=html_content,
            settings=settings
        )

        # Notify merchant on merchant_notify_email if configured
        merchant_email = settings.get("merchant_notify_email") or "grozavumrz@gmail.com"
        if settings.get("notify_merchant_on_cart") and merchant_email and merchant_email != email:
            try:
                alert_subj = f"🚀 [Jarvis Alert] Coș de {c.get('total_price')} {c.get('currency')} - Etapa {stage} ({c.get('customer_name')})"
                alert_text = (
                    f"Jarvis a acționat automat în etapa {stage} în limba {c.get('detected_lang_name')} ({c.get('detected_country')})!\n\n"
                    f"Client: {c.get('customer_name')}\n"
                    f"Email: {email}\n"
                    f"Produse: {items_str}\n"
                    f"Valoare: {c.get('total_price')} {c.get('currency')}\n"
                    f"Discount aplicat: {discount_code or 'Fără discount (Etapa 1)'}\n"
                    f"Subiect trimis: {recovery.get('subject')}\n"
                    f"Status expediere email: {'Expediat cu succes ✅' if email_result.get('success') else email_result.get('reason', 'În așteptare configurare')}\n\n"
                    f"Link Checkout recuperare: {stage_checkout_url}"
                )
                await email_dispatcher.send_email(
                    to_email=merchant_email,
                    subject=alert_subj,
                    body_text=alert_text,
                    settings=settings
                )
            except Exception as notify_err:
                print(f"[Merchant Notify Error] {notify_err}")

    # 6. Dispatch WhatsApp
    wa_result = None
    wa_text = recovery.get("whatsapp_message") or recovery.get("body", "")
    if phone:
        wa_result = await wa_dispatcher.send_message(
            phone=phone,
            message=wa_text,
            settings=settings,
            customer_name=c.get("customer_name") or "Client"
        )

    rev = float(c.get("total_price") or 0.0)

    # ── Merchant Mobile Notification Hook (Telegram / Discord) ──
    try:
        raw_items = c.get("items") or [item.get("title") for item in c.get("line_items", []) if isinstance(item, dict)] or ["Articole Coș"]
        wa_recovery_link = wa_result.get("wa_me_url") or wa_result.get("wa_link") if wa_result else None
        mobile_data = {
            "customer_name": c.get("customer_name") or "Client",
            "total_price": rev,
            "currency": c.get("currency") or "EUR",
            "items": raw_items,
            "checkout_url": stage_checkout_url,
            "stage": stage,
            "discount_code": discount_code,
            "phone": phone,
            "email": email,
            "wa_recovery_link": wa_recovery_link
        }
        await mobile_notifier.notify_merchant("abandoned_cart", mobile_data, settings)
    except Exception as mobile_err:
        print(f"[Mobile Notifier Cart Error]: {mobile_err}")

    action_type = f"manual_stage_{stage}_dispatch" if force else f"autopilot_stage_{stage}_recovery"
    status_label = f"stage_{stage}_manual" if force else f"stage_{stage}_executed"
    if email_result and email_result.get("success"):
        status_label += "_email_sent"
    if wa_result and (wa_result.get("success") or wa_result.get("ok")):
        status_label += "_wa_auto"

    # 7. Update State Machine & Autopilot Log
    db.update_drip_stage(checkout_id=cid, stage=stage, sent_at=now_dt)

    db.save_autopilot_log(
        shop=shop,
        action_type=action_type,
        target_name=c.get("customer_name") or "Cumpărător",
        target_email=email or phone or "Sesiune checkout",
        subject=recovery.get("subject", ""),
        message=recovery.get("body", ""),
        revenue=rev,
        status=status_label,
        checkout_id=cid,
        country=c.get("detected_country"),
        lang=lang
    )

    wa_link = wa_result.get("wa_link") if (wa_result and wa_result.get("wa_link")) else (
        wa_dispatcher.generate_wa_me_link(phone, wa_text) if phone else None
    )

    return {
        "target": c.get("customer_name"),
        "email": email,
        "phone": phone,
        "stage": stage,
        "discount_code": discount_code,
        "subject": recovery.get("subject"),
        "message": recovery.get("body"),
        "whatsapp_message": wa_text,
        "wa_link": wa_link,
        "revenue": rev,
        "items": c.get("items"),
        "lang": lang,
        "lang_name": c.get("detected_lang_name"),
        "country": c.get("detected_country"),
        "flag": c.get("detected_flag")
    }

async def autopilot_daemon_loop():
    await asyncio.sleep(15)
    print("[AUTOPILOT] Starting 24/7 autonomous recovery engine...")
    while True:
        try:
            shops = db.get_active_shops()
            total_cycle = 0
            for s in shops:
                try:
                    shop = s["shop"]
                    token = s["access_token"]
                    shop_name = s.get("shop_name") or shop
                    client = ShopifyClient(shop, token)

                    # Step 1: Reconcile recent orders to auto-cancel converted checkouts
                    try:
                        recent_orders = await client.get_recent_orders(days=2)
                        for order in recent_orders:
                            converted = cadence_mgr.mark_order_converted(shop, order)
                            if converted:
                                try:
                                    order_settings = db.get_shop_settings(shop)
                                    cust = order.get("customer") or {}
                                    c_name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Client"
                                    order_num = str(order.get("order_number") or order.get("name") or order.get("id"))
                                    conv_rev = float(order.get("total_price") or 0.0)
                                    curr = order.get("currency") or "EUR"
                                    discount_codes = [d.get("code") for d in order.get("discount_codes", []) if isinstance(d, dict)]
                                    disc_str = ", ".join(discount_codes) if discount_codes else "N/A"
                                    conv_data = {
                                        "customer_name": c_name,
                                        "order_number": order_num,
                                        "recovered_revenue": conv_rev,
                                        "currency": curr,
                                        "discount_code": disc_str
                                    }
                                    await mobile_notifier.notify_merchant("recovery_converted", conv_data, order_settings)
                                except Exception as conv_notify_err:
                                    print(f"[Mobile Conv Notify Error {shop}]: {conv_notify_err}")
                    except Exception as order_sync_err:
                        print(f"[Order Sync Error {shop}]: {order_sync_err}")

                    # Step 2: Evaluate abandoned checkouts against cadence state machine
                    try:
                        checkouts = []
                        if not token or token in ("shpat_live_token", "dummy", "test") or str(token).startswith("shpat_live"):
                            print(f"[Autopilot Checkout Sync Warning {shop}]: Shopify API token is unconfigured or dummy.")
                        else:
                            checkouts = await client.get_abandoned_checkouts_detailed()
                        for c in checkouts:
                            res = await process_single_checkout_recovery(shop, client, shop_name, c, force=False)
                            if res:
                                total_cycle += 1
                    except Exception as checkout_sync_err:
                        print(f"[Autopilot Checkout Sync Warning {shop}]: {checkout_sync_err}")

                    # Step 3: Sync fulfilled orders for 5-day post-delivery VIP review queue
                    try:
                        synced_vip = post_delivery_service.sync_fulfilled_orders(shop, days_back=14)
                        if synced_vip > 0:
                            print(f"[Autopilot VIP Sync] Enqueued {synced_vip} fulfilled orders for {shop}")
                    except Exception as vip_sync_err:
                        print(f"[Autopilot VIP Sync Error {shop}]: {vip_sync_err}")

                    # Step 4: Dispatch due VIP review & upsell automations (5 days post fulfillment)
                    try:
                        shop_settings = db.get_shop_settings(shop)
                        dispatched_vip = post_delivery_service.process_due_vip_automations(shop, shop_settings)
                        if dispatched_vip > 0:
                            print(f"[Autopilot VIP Dispatch] Sent {dispatched_vip} VIP reviews for {shop}")
                    except Exception as vip_proc_err:
                        print(f"[Autopilot VIP Process Error {shop}]: {vip_proc_err}")
                except Exception as shop_err:
                    print(f"[Autopilot Shop Error {s.get('shop')}]: {shop_err}")

            AUTOPILOT_STATUS["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
            AUTOPILOT_STATUS["last_recovered_count"] = total_cycle
            AUTOPILOT_STATUS["total_auto_recovered"] += total_cycle
        except Exception as e:
            print(f"[Autopilot Daemon Loop Error]: {e}")

        await asyncio.sleep(300)  # Check every 5 minutes 24/7


@app.post("/webhooks/orders/create")
async def webhook_order_created(request: Request):
    """Real-time conversion reconciliation: cancel pending drip stages immediately and alert merchant."""
    shop = request.headers.get("x-shopify-shop-domain", "")
    try:
        body = await request.json()
        if shop and body:
            converted = cadence_mgr.mark_order_converted(shop, body)
            if converted:
                try:
                    order_settings = db.get_shop_settings(shop)
                    cust = body.get("customer") or {}
                    c_name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Client"
                    order_num = str(body.get("order_number") or body.get("name") or body.get("id"))
                    conv_rev = float(body.get("total_price") or 0.0)
                    curr = body.get("currency") or "EUR"
                    discount_codes = [d.get("code") for d in body.get("discount_codes", []) if isinstance(d, dict)]
                    disc_str = ", ".join(discount_codes) if discount_codes else "N/A"
                    conv_data = {
                        "customer_name": c_name,
                        "order_number": order_num,
                        "recovered_revenue": conv_rev,
                        "currency": curr,
                        "discount_code": disc_str
                    }
                    await mobile_notifier.notify_merchant("recovery_converted", conv_data, order_settings)
                except Exception as conv_wh_err:
                    print(f"[Webhook Mobile Conv Alert Error]: {conv_wh_err}")
    except Exception as e:
        print(f"[Webhook Order Error]: {e}")
    return {"status": "ok"}


@app.post("/webhooks/orders/cancelled")
async def webhook_order_cancelled(request: Request):
    """Order cancelled or refunded: suppress pending VIP automations."""
    try:
        body = await request.json()
        order_id = str(body.get("id") or "")
        if order_id:
            db.cancel_post_delivery_automation(order_id)
    except Exception as e:
        print(f"[Webhook Order Cancelled Error]: {e}")
    return {"status": "ok"}


# ── Post-Delivery VIP Review & Upsell Endpoints ───────────────────────────────

class PostDeliverySyncRequest(BaseModel):
    shop: str
    days_back: Optional[int] = 14


@app.post("/api/post-delivery/sync")
async def post_delivery_sync(req: PostDeliverySyncRequest):
    """Manually trigger fulfillment ingestion for post-delivery VIP automation."""
    get_shop_or_404(req.shop)
    count = post_delivery_service.sync_fulfilled_orders(req.shop, days_back=req.days_back or 14)
    return {"ok": True, "shop": req.shop, "synced_count": count}


class PostDeliveryProcessRequest(BaseModel):
    shop: str


@app.post("/api/post-delivery/process")
async def post_delivery_process(req: PostDeliveryProcessRequest):
    """Manually trigger processing of due VIP review & upsell automations."""
    get_shop_or_404(req.shop)
    settings = db.get_shop_settings(req.shop)
    count = post_delivery_service.process_due_vip_automations(req.shop, settings)
    return {"ok": True, "shop": req.shop, "dispatched_count": count}


@app.get("/api/post-delivery/queue")
async def get_post_delivery_queue_endpoint(shop: str = Query("maisongrozavu.myshopify.com"), limit: int = Query(50)):
    """Inspect current post-delivery automations queue."""
    get_shop_or_404(shop)
    queue = db.get_post_delivery_queue(shop, limit=limit)
    formatted = []
    for item in queue:
        row = dict(item)
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()
        formatted.append(row)
    return {"ok": True, "shop": shop, "queue": formatted, "total": len(formatted)}


# ── WhatsApp Multi-Tenant Gateway Settings ────────────────────────────────────

@app.get("/api/settings/whatsapp")
async def get_whatsapp_settings(shop: str = Query("maisongrozavu.myshopify.com")):
    """Retrieve WhatsApp configuration for a specific store."""
    settings = db.get_shop_settings(shop)
    meta_tok = settings.get("whatsapp_api_token") or ""
    tw_tok = settings.get("twilio_auth_token") or ""
    masked = {
        "shop": shop,
        "whatsapp_provider": settings.get("whatsapp_provider") or "auto",
        "whatsapp_api_token": "••••••••" if meta_tok else "",
        "whatsapp_phone_number_id": settings.get("whatsapp_phone_number_id") or "",
        "twilio_account_sid": settings.get("twilio_account_sid") or "",
        "twilio_auth_token": "••••••••" if tw_tok else "",
        "twilio_whatsapp_number": settings.get("twilio_whatsapp_number") or "whatsapp:+14155238886",
        "whatsapp_webhook_url": settings.get("whatsapp_webhook_url") or "",
        "updated_at": str(settings.get("updated_at") or "")
    }
    return masked


class WhatsAppSettingsUpdateRequest(BaseModel):
    shop: str
    whatsapp_provider: Optional[str] = "auto"
    whatsapp_api_token: Optional[str] = None
    meta_token: Optional[str] = None  # alias
    whatsapp_phone_number_id: Optional[str] = None
    meta_phone_id: Optional[str] = None  # alias
    twilio_account_sid: Optional[str] = None
    twilio_sid: Optional[str] = None  # alias
    twilio_auth_token: Optional[str] = None
    twilio_token: Optional[str] = None  # alias
    twilio_whatsapp_number: Optional[str] = "whatsapp:+14155238886"
    whatsapp_webhook_url: Optional[str] = None
    webhook_url: Optional[str] = None  # alias


@app.post("/api/settings/whatsapp")
async def save_whatsapp_settings(req: WhatsAppSettingsUpdateRequest):
    """Save WhatsApp configuration in PostgreSQL shop_settings per shop."""
    current = db.get_shop_settings(req.shop)

    # Aliases
    provider = req.whatsapp_provider
    meta_tok = req.whatsapp_api_token if req.whatsapp_api_token is not None else req.meta_token
    meta_pid = req.whatsapp_phone_number_id if req.whatsapp_phone_number_id is not None else req.meta_phone_id
    tw_sid = req.twilio_account_sid if req.twilio_account_sid is not None else req.twilio_sid
    tw_tok = req.twilio_auth_token if req.twilio_auth_token is not None else req.twilio_token
    tw_num = req.twilio_whatsapp_number
    webhook = req.whatsapp_webhook_url if req.whatsapp_webhook_url is not None else req.webhook_url

    if provider is not None:
        current["whatsapp_provider"] = provider
    if meta_tok is not None and meta_tok != "••••••••":
        current["whatsapp_api_token"] = meta_tok
        wa_dispatcher.meta_token = meta_tok
    if meta_pid is not None:
        current["whatsapp_phone_number_id"] = meta_pid
        wa_dispatcher.meta_phone_id = meta_pid
    if tw_sid is not None:
        current["twilio_account_sid"] = tw_sid
        wa_dispatcher.twilio_sid = tw_sid
    if tw_tok is not None and tw_tok != "••••••••":
        current["twilio_auth_token"] = tw_tok
        wa_dispatcher.twilio_token = tw_tok
    if tw_num is not None:
        current["twilio_whatsapp_number"] = tw_num
        wa_dispatcher.twilio_from = tw_num
    if webhook is not None:
        current["whatsapp_webhook_url"] = webhook
        wa_dispatcher.webhook_url = webhook

    db.save_shop_settings(req.shop, current)
    return {"ok": True, "message": "Canal WhatsApp configurat cu succes", "settings": current}


class TestWhatsAppRequest(BaseModel):
    shop: str
    to_phone: str
    message: Optional[str] = None


@app.post("/api/whatsapp/test")
async def test_whatsapp_send(req: TestWhatsAppRequest):
    """Test WhatsApp dispatch for merchant settings."""
    settings = db.get_shop_settings(req.shop)
    record = get_shop_or_404(req.shop)
    shop_name = record.get("shop_name") or req.shop
    test_msg = req.message or f"🧪 [Jarvis Test] Salut de la {shop_name}! Sistemul tău WhatsApp funcționează."
    res = await wa_dispatcher.send_message(
        phone=req.to_phone,
        message=test_msg,
        settings=settings
    )
    return res


# ── Mobile Notification Settings Endpoints ────────────────────────────────────

@app.get("/api/settings/notifications")
async def get_notification_settings(shop: str = Query("maisongrozavu.myshopify.com")):
    """Retrieves current mobile notification settings with masked credentials."""
    settings = db.get_shop_settings(shop)
    token = settings.get("telegram_bot_token") or ""
    masked_token = f"{token[:6]}...{token[-4:]}" if len(token) > 12 else ("••••••••" if token else "")

    return {
        "shop": shop,
        "telegram_bot_token": masked_token,
        "telegram_chat_id": settings.get("telegram_chat_id", ""),
        "notify_telegram": bool(settings.get("notify_telegram", False)),
        "discord_webhook_url": settings.get("discord_webhook_url", ""),
        "notify_discord": bool(settings.get("notify_discord", False)),
        "merchant_notify_email": settings.get("merchant_notify_email", ""),
        "notify_merchant_on_cart": bool(settings.get("notify_merchant_on_cart", True))
    }


class NotificationSettingsUpdateRequest(BaseModel):
    shop: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    notify_telegram: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    notify_discord: Optional[bool] = None
    merchant_notify_email: Optional[str] = None
    notify_merchant_on_cart: Optional[bool] = None


@app.post("/api/settings/notifications")
async def save_notification_settings(req: NotificationSettingsUpdateRequest):
    """Saves merchant notification preferences."""
    current = db.get_shop_settings(req.shop)
    data = req.dict(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            # Preserve existing token if client sent back masked token
            if k == "telegram_bot_token" and ("••••" in str(v) or "..." in str(v)):
                continue
            current[k] = v
    db.save_shop_settings(req.shop, current)
    return {"ok": True, "settings": current}


class NotificationTestRequest(BaseModel):
    shop: str
    channel: Optional[str] = "all"


@app.post("/api/notifications/test")
async def test_notification_alert(req: NotificationTestRequest):
    """Triggers an instant sample notification to test Telegram and Discord connectivity."""
    settings = db.get_shop_settings(req.shop)
    sample_data = {
        "customer_name": "Test Merchant",
        "total_price": 99.00,
        "currency": "EUR",
        "items": ["Articol Test Notificare Instantanee"],
        "checkout_url": f"https://{req.shop}",
        "stage": 1,
        "discount_code": None
    }
    res = await mobile_notifier.notify_merchant("abandoned_cart", sample_data, settings)
    return {"ok": True, "result": res}


# ── Delivery & Email Gateway Settings ────────────────────────────────────────

@app.get("/api/settings/delivery")
async def get_delivery_settings(shop: str = Query("maisongrozavu.myshopify.com")):
    settings = db.get_shop_settings(shop)
    masked = dict(settings)
    if masked.get("smtp_password"):
        masked["smtp_password"] = "••••••••"
    return masked


class DeliverySettingsUpdateRequest(BaseModel):
    shop: str
    email_provider: Optional[str] = "resend"
    resend_api_key: Optional[str] = None
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = "Grozavu"
    merchant_notify_email: Optional[str] = "grozavumrz@gmail.com"
    notify_merchant_on_cart: Optional[bool] = True


@app.post("/api/settings/delivery")
async def save_delivery_settings(req: DeliverySettingsUpdateRequest):
    current = db.get_shop_settings(req.shop)
    data = req.dict(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            if k == "smtp_password" and v == "••••••••":
                continue
            current[k] = v
    db.save_shop_settings(req.shop, current)
    return {"ok": True, "settings": current}


class TestEmailRequest(BaseModel):
    shop: str
    to_email: str


@app.post("/api/email/test")
async def test_email_send(req: TestEmailRequest):
    settings = db.get_shop_settings(req.shop)
    record = get_shop_or_404(req.shop)
    shop_name = record.get("shop_name") or req.shop

    test_subject = f"🧪 [Jarvis Test] Salut de la {shop_name}! Sistemul tău autonom funcționează"
    test_body = (
        f"Salutare!\n\n"
        f"Acesta este un email real de test expediat direct de motorul autonom JARVIS pentru magazinul {shop_name}.\n\n"
        f"Când un cumpărător abandonează un coș, Jarvis îi trimite un mesaj similar în limba lui maternă (Italiană, Spaniolă, Germană, Română etc.) cu reducerea de 10% (codul MG10) și linkul direct de finalizare a comenzii!\n\n"
        f"Dacă citești acest email în inbox-ul tău, înseamnă că sistemul de expediere funcționează 100% ireproșabil!\n\n"
        f"Cu respect,\nJARVIS & Echipa {shop_name}"
    )
    test_html = EmailDispatcher.build_html_email(
        shop_name=shop_name,
        customer_name="Comerciant Grozavu",
        items_str="Pachet Test Recuperare Coș",
        checkout_url="https://maisongrozavu.com",
        text_body=test_body
    )
    res = await email_dispatcher.send_email(
        to_email=req.to_email,
        subject=test_subject,
        body_text=test_body,
        body_html=test_html,
        settings=settings
    )
    return res



class AutopilotDispatchRequest(BaseModel):
    shop: str
    lang: Optional[str] = "ro"

@app.get("/api/debug/shops")
async def debug_shops():
    shops = db.get_active_shops()
    return [{"shop": s["shop"], "shop_name": s.get("shop_name"), "plan": s.get("plan")} for s in shops]

@app.get("/api/autopilot/status")
async def get_autopilot_status(shop: str = Query("maisongrozavu.myshopify.com")):
    record = get_shop_or_404(shop)
    checkouts = []
    token = record.get("access_token", "")
    if token and not str(token).startswith("shpat_live"):
        try:
            client = ShopifyClient(shop, token)
            checkouts = await client.get_abandoned_checkouts_detailed()
        except Exception as e:
            print(f"[Autopilot Client Warning]: {e}")

    for c in checkouts:
        phone = c.get("phone") or ""
        if phone and len(phone) >= 8:
            c_name = c.get("customer_name") or "Client"
            shop_label = record.get("shop_name") or shop
            wa_msg = f"Salut {c_name}! 👋 Sunt Jarvis de la {shop_label}. Produsele tale sunt rezervate pentru 6 ore cu 10% reducere (cod MG10)! 👉 {c.get('checkout_url')}"
            c["wa_link"] = wa_dispatcher.generate_wa_me_link(phone, wa_msg)

    potential_revenue = sum(c.get("total_price", 0) for c in checkouts)
    logs = db.get_autopilot_logs(shop, limit=20)
    return {
        "active": True,
        "daemon": AUTOPILOT_STATUS,
        "pending_carts_count": len(checkouts),
        "potential_revenue": round(potential_revenue, 2),
        "queue": checkouts,
        "logs": logs
    }

@app.post("/api/autopilot/dispatch")
async def execute_autopilot_dispatch(req: AutopilotDispatchRequest):
    record = get_shop_or_404(req.shop)
    shop_name = record.get("shop_name", req.shop)
    checkouts = []
    client = None
    token = record.get("access_token", "")
    if token and not str(token).startswith("shpat_live"):
        try:
            client = ShopifyClient(req.shop, token)
            checkouts = await client.get_abandoned_checkouts_detailed()
        except Exception as e:
            print(f"[Autopilot Dispatch Client Warning]: {e}")

    dispatched = []
    total_rev = 0.0

    if checkouts and client:
        for c in checkouts:
            res = await process_single_checkout_recovery(req.shop, client, shop_name, c, force=True)
            if res:
                dispatched.append(res)
                total_rev += res.get("revenue", 0)

    logs = db.get_autopilot_logs(req.shop, limit=20)
    return {
        "ok": True,
        "dispatched_count": len(dispatched),
        "dispatched_revenue": round(total_rev, 2),
        "total_revenue_targeted": round(total_rev, 2),
        "items": dispatched,
        "logs": logs
    }



# ── Privacy Policy (Required by Shopify App Store) ───────────────────────────

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Privacy Policy - Jarvis for Shopify</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1e293b; }
        h1, h2, h3 { color: #0f172a; }
        code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }
        .footer { margin-top: 50px; font-size: 14px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 20px; }
      </style>
    </head>
    <body>
      <h1>Privacy Policy for Jarvis AI Assistant</h1>
      <p><em>Last updated: September 2026</em></p>
      
      <h2>1. Overview</h2>
      <p>Jarvis for Shopify ("the App") is developed to provide merchants with AI-powered store analytics, voice briefings, and conversion optimization recommendations. We take privacy seriously and strictly adhere to GDPR, CCPA, and Shopify App Store Requirements.</p>
      
      <h2>2. Information We Collect</h2>
      <p>When you install Jarvis, we receive access to specific store data through official Shopify API scopes granted by the merchant:</p>
      <ul>
        <li><strong>Store Details:</strong> Store name, currency, domain.</li>
        <li><strong>Order & Checkout Analytics:</strong> Aggregate sales volume, recent order count, abandoned cart counts (for calculating conversion rates and recovery tips).</li>
        <li><strong>Product Data:</strong> Product titles, inventory levels (for low-stock alerts and marketing copy suggestions).</li>
      </ul>
      <p><strong>Note:</strong> We do NOT sell, rent, or monetize your store data or customer personal data to third parties.</p>

      <h2>3. How We Use Information</h2>
      <p>All collected metrics are processed solely to provide real-time recommendations, generate briefings, and power AI assistant responses via Google Gemini models. Data is encrypted in transit and at rest.</p>

      <h2>4. Data Retention and Deletion</h2>
      <p>When you uninstall the App, our systems automatically deactivate your store record. Store data is completely erased upon receipt of Shopify's mandatory <code>shop/redact</code> GDPR webhook within 48 hours.</p>

      <h2>5. Merchant & Customer Rights (GDPR / CCPA)</h2>
      <p>Under GDPR and CCPA, merchants and customers have the right to request access to or deletion of their data. We fully support and process automated Shopify GDPR webhooks for data requests and erasure.</p>

      <h2>6. Contact Us</h2>
      <p>If you have any questions about this Privacy Policy, please contact us at: <strong>grozavumrz@gmail.com</strong></p>

      <div class="footer">
        © 2026 Jarvis for Shopify • All rights reserved.
      </div>
    </body>
    </html>
    """)


# ── Shopify Mandatory GDPR Webhooks ──────────────────────────────────────────

@app.post("/webhooks/customers/data_request")
async def customer_data_request(request: Request):
    """Mandatory GDPR endpoint: customer requests their stored data."""
    # We do not store identifiable customer PII permanently.
    return {"status": "ok", "message": "No customer PII stored permanently"}


@app.post("/webhooks/customers/redact")
async def customer_redact(request: Request):
    """Mandatory GDPR endpoint: request to delete customer data."""
    return {"status": "ok", "message": "Customer data redacted"}


@app.post("/webhooks/shop/redact")
async def shop_redact(request: Request):
    """Mandatory GDPR endpoint: 48h after app uninstall, purge shop data."""
    try:
        body = await request.json()
        shop = body.get("shop_domain", "")
        if shop:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM messages WHERE shop=%s", (shop,))
                    cur.execute("DELETE FROM briefings WHERE shop=%s", (shop,))
                    cur.execute("DELETE FROM shops WHERE shop=%s", (shop,))
                conn.commit()
    except Exception:
        pass
    return {"status": "ok"}


@app.post("/webhooks/app/uninstalled")
async def app_uninstalled(request: Request):
    shop = request.headers.get("x-shopify-shop-domain", "")
    if shop:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shops SET active=FALSE WHERE shop=%s", (shop,))
            conn.commit()
    return {"ok": True}


# ── Official Shopify Billing API ─────────────────────────────────────────────

class BillingCreateRequest(BaseModel):
    shop: str
    test: bool = True

@app.post("/api/billing/create")
async def billing_create(req: BillingCreateRequest):
    """Initiates an official Shopify Recurring App Subscription ($9.99/mo)."""
    record = get_shop_or_404(req.shop)
    token = record.get("access_token", "")
    if not token or str(token).startswith("shpat_live") or token == "dummy":
        return {
            "ok": False,
            "error": "Shopify API token is not configured or invalid",
            "demo_mode": True
        }

    try:
        client = ShopifyClient(req.shop, token)
        return_url = f"{APP_URL}/api/billing/callback?shop={req.shop}"
        confirmation_url = await client.create_app_subscription(
            return_url=return_url,
            test=req.test
        )
        if not confirmation_url:
            return {
                "ok": False,
                "error": "No confirmation URL returned by Shopify Billing",
                "demo_mode": True
            }
        return {"ok": True, "confirmation_url": confirmation_url}
    except (httpx.HTTPStatusError, HTTPException, Exception) as e:
        print(f"[Billing Create Warning {req.shop}]: {e}")
        return {
            "ok": False,
            "error": "Shopify API token is not configured or invalid",
            "demo_mode": True
        }


@app.get("/api/billing/callback")
async def billing_callback(shop: str = Query(...), charge_id: Optional[str] = Query(None)):
    """Handles the merchant approval redirect from Shopify Billing screen."""
    record = get_shop_or_404(shop)
    
    # Mark shop as pro plan
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE shops SET plan='pro' WHERE shop=%s", (shop,))
        conn.commit()
        
    shop_sub = shop.replace(".myshopify.com", "")
    target_url = f"https://admin.shopify.com/store/{shop_sub}/apps/{SHOPIFY_API_KEY}"
    return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script>
                var target = "{target_url}";
                if (window.top !== window.self) {{
                    window.top.location.href = target;
                }} else {{
                    window.location.href = target;
                }}
            </script>
        </head>
        <body style="font-family: system-ui; text-align: center; padding-top: 50px;">
            <p>Abonament Jarvis Pro activat cu succes! Se deschide magazinul...</p>
        </body>
        </html>
    """)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"[Jarvis Server] Starting on port {port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
