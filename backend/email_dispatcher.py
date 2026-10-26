import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import httpx
from typing import Dict, Optional


class EmailDispatcher:
    """
    Delivers custom recovery emails directly to customer inboxes via:
    1. Resend API (Recommended: fast, 3000 free emails/mo, 100% inbox delivery)
    2. SMTP (Gmail, Outlook, Brevo, SendGrid, custom domain)
    """

    @staticmethod
    def build_html_email(shop_name: str, customer_name: str, items_str: str, checkout_url: str, text_body: str, discount_code: str = "JARVIS10") -> str:
        formatted_body = text_body.replace("\n", "<br/>")
        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{shop_name}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
    .header {{ background: #0f172a; padding: 24px; text-align: center; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 22px; letter-spacing: 1px; text-transform: uppercase; }}
    .body {{ padding: 32px 28px; line-height: 1.6; font-size: 15px; color: #334155; }}
    .coupon-box {{ background: #ecfdf5; border: 1px dashed #10b981; border-radius: 8px; padding: 14px; text-align: center; margin: 24px 0; }}
    .coupon-code {{ font-family: monospace; font-size: 22px; font-weight: 700; color: #047857; letter-spacing: 2px; }}
    .btn-wrap {{ text-align: center; margin: 28px 0; }}
    .btn {{ display: inline-block; background: #0f172a; color: #ffffff !important; padding: 14px 32px; border-radius: 8px; font-weight: 700; text-decoration: none; font-size: 15px; letter-spacing: 0.5px; }}
    .btn:hover {{ background: #1e293b; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{shop_name}</h1>
    </div>
    <div class="body">
      <p>{formatted_body}</p>
      
      <div class="coupon-box">
        <div style="font-size: 12px; color: #059669; text-transform: uppercase; font-weight: 600; margin-bottom: 4px;">Cod de reducere rezervat (10% OFF):</div>
        <div class="coupon-code">{discount_code}</div>
        <div style="font-size: 11px; color: #64748b; margin-top: 4px;">Se aplică automat dând click pe butonul de mai jos</div>
      </div>

      <div class="btn-wrap">
        <a href="{checkout_url}" class="btn" target="_blank">Finalizează Comanda cu 10% Reducere →</a>
      </div>
    </div>
    <div class="footer">
      © {shop_name} • Ai primit acest mesaj pentru că ai inițiat o comandă pe magazinul nostru.
    </div>
  </div>
</body>
</html>"""

    async def send_email(self, to_email: str, subject: str, body_text: str, body_html: Optional[str] = None, settings: Optional[dict] = None) -> Dict:
        """Dispatch email using configured settings or environment variables."""
        if not to_email or "@" not in to_email or to_email.endswith("@ilovemyemail.net") or to_email.endswith("@example.com"):
            return {"success": False, "reason": "Adresă email invalidă sau de test"}

        settings = settings or {}
        resend_key = (settings.get("resend_api_key") or os.getenv("RESEND_API_KEY", "")).strip()
        from_email = (settings.get("sender_email") or os.getenv("SENDER_EMAIL", "onboarding@resend.dev")).strip()
        from_name = settings.get("sender_name", "Grozavu")

        # 1. Try Resend API if key is present
        if resend_key:
            try:
                headers = {
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "from": f"{from_name} <{from_email}>",
                    "to": [to_email],
                    "subject": subject,
                    "html": body_html or body_text.replace("\n", "<br/>"),
                    "text": body_text
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post("https://api.resend.com/emails", headers=headers, json=payload)
                    if resp.status_code in (200, 201):
                        return {"success": True, "provider": "resend", "data": resp.json()}
                    else:
                        print(f"[Resend Error] {resp.status_code}: {resp.text}")
                        return {"success": False, "provider": "resend", "error": resp.text}
            except Exception as e:
                print(f"[Resend Exception] {e}")

        # 2. Try SMTP if configured
        smtp_host = (settings.get("smtp_host") or os.getenv("SMTP_HOST", "")).strip()
        smtp_user = (settings.get("smtp_user") or os.getenv("SMTP_USER", "")).strip()
        smtp_pass = (settings.get("smtp_password") or os.getenv("SMTP_PASSWORD", "")).strip()
        smtp_port = int(settings.get("smtp_port") or os.getenv("SMTP_PORT", "587"))

        if smtp_host and smtp_user and smtp_pass:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = f"{from_name} <{smtp_user}>"
                msg["To"] = to_email

                part1 = MIMEText(body_text, "plain", "utf-8")
                msg.attach(part1)
                if body_html:
                    part2 = MIMEText(body_html, "html", "utf-8")
                    msg.attach(part2)

                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_email], msg.as_string())
                server.quit()
                return {"success": True, "provider": "smtp"}
            except Exception as e:
                print(f"[SMTP Exception] {e}")
                return {"success": False, "provider": "smtp", "error": str(e)}

        return {
            "success": False,
            "provider": "none",
            "reason": "Niciun serviciu de expediere email configurat (Resend API Key sau SMTP necesar)"
        }
