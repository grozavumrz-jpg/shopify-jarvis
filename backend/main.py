import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
async def get_briefing(shop: str = Query(...)):
    """Return today's AI briefing. Generates a new one if older than 2h."""
    record = get_shop_or_404(shop)

    # Check cached briefing
    cached = db.get_latest_briefing(shop)
    if cached:
        age_minutes = (datetime.utcnow() - datetime.fromisoformat(
            cached["created_at"].replace("Z", "").split(".")[0]
        )).total_seconds() / 60
        if age_minutes < 120:
            return {"briefing": cached["data"], "cached": True}

    # Generate fresh briefing
    client   = ShopifyClient(shop, record["access_token"])
    snapshot = await client.get_store_snapshot()
    briefing = await ai.generate_briefing(snapshot)

    db.save_briefing(shop, briefing)
    return {"briefing": briefing, "cached": False, "snapshot": snapshot}


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
        message=req.message
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


# ── Shopify Webhooks ──────────────────────────────────────────────────────────

@app.post("/webhooks/app/uninstalled")
async def app_uninstalled(request: Request):
    shop = request.headers.get("x-shopify-shop-domain", "")
    if shop:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shops SET active=FALSE WHERE shop=%s", (shop,))
            conn.commit()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
