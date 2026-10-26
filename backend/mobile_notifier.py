"""
backend/mobile_notifier.py
Instant Mobile Merchant Alerts via Telegram Bot API & Discord Webhooks.
Designed for Shopify Jarvis Autonomous Revenue Recovery.
"""

import html
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
import httpx

logger = logging.getLogger("mobile_notifier")


class MobileNotifier:
    """
    Instant Mobile Notifier for Shopify Jarvis Merchants.
    Dispatches real-time alerts across:
      1. Telegram Bot API (HTML formatted messages)
      2. Discord Webhook (Rich Embeds with color coding & length truncation)
    """

    # Official Hex Color Codes for Discord Embeds
    COLOR_AMBER = 0xF59E0B      # Decimal: 16096779 — Abandoned Cart Alert
    COLOR_EMERALD = 0x10B981    # Decimal: 1096065  — Revenue Recovery Converted
    COLOR_PURPLE = 0x6366F1     # Decimal: 6514417  — VIP Review & Upsell Sent

    # Discord Limits according to Discord API documentation
    DISCORD_FIELD_VALUE_LIMIT = 1024
    DISCORD_FIELD_NAME_LIMIT = 256
    DISCORD_DESCRIPTION_LIMIT = 4096

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    @staticmethod
    def _safe_float(val: Any) -> float:
        """Safely parses float with fallback to 0.0 on invalid string or None."""
        try:
            return float(val or 0.0)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _truncate(val: Any, limit: int) -> str:
        """Truncates string to limit with ellipsis if exceeded."""
        s = str(val if val is not None else "")
        if len(s) <= limit:
            return s
        return s[:limit - 3] + "..."

    @staticmethod
    def _format_items_summary(items: Any) -> str:
        """Formats item list or strings into a clean summary."""
        if not items:
            return "Nespecificat"
        if isinstance(items, list):
            titles = []
            for item in items:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("name") or "Articol"
                    qty = item.get("quantity")
                    titles.append(f"{title} (x{qty})" if qty else str(title))
                else:
                    titles.append(str(item))
            return ", ".join(titles) if titles else "Nespecificat"
        return str(items)

    def format_telegram_message(self, event_type: str, data: Dict[str, Any]) -> str:
        """
        Formats HTML sanitized alert for Telegram Bot API.
        Escapes dynamic content (<, >, &) to prevent Telegram HTML parse errors.
        """
        c_name = html.escape(str(data.get("customer_name") or "Client"))
        currency = html.escape(str(data.get("currency") or "EUR"))

        if event_type == "abandoned_cart":
            total = self._safe_float(data.get("total_price"))
            items_str = html.escape(self._format_items_summary(data.get("items")))
            raw_url = str(data.get("checkout_url") or "")
            clean_url = html.escape(raw_url)
            stage = data.get("stage")
            stage_info = f" • Etapa {html.escape(str(stage))}" if stage else ""
            discount = data.get("discount_code")
            discount_info = f" • Reducere {html.escape(str(discount))}" if discount else ""

            lines = [
                f"🛒 <b>Coș Abandonat Detectat!{stage_info}{discount_info}</b>\n",
                f"👤 <b>Client:</b> {c_name}",
                f"💰 <b>Valoare:</b> {total:.2f} {currency}",
                f"🛍️ <b>Produse:</b> {items_str}"
            ]
            if clean_url:
                lines.append(f"🔗 <a href=\"{clean_url}\">Deschide Checkout Recuperare</a>")
            wa_link = data.get("wa_recovery_link") or data.get("wa_link")
            if wa_link:
                lines.append(f"📲 <a href=\"{html.escape(str(wa_link))}\">Trimite WhatsApp 1-Click</a>")
            return "\n".join(lines)

        elif event_type == "recovery_converted":
            rev = self._safe_float(data.get("recovered_revenue") or data.get("total_price"))
            order_num = html.escape(str(data.get("order_number") or "N/A"))
            discount = data.get("discount_code")
            discount_str = html.escape(str(discount)) if discount else "Niciunul"

            lines = [
                "🎉 <b>Venit Recuperat cu Succes!</b>\n",
                f"👤 <b>Client:</b> {c_name}",
                f"📦 <b>Comandă:</b> #{order_num}",
                f"💵 <b>Venit Recuperat:</b> {rev:.2f} {currency}",
                f"🏷️ <b>Cod Reducere:</b> {discount_str}"
            ]
            return "\n".join(lines)

        elif event_type == "vip_upsell_sent":
            order_num = html.escape(str(data.get("order_number") or "N/A"))
            discount = html.escape(str(data.get("discount_code") or "MGVIP15"))

            lines = [
                "👑 <b>VIP Review &amp; Upsell Expediat!</b>\n",
                f"👤 <b>Client:</b> {c_name}",
                f"📦 <b>Comandă:</b> #{order_num}",
                f"🎁 <b>Cod Cadou VIP:</b> {discount}"
            ]
            return "\n".join(lines)

        # Generic fallback
        return f"🔔 <b>Eveniment Jarvis: {html.escape(str(event_type))}</b>\n👤 Client: {c_name}"

    def format_discord_embed(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formats Rich Embed for Discord Webhook.
        Truncates field values <= 1024 characters to prevent HTTP 400 Bad Request.
        """
        c_name = str(data.get("customer_name") or "Client")
        currency = str(data.get("currency") or "EUR")
        now_iso = datetime.now(timezone.utc).isoformat()

        if event_type == "abandoned_cart":
            total = self._safe_float(data.get("total_price"))
            items_str = self._format_items_summary(data.get("items"))
            url = str(data.get("checkout_url") or "")
            stage = data.get("stage")
            stage_str = f"Etapa {stage}" if stage else "Inițial"
            discount = data.get("discount_code")
            if discount:
                stage_str += f" ({discount})"

            fields = [
                {"name": "Client", "value": self._truncate(c_name, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Valoare Coș", "value": self._truncate(f"{total:.2f} {currency}", self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Etapă Drip", "value": self._truncate(stage_str, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Produse", "value": self._truncate(items_str, self.DISCORD_FIELD_VALUE_LIMIT), "inline": False}
            ]
            if url:
                fields.append({"name": "Acțiune Recuperare", "value": self._truncate(f"[Finalizează Comanda]({url})", self.DISCORD_FIELD_VALUE_LIMIT), "inline": False})
            wa_link = data.get("wa_recovery_link") or data.get("wa_link")
            if wa_link:
                fields.append({"name": "WhatsApp Rapid", "value": self._truncate(f"[Deschide Chat Direct wa.me]({wa_link})", self.DISCORD_FIELD_VALUE_LIMIT), "inline": False})

            return {
                "title": "🛒 Coș Abandonat Detectat",
                "description": self._truncate(f"Un client a abandonat produse în valoare de **{total:.2f} {currency}**.", self.DISCORD_DESCRIPTION_LIMIT),
                "color": self.COLOR_AMBER,
                "timestamp": now_iso,
                "fields": fields,
                "footer": {"text": "Shopify Jarvis Autonomous Recovery Engine"}
            }

        elif event_type == "recovery_converted":
            rev = self._safe_float(data.get("recovered_revenue") or data.get("total_price"))
            order_num = str(data.get("order_number") or "N/A")
            discount = str(data.get("discount_code") or "N/A")

            fields = [
                {"name": "Client", "value": self._truncate(c_name, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Comandă", "value": self._truncate(f"#{order_num}", self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Venit Recuperat", "value": self._truncate(f"{rev:.2f} {currency}", self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Cod Reducere", "value": self._truncate(discount, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True}
            ]

            return {
                "title": "🎉 Venit Recuperat cu Succes!",
                "description": self._truncate(f"Comanda **#{order_num}** a fost plasată cu succes după recuperare autonomă!", self.DISCORD_DESCRIPTION_LIMIT),
                "color": self.COLOR_EMERALD,
                "timestamp": now_iso,
                "fields": fields,
                "footer": {"text": "Shopify Jarvis Autonomous Recovery Engine"}
            }

        elif event_type == "vip_upsell_sent":
            order_num = str(data.get("order_number") or "N/A")
            discount = str(data.get("discount_code") or "MGVIP15")

            fields = [
                {"name": "Client", "value": self._truncate(c_name, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Comandă", "value": self._truncate(f"#{order_num}", self.DISCORD_FIELD_VALUE_LIMIT), "inline": True},
                {"name": "Cod Cadou VIP", "value": self._truncate(discount, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True}
            ]

            return {
                "title": "👑 Notificare VIP Review & Upsell Expediată",
                "description": self._truncate(f"Secvența VIP a fost transmisă pentru comanda **#{order_num}**.", self.DISCORD_DESCRIPTION_LIMIT),
                "color": self.COLOR_PURPLE,
                "timestamp": now_iso,
                "fields": fields,
                "footer": {"text": "Shopify Jarvis Autonomous VIP Engine"}
            }

        # Fallback embed
        return {
            "title": f"🔔 Alertă Merchant: {event_type}",
            "description": f"Eveniment declanșat pentru clientul {c_name}.",
            "color": self.COLOR_AMBER,
            "timestamp": now_iso,
            "fields": [{"name": "Client", "value": self._truncate(c_name, self.DISCORD_FIELD_VALUE_LIMIT), "inline": True}]
        }

    async def send_telegram_notification(self, bot_token: str, chat_id: str, text: str) -> Dict[str, Any]:
        """Sends an HTML formatted message directly via Telegram Bot API."""
        token = (bot_token or "").strip()
        chat = str(chat_id or "").strip()

        if not token or not chat:
            return {"ok": False, "reason": "missing_telegram_credentials"}

        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    return {"ok": True, "status": 200, "data": resp.json()}
                return {"ok": False, "status": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.error(f"[Telegram API Exception]: {e}")
            return {"ok": False, "error": str(e)}

    async def send_telegram(self, text: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Sends an HTML formatted message via Telegram Bot API using store settings."""
        if not settings.get("notify_telegram"):
            return {"ok": False, "reason": "notify_telegram_disabled"}

        bot_token = settings.get("telegram_bot_token")
        chat_id = settings.get("telegram_chat_id")

        return await self.send_telegram_notification(bot_token, chat_id, text)

    async def send_discord_notification(self, webhook_url: str, embed_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a rich embed directly via Discord Webhook."""
        url = (webhook_url or "").strip()
        if not url:
            return {"ok": False, "reason": "missing_discord_webhook_url"}

        # Ensure embed field values do not exceed DISCORD_FIELD_VALUE_LIMIT
        sanitized_embed = dict(embed_payload)
        if "fields" in sanitized_embed and isinstance(sanitized_embed["fields"], list):
            sanitized_fields = []
            for f in sanitized_embed["fields"]:
                if isinstance(f, dict):
                    f_copy = dict(f)
                    if "value" in f_copy:
                        f_copy["value"] = self._truncate(f_copy["value"], self.DISCORD_FIELD_VALUE_LIMIT)
                    sanitized_fields.append(f_copy)
                else:
                    sanitized_fields.append(f)
            sanitized_embed["fields"] = sanitized_fields

        payload = {"embeds": [sanitized_embed], "parse_mode": "HTML"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code in (200, 204):
                    return {"ok": True, "status": resp.status_code}
                return {"ok": False, "status": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.error(f"[Discord Webhook Exception]: {e}")
            return {"ok": False, "error": str(e)}

    async def send_discord(self, embed: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a rich embed via Discord Webhook using store settings."""
        if not settings.get("notify_discord"):
            return {"ok": False, "reason": "notify_discord_disabled"}

        webhook_url = settings.get("discord_webhook_url")
        return await self.send_discord_notification(webhook_url, embed)

    async def notify_merchant(
        self,
        event_type: str,
        data: Dict[str, Any],
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Dispatches merchant alerts across configured mobile channels.
        Safe against network errors, missing tokens, and formatting bugs.
        """
        tg_toggle = bool(settings.get("notify_telegram"))
        dc_toggle = bool(settings.get("notify_discord"))

        # Zero network calls if both channels are disabled
        if not tg_toggle and not dc_toggle:
            return {
                "ok": True,
                "dispatched": False,
                "reason": "both_channels_disabled"
            }

        tg_res = {"ok": False, "skipped": True}
        dc_res = {"ok": False, "skipped": True}

        # 1. Telegram
        if tg_toggle:
            tg_token = (settings.get("telegram_bot_token") or "").strip()
            tg_chat = str(settings.get("telegram_chat_id") or "").strip()
            if tg_token and tg_chat:
                try:
                    tg_text = self.format_telegram_message(event_type, data)
                    tg_res = await self.send_telegram_notification(tg_token, tg_chat, tg_text)
                except Exception as e:
                    tg_res = {"ok": False, "error": f"formatting_error: {str(e)}"}
            else:
                tg_res = {"ok": False, "reason": "missing_telegram_credentials"}

        # 2. Discord
        if dc_toggle:
            dc_url = (settings.get("discord_webhook_url") or "").strip()
            if dc_url:
                try:
                    dc_embed = self.format_discord_embed(event_type, data)
                    dc_res = await self.send_discord_notification(dc_url, dc_embed)
                except Exception as e:
                    dc_res = {"ok": False, "error": f"formatting_error: {str(e)}"}
            else:
                dc_res = {"ok": False, "reason": "missing_discord_webhook_url"}

        overall_ok = (tg_res.get("ok", False) if tg_toggle else True) and \
                     (dc_res.get("ok", False) if dc_toggle else True)

        return {
            "ok": overall_ok,
            "telegram": tg_res,
            "discord": dc_res
        }
