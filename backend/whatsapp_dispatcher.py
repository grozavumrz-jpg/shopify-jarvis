"""
Autonomous Multi-Tenant WhatsApp Dispatch Engine.
Supports:
1. Meta WhatsApp Business Cloud API (Official v19.0 Graph API with Bearer token)
2. Twilio WhatsApp API (HTTP Basic Auth)
3. Generic Custom Webhook Gateway
4. Canonical 1-Click Fallback Link (https://wa.me/{clean_phone}?text={quote(message)})
"""

import os
import urllib.parse
from typing import Dict, Optional, Any
import httpx

try:
    import database as db
except ImportError:
    try:
        import backend.database as db
    except ImportError:
        db = None


class WhatsAppDispatcher:
    """
    Multi-tenant WhatsApp dispatcher capable of routing messages via
    Meta Cloud API, Twilio, generic webhooks, or canonical wa.me links.
    """

    def __init__(self):
        # Default fallback credentials from environment
        self.meta_token = os.getenv("WHATSAPP_API_TOKEN", "").strip()
        self.meta_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886").strip()
        self.webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL", "").strip()

    def clean_phone_number(self, phone: Optional[str]) -> str:
        """
        Sanitize phone number to standard international format (without + or spaces).
        - Strips all non-digit characters.
        - Strips leading international double zero (e.g., 0039 -> 39).
        - Automatically normalizes local prefixes for Italy (3xx -> 393xx),
          Spain (6xx/7xx -> 346xx), Romania (07xx -> 407xx), Germany (01xx -> 491xx).
        """
        if not phone or not isinstance(phone, str):
            return ""

        # Extract only digits
        cleaned = "".join(ch for ch in phone if ch.isdigit())

        # Strip leading double-zero international dial prefix (0039... -> 39...)
        if cleaned.startswith("00"):
            cleaned = cleaned[2:]

        # If Italian mobile without country code (starts with 3, 10 digits)
        if len(cleaned) == 10 and cleaned.startswith("3"):
            return "39" + cleaned

        # If Spanish mobile without country code (starts with 6 or 7, 9 digits)
        if len(cleaned) == 9 and cleaned[0] in ("6", "7"):
            return "34" + cleaned

        # If Romanian mobile (starts with 07, 10 digits)
        if len(cleaned) == 10 and cleaned.startswith("07"):
            return "40" + cleaned[1:]

        # If German mobile (starts with 015, 016, 017, length 11 or 12)
        if cleaned.startswith("01") and len(cleaned) in (11, 12):
            return "49" + cleaned[1:]

        return cleaned

    def generate_wa_me_link(self, phone: str, message: str) -> str:
        """
        Generate canonical direct wa.me link with pre-filled, properly encoded message.
        Conforms strictly to: https://wa.me/{clean_phone}?text={urllib.parse.quote(message)}
        """
        clean = self.clean_phone_number(phone)
        encoded_msg = urllib.parse.quote(message)
        return f"https://wa.me/{clean}?text={encoded_msg}"

    def _resolve_store_config(self, settings: Optional[Dict] = None) -> Dict[str, str]:
        """
        Resolve multi-tenant credentials with precedence:
        Explicit settings dict -> PostgreSQL shop_settings DB lookup -> Environment variables.
        """
        db_settings = {}
        if settings and settings.get("shop") and db:
            try:
                db_settings = db.get_shop_settings(settings["shop"]) or {}
            except Exception:
                db_settings = {}

        def resolve_val(keys: list, env_var: str, default: str = "") -> str:
            # 1. Check explicit settings passed in call
            if settings:
                for k in keys:
                    if k in settings and settings[k] is not None:
                        return str(settings[k]).strip()
            # 2. Check DB settings for this store
            if db_settings:
                for k in keys:
                    if k in db_settings and db_settings[k] is not None:
                        return str(db_settings[k]).strip()
            # 3. Check environment variable fallback
            return os.getenv(env_var, default).strip()

        # Determine effective provider
        provider = resolve_val(["whatsapp_provider"], "WHATSAPP_PROVIDER", "auto").lower()
        if not provider:
            provider = "auto"

        return {
            "provider": provider,
            "meta_token": resolve_val(["whatsapp_api_token", "meta_token"], "WHATSAPP_API_TOKEN"),
            "meta_phone_id": resolve_val(["whatsapp_phone_number_id", "meta_phone_id"], "WHATSAPP_PHONE_NUMBER_ID"),
            "twilio_sid": resolve_val(["twilio_account_sid", "twilio_sid"], "TWILIO_ACCOUNT_SID"),
            "twilio_token": resolve_val(["twilio_auth_token", "twilio_token"], "TWILIO_AUTH_TOKEN"),
            "twilio_from": resolve_val(["twilio_whatsapp_number", "twilio_from"], "TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886"),
            "webhook_url": resolve_val(["whatsapp_webhook_url", "webhook_url"], "WHATSAPP_WEBHOOK_URL"),
        }

    async def _dispatch_meta(self, clean_phone: str, message: str, meta_phone_id: str, meta_token: str) -> Dict[str, Any]:
        """Send message via Meta WhatsApp Business Cloud API."""
        url = f"https://graph.facebook.com/v19.0/{meta_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": True, "body": message}
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                messages = data.get("messages", [])
                mid = messages[0].get("id", "") if messages else ""
                return {"ok": True, "success": True, "provider": "meta", "gateway": "meta_cloud_api", "id": mid, "message_id": mid}
            return {
                "ok": False,
                "success": False,
                "provider": "meta",
                "gateway": "meta_cloud_api",
                "error": f"Meta API HTTP {resp.status_code}: {resp.text}",
                "status_code": resp.status_code
            }

    async def _dispatch_twilio(self, clean_phone: str, message: str, twilio_sid: str, twilio_token: str, twilio_from: str) -> Dict[str, Any]:
        """Send message via Twilio WhatsApp API using Basic Auth."""
        url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
        auth = (twilio_sid, twilio_token)
        from_num = twilio_from if twilio_from.startswith("whatsapp:") else f"whatsapp:{twilio_from}"
        data = {
            "From": from_num,
            "To": f"whatsapp:+{clean_phone}",
            "Body": message
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, auth=auth, data=data)
            if resp.status_code in (200, 201):
                res_json = resp.json()
                sid = res_json.get("sid", "")
                return {"ok": True, "success": True, "provider": "twilio", "gateway": "twilio", "sid": sid, "message_id": sid}
            return {
                "ok": False,
                "success": False,
                "provider": "twilio",
                "gateway": "twilio",
                "error": f"Twilio API HTTP {resp.status_code}: {resp.text}",
                "status_code": resp.status_code
            }

    async def _dispatch_webhook(self, clean_phone: str, message: str, webhook_url: str, customer_name: Optional[str] = None) -> Dict[str, Any]:
        """Send message via generic custom webhook gateway."""
        payload = {
            "phone": clean_phone,
            "customer_name": customer_name or "Client",
            "message": message
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 201):
                return {"ok": True, "success": True, "provider": "webhook", "gateway": "webhook"}
            return {
                "ok": False,
                "success": False,
                "provider": "webhook",
                "gateway": "webhook",
                "error": f"Webhook HTTP {resp.status_code}: {resp.text}",
                "status_code": resp.status_code
            }

    async def send_message(
        self,
        phone: str,
        message: str,
        settings: Optional[Dict] = None,
        customer_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Autonomously dispatch WhatsApp message with multi-tenant settings and waterfall routing:
        1. auto: Meta Cloud API -> Twilio API -> Webhook -> wa.me link
        2. meta: Meta Cloud API -> wa.me link fallback on failure
        3. twilio: Twilio API -> wa.me link fallback on failure
        4. webhook: Webhook -> wa.me link fallback on failure
        """
        # 1. Phone sanitization and length validation
        clean_phone = self.clean_phone_number(phone)
        if not clean_phone or len(clean_phone) < 8:
            return {
                "ok": False,
                "success": False,
                "provider": "none",
                "gateway": "none",
                "error": "Număr de telefon invalid sau prea scurt",
                "wa_me_url": None,
                "wa_link": None
            }

        # 2. Canonical wa.me link generated upfront for fallback availability
        wa_fallback_link = self.generate_wa_me_link(phone, message)

        # 3. Resolve effective credentials for this store/call
        cfg = self._resolve_store_config(settings)
        provider = cfg["provider"]
        last_error = None

        try:
            # ── Route: Twilio Explicit ──
            if provider == "twilio":
                if cfg["twilio_sid"] and cfg["twilio_token"]:
                    try:
                        res = await self._dispatch_twilio(
                            clean_phone, message, cfg["twilio_sid"], cfg["twilio_token"], cfg["twilio_from"]
                        )
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    except Exception as e:
                        last_error = f"Twilio exception: {str(e)}"
                else:
                    last_error = "Twilio credentials not configured"

                return {
                    "ok": False,
                    "success": False,
                    "provider": "twilio",
                    "gateway": "twilio",
                    "wa_me_url": wa_fallback_link,
                    "wa_link": wa_fallback_link,
                    "error": last_error
                }

            # ── Route: Meta Explicit ──
            if provider in ("meta", "meta_cloud_api"):
                if cfg["meta_token"] and cfg["meta_phone_id"]:
                    try:
                        res = await self._dispatch_meta(
                            clean_phone, message, cfg["meta_phone_id"], cfg["meta_token"]
                        )
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    except Exception as e:
                        last_error = f"Meta exception: {str(e)}"
                else:
                    last_error = "Meta credentials not configured"

                return {
                    "ok": False,
                    "success": False,
                    "provider": "meta",
                    "gateway": "meta_cloud_api",
                    "wa_me_url": wa_fallback_link,
                    "wa_link": wa_fallback_link,
                    "error": last_error
                }

            # ── Route: Webhook Explicit ──
            if provider == "webhook":
                if cfg["webhook_url"]:
                    try:
                        res = await self._dispatch_webhook(clean_phone, message, cfg["webhook_url"], customer_name)
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    except Exception as e:
                        last_error = f"Webhook exception: {str(e)}"
                else:
                    last_error = "Webhook URL not configured"

                return {
                    "ok": False,
                    "success": False,
                    "provider": "webhook",
                    "gateway": "webhook",
                    "wa_me_url": wa_fallback_link,
                    "wa_link": wa_fallback_link,
                    "error": last_error
                }

            # ── Route: Auto Waterfall (Meta -> Twilio -> Webhook -> wa.me) ──
            # Step 1: Try Meta Cloud API if configured
            if cfg["meta_token"] and cfg["meta_phone_id"]:
                try:
                    res = await self._dispatch_meta(clean_phone, message, cfg["meta_phone_id"], cfg["meta_token"])
                    if res.get("ok"):
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    last_error = res.get("error")
                except Exception as e:
                    last_error = f"Meta exception: {str(e)}"

            # Step 2: Try Twilio if configured
            if cfg["twilio_sid"] and cfg["twilio_token"]:
                try:
                    res = await self._dispatch_twilio(clean_phone, message, cfg["twilio_sid"], cfg["twilio_token"], cfg["twilio_from"])
                    if res.get("ok"):
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    last_error = res.get("error")
                except Exception as e:
                    last_error = f"Twilio exception: {str(e)}"

            # Step 3: Try Generic Webhook if configured
            if cfg["webhook_url"]:
                try:
                    res = await self._dispatch_webhook(clean_phone, message, cfg["webhook_url"], customer_name)
                    if res.get("ok"):
                        res["wa_me_url"] = wa_fallback_link
                        res["wa_link"] = wa_fallback_link
                        return res
                    last_error = res.get("error")
                except Exception as e:
                    last_error = f"Webhook exception: {str(e)}"

            # Step 4: Final Fallback -> Canonical wa.me 1-click link
            return {
                "ok": False,
                "success": False,
                "provider": "wa_me",
                "gateway": "wa_me_link",
                "wa_me_url": wa_fallback_link,
                "wa_link": wa_fallback_link,
                "notice": "WhatsApp 1-click fallback link ready. Configure Meta Cloud API or Twilio credentials in settings for automated cloud dispatch.",
                "error": last_error
            }
        except Exception as outer_err:
            return {
                "ok": False,
                "success": False,
                "provider": provider,
                "gateway": "wa_me_link",
                "wa_me_url": wa_fallback_link,
                "wa_link": wa_fallback_link,
                "error": str(outer_err)
            }

    async def send_autonomous_whatsapp(
        self,
        phone: str,
        customer_name: str,
        message: str,
        settings: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Backward-compatible method signature delegating to send_message.
        """
        return await self.send_message(
            phone=phone,
            message=message,
            settings=settings,
            customer_name=customer_name
        )
