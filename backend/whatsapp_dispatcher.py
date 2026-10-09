import os
import httpx
import urllib.parse
from typing import Dict, Optional


class WhatsAppDispatcher:
    """
    Autonomous WhatsApp dispatch engine supporting:
    1. Meta WhatsApp Business Cloud API (Official)
    2. Twilio WhatsApp API
    3. Custom Webhook Gateway
    4. Fallback direct 1-click wa.me link
    """

    def __init__(self):
        # Meta Cloud API
        self.meta_token = os.getenv("WHATSAPP_API_TOKEN", "").strip()
        self.meta_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()

        # Twilio API
        self.twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886").strip()

        # Generic webhook gateway (UltraMsg, GreenAPI, etc.)
        self.webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL", "").strip()

    def clean_phone_number(self, phone: str) -> str:
        """Sanitize phone number to standard international format (without + or spaces)."""
        if not phone:
            return ""
        cleaned = "".join(ch for ch in phone if ch.isdigit())
        # If Italian mobile without country code (starts with 3, 10 digits)
        if len(cleaned) == 10 and cleaned.startswith("3"):
            return "39" + cleaned
        # If Spanish mobile (starts with 6 or 7, 9 digits)
        if len(cleaned) == 9 and cleaned[0] in ("6", "7"):
            return "34" + cleaned
        # If Romanian mobile (starts with 07, 10 digits)
        if len(cleaned) == 10 and cleaned.startswith("07"):
            return "40" + cleaned[1:]
        # If German mobile (starts with 015, 016, 017)
        if cleaned.startswith("01") and len(cleaned) in (11, 12):
            return "49" + cleaned[1:]
        return cleaned

    def generate_wa_me_link(self, phone: str, message: str) -> str:
        """Generate direct wa.me link with pre-filled message."""
        clean = self.clean_phone_number(phone)
        encoded_msg = urllib.parse.quote(message)
        return f"https://api.whatsapp.com/send?phone={clean}&text={encoded_msg}"

    async def send_autonomous_whatsapp(self, phone: str, customer_name: str, message: str) -> Dict:
        """
        Autonomously dispatch WhatsApp message through configured gateway.
        """
        clean_phone = self.clean_phone_number(phone)
        if not clean_phone or len(clean_phone) < 8:
            return {
                "success": False,
                "gateway": "none",
                "error": "Număr de telefon invalid sau prea scurt"
            }

        # 1. Try Meta Cloud API (Official WhatsApp API)
        if self.meta_token and self.meta_phone_id:
            try:
                url = f"https://graph.facebook.com/v19.0/{self.meta_phone_id}/messages"
                headers = {
                    "Authorization": f"Bearer {self.meta_token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_phone,
                    "type": "text",
                    "text": {"preview_url": True, "body": message}
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code in (200, 201):
                        return {"success": True, "gateway": "meta_cloud_api", "id": resp.json().get("messages", [{}])[0].get("id")}
                    else:
                        print(f"[Meta WA Error] {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"[Meta WA Exception] {e}")

        # 2. Try Twilio WhatsApp API
        if self.twilio_sid and self.twilio_token:
            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
                auth = (self.twilio_sid, self.twilio_token)
                data = {
                    "From": self.twilio_from,
                    "To": f"whatsapp:+{clean_phone}",
                    "Body": message
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(url, auth=auth, data=data)
                    if resp.status_code in (200, 201):
                        return {"success": True, "gateway": "twilio", "sid": resp.json().get("sid")}
                    else:
                        print(f"[Twilio WA Error] {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"[Twilio WA Exception] {e}")

        # 3. Try Generic Webhook Gateway
        if self.webhook_url:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(self.webhook_url, json={
                        "phone": clean_phone,
                        "customer_name": customer_name,
                        "message": message
                    })
                    if resp.status_code in (200, 201):
                        return {"success": True, "gateway": "webhook"}
            except Exception as e:
                print(f"[Webhook WA Exception] {e}")

        # 4. Fallback: Direct 1-Click link available for manual/instant launch
        wa_link = self.generate_wa_me_link(phone, message)
        return {
            "success": False,
            "gateway": "wa_me_link",
            "wa_link": wa_link,
            "notice": "Mesaj WhatsApp generat cu succes! Pentru trimitere directă din cloud API, configurează WHATSAPP_API_TOKEN sau TWILIO în setări."
        }
