import os
import uuid
from datetime import datetime
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

# ── Init ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Jarvis for Shopify")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "")
APP_URL         = os.getenv("APP_URL") or os.getenv("APP URL") or "https://shopify-jarvis-production.up.railway.app"

ai = AIAdvisor()

# Serve React frontend build
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")


@app.on_event("startup")
def startup():
    db.init_db()


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

def get_shop_or_404(shop: str):
    record = db.get_shop(shop)
    if not record:
        raise HTTPException(401, "Shop not installed. Please install the app first.")
    return record


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/briefing")
async def get_briefing(shop: str = Query(...), lang: str = Query("en")):
    """Return today's AI briefing. Generates a new one if older than 2h."""
    record = get_shop_or_404(shop)

    # Check cached briefing
    cached = db.get_latest_briefing(shop)
    client = ShopifyClient(shop, record["access_token"])
    snapshot = await client.get_store_snapshot()
    current_plan = record.get("plan", "free") or "free"

    if cached:
        age_minutes = (datetime.utcnow() - datetime.fromisoformat(
            cached["created_at"].replace("Z", "").split(".")[0]
        )).total_seconds() / 60
        if age_minutes < 120:
            return {
                "briefing": cached["data"],
                "cached": True,
                "snapshot": snapshot,
                "plan": current_plan
            }

    # Generate fresh briefing
    briefing = await ai.generate_briefing(snapshot, lang=lang)
    db.save_briefing(shop, briefing)
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
async def get_snapshot(shop: str = Query(...)):
    """Return raw store metrics."""
    record   = get_shop_or_404(shop)
    client   = ShopifyClient(shop, record["access_token"])
    snapshot = await client.get_store_snapshot()
    return snapshot


class ChatRequest(BaseModel):
    shop: str
    message: str
    lang: Optional[str] = "en"

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Chat with the AI advisor about the store."""
    record = get_shop_or_404(req.shop)

    # Save user message
    db.save_message(req.shop, "user", req.message)

    # Fetch store data + history
    client   = ShopifyClient(req.shop, record["access_token"])
    snapshot = await client.get_store_snapshot()
    history  = db.get_messages(req.shop, limit=16)

    # Generate AI reply
    reply = await ai.chat(
        shop_name=record.get("shop_name", req.shop),
        snapshot=snapshot,
        history=history[:-1],   # exclude the message we just saved
        message=req.message,
        lang=req.lang or "en"
    )

    db.save_message(req.shop, "assistant", reply)
    return {"reply": reply}


@app.get("/api/history")
async def get_history(shop: str = Query(...), limit: int = 30):
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
        print("TTS error:", e)
    raise HTTPException(500, "TTS audio stream failed")


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
    client = ShopifyClient(req.shop, record["access_token"])
    return_url = f"{APP_URL}/api/billing/callback?shop={req.shop}"
    
    confirmation_url = await client.create_app_subscription(
        return_url=return_url,
        test=req.test
    )
    return {"confirmation_url": confirmation_url}


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
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
