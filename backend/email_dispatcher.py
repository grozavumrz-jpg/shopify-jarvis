import os
import re
import html
import urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import httpx
from typing import Dict, Any, List, Optional, Union


EMAIL_I18N: Dict[str, Dict[str, str]] = {
    "en": {
        "items_header": "YOUR RESERVED SELECTION",
        "qty": "Qty",
        "price": "Price",
        "discount_reserved": "RESERVED DISCOUNT CODE",
        "discount_auto_apply": "Automatically applied at checkout by clicking below",
        "cta_discount": "Complete Order with {discount} Off →",
        "cta_discount_generic": "Complete Order with Discount →",
        "cta_neutral": "Complete Your Order →",
        "secure_checkout": "🔒 Secure 256-Bit SSL Checkout • Priority Dispatch",
        "footer_text": "© {shop_name} • You received this email because you initiated an order on our store.",
        "preheader_default": "Your items are waiting for you at {shop_name}",
    },
    "ro": {
        "items_header": "PRODUSELE TALE REZERVATE",
        "qty": "Cantitate",
        "price": "Preț",
        "discount_reserved": "COD DE REDUCERE REZERVAT",
        "discount_auto_apply": "Se aplică automat dând click pe butonul de mai jos",
        "cta_discount": "Finalizează Comanda cu {discount} Reducere →",
        "cta_discount_generic": "Finalizează Comanda cu Reducere →",
        "cta_neutral": "Finalizează Comanda Acum →",
        "secure_checkout": "🔒 Plată 100% Securizată SSL • Livrare Prioritară",
        "footer_text": "© {shop_name} • Ai primit acest mesaj pentru că ai inițiat o comandă pe magazinul nostru.",
        "preheader_default": "Produsele tale te așteaptă la {shop_name}",
    },
    "it": {
        "items_header": "I TUOI ARTICOLI RISERVATI",
        "qty": "Qtà",
        "price": "Prezzo",
        "discount_reserved": "CODICE SCONTO RISERVATO",
        "discount_auto_apply": "Applicato automaticamente cliccando sul pulsante qui sotto",
        "cta_discount": "Completa l'Ordine con lo Sconto {discount} →",
        "cta_discount_generic": "Completa l'Ordine con lo Sconto →",
        "cta_neutral": "Completa il Tuo Ordine →",
        "secure_checkout": "🔒 Checkout Sicuro SSL a 256 Bit • Spedizione Prioritaria",
        "footer_text": "© {shop_name} • Hai ricevuto questa email perché hai avviato un ordine sul nostro negozio.",
        "preheader_default": "I tuoi articoli ti aspettano su {shop_name}",
    },
    "es": {
        "items_header": "TUS ARTÍCULOS RESERVADOS",
        "qty": "Cant.",
        "price": "Precio",
        "discount_reserved": "CÓDIGO DE DESCUENTO RESERVADO",
        "discount_auto_apply": "Se aplica automáticamente al hacer clic en el botón de abajo",
        "cta_discount": "Finalizar Pedido con {discount} de Descuento →",
        "cta_discount_generic": "Finalizar Pedido con Descuento →",
        "cta_neutral": "Finalizar Mi Pedido →",
        "secure_checkout": "🔒 Pago Seguro SSL de 256 Bits • Envío Prioritario",
        "footer_text": "© {shop_name} • Has recibido este correo porque iniciaste un pedido en nuestra tienda.",
        "preheader_default": "Tus artículos te están esperando en {shop_name}",
    },
    "de": {
        "items_header": "DEINE RESERVIERTE AUSWAHL",
        "qty": "Menge",
        "price": "Preis",
        "discount_reserved": "RESERVIERTER GUTSCHEINCODE",
        "discount_auto_apply": "Wird automatisch angewendet beim Klick auf den Button unten",
        "cta_discount": "Bestellung mit {discount} Rabatt abschließen →",
        "cta_discount_generic": "Bestellung mit Rabatt abschließen →",
        "cta_neutral": "Bestellung jetzt abschließen →",
        "secure_checkout": "🔒 Sichere 256-Bit SSL-Kasse • Prioritärer Versand",
        "footer_text": "© {shop_name} • Sie haben diese E-Mail erhalten, weil Sie eine Bestellung in unserem Shop begonnen haben.",
        "preheader_default": "Deine Artikel warten auf dich bei {shop_name}",
    },
    "fr": {
        "items_header": "VOTRE SÉLECTION RÉSERVÉE",
        "qty": "Qté",
        "price": "Prix",
        "discount_reserved": "CODE DE RÉDUCTION RÉSERVÉ",
        "discount_auto_apply": "Appliqué automatiquement en cliquant sur le bouton ci-dessous",
        "cta_discount": "Finaliser ma Commande avec {discount} de Réduction →",
        "cta_discount_generic": "Finaliser ma Commande avec Réduction →",
        "cta_neutral": "Finaliser ma Commande →",
        "secure_checkout": "🔒 Paiement Sécurisé SSL 256 Bits • Expédition Prioritaire",
        "footer_text": "© {shop_name} • Vous avez reçu cet e-mail car vous avez initié une commande sur notre boutique.",
        "preheader_default": "Vos articles vous attendent sur {shop_name}",
    },
}


class EmailDispatcher:
    """
    Delivers custom recovery emails directly to customer inboxes via:
    1. Resend API (Recommended: fast, 3000 free emails/mo, 100% inbox delivery)
    2. SMTP (Gmail, Outlook, Brevo, SendGrid, custom domain)
    """

    @staticmethod
    def _normalize_lang(lang: str) -> str:
        clean = (lang or "en").strip().lower().replace("_", "-").split("-")[0]
        return clean if clean in EMAIL_I18N else "en"

    @staticmethod
    def _extract_discount_percentage(discount_code: Optional[str]) -> Optional[str]:
        if not discount_code:
            return None
        match = re.search(r"(?<!\d)([1-9][0-9]?)(?!\d)", str(discount_code))
        if match:
            pct = int(match.group(1))
            if 1 <= pct <= 99:
                return f"{pct}%"
        return None

    @classmethod
    def _render_showcase_section(
        cls,
        line_items: Optional[List[Dict[str, Any]]],
        items_str: str,
        product_image_url: Optional[str],
        currency: str,
        labels: Dict[str, str],
    ) -> str:
        """Renders the product showcase section with 90x90 thumbnails and itemized details."""
        rows_html = []

        if line_items and len(line_items) > 0:
            for i, item in enumerate(line_items):
                raw_title = item.get("title") or "Item"
                title = html.escape(str(raw_title))
                raw_variant = item.get("variant_title") or ""
                variant = html.escape(str(raw_variant))
                # Suppress variant if empty or 'Default Title'
                show_variant = bool(raw_variant and raw_variant.strip() and raw_variant.strip().lower() != "default title")
                
                qty = item.get("quantity") or 1
                price_val = item.get("price")
                try:
                    raw_price = f"{float(price_val):.2f} {currency}" if price_val is not None else ""
                except (ValueError, TypeError):
                    raw_price = f"{price_val} {currency}" if price_val else ""
                price_str = html.escape(raw_price)

                img_url = item.get("image_url")
                if img_url and str(img_url).startswith("http"):
                    safe_img_url = html.escape(str(img_url))
                    thumbnail_html = (
                        f'<img src="{safe_img_url}" alt="{title}" width="90" height="90" '
                        f'style="width: 90px; height: 90px; max-width: 90px; max-height: 90px; '
                        f'border-radius: 8px; object-fit: cover; display: block; border: 1px solid #e2e8f0;" />'
                    )
                else:
                    thumbnail_html = (
                        '<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="90" height="90" '
                        'style="width: 90px; height: 90px; max-width: 90px; max-height: 90px; '
                        'background-color: #f1f5f9; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center;">'
                        '<tr><td align="center" valign="middle" style="font-size: 26px; line-height: 1;">🛍️</td></tr>'
                        '</table>'
                    )

                variant_markup = (
                    f'<div style="font-size: 13px; color: #64748b; margin-bottom: 6px; line-height: 1.3;">{variant}</div>'
                    if show_variant else ""
                )

                is_last = (i == len(line_items) - 1)
                border_bottom = "" if is_last else "border-bottom: 1px solid #f1f5f9;"

                row = f"""
                <tr>
                  <td style="padding: 16px 0; {border_bottom}" valign="middle">
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                      <tr>
                        <td width="90" valign="middle" style="width: 90px; max-width: 90px; min-width: 90px; padding-right: 16px;">
                          {thumbnail_html}
                        </td>
                        <td valign="middle" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: left;">
                          <div style="font-size: 15px; font-weight: 600; color: #0f172a; line-height: 1.35; margin-bottom: 4px;">{title}</div>
                          {variant_markup}
                          <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin-top: 4px;">
                            <tr>
                              <td style="font-size: 13px; color: #64748b; padding-right: 14px;">
                                {labels['qty']}: <span style="font-weight: 600; color: #1e293b;">{qty}</span>
                              </td>
                              <td style="font-size: 14px; font-weight: 700; color: #0f172a;">
                                {price_str}
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>"""
                rows_html.append(row)
        else:
            # Legacy fallback or default placeholder
            title = html.escape(str(items_str or labels["items_header"]))
            if product_image_url and product_image_url.startswith("http"):
                safe_img = html.escape(str(product_image_url))
                thumbnail_html = (
                    f'<img src="{safe_img}" alt="{title}" width="90" height="90" '
                    f'style="width: 90px; height: 90px; max-width: 90px; max-height: 90px; '
                    f'border-radius: 8px; object-fit: cover; display: block; border: 1px solid #e2e8f0;" />'
                )
            else:
                thumbnail_html = (
                    '<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="90" height="90" '
                    'style="width: 90px; height: 90px; max-width: 90px; max-height: 90px; '
                    'background-color: #f1f5f9; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center;">'
                    '<tr><td align="center" valign="middle" style="font-size: 26px; line-height: 1;">🛍️</td></tr>'
                    '</table>'
                )

            row = f"""
            <tr>
              <td style="padding: 16px 0;" valign="middle">
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                  <tr>
                    <td width="90" valign="middle" style="width: 90px; max-width: 90px; min-width: 90px; padding-right: 16px;">
                      {thumbnail_html}
                    </td>
                    <td valign="middle" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: left;">
                      <div style="font-size: 15px; font-weight: 600; color: #0f172a; line-height: 1.35; margin-bottom: 4px;">{title}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>"""
            rows_html.append(row)

        content_rows = "\n".join(rows_html)

        return f"""
        <!-- PRODUCT SHOWCASE SECTION -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 24px 0; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff; overflow: hidden; border-collapse: separate;">
          <tr>
            <td style="background-color: #f8fafc; padding: 12px 20px; border-bottom: 1px solid #e2e8f0;">
              <span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 1.5px; text-transform: uppercase;">
                {labels['items_header']}
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding: 4px 20px;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                {content_rows}
              </table>
            </td>
          </tr>
        </table>"""

    @classmethod
    def build_html_email(
        cls,
        shop_name: str,
        customer_name: str = "Client",
        items_str: str = "",
        checkout_url: str = "",
        text_body: str = "",
        discount_code: Optional[str] = None,
        product_image_url: Optional[str] = None,
        line_items: Optional[List[Dict[str, Any]]] = None,
        lang: str = "en",
        currency: str = "EUR",
        preheader: Optional[str] = None,
        customer_email: Optional[str] = None,
    ) -> str:
        clean_lang = cls._normalize_lang(lang)
        labels = EMAIL_I18N[clean_lang]
        
        safe_shop_name = html.escape(str(shop_name or ""))
        safe_body = html.escape(str(text_body or ""))
        formatted_body = safe_body.replace("\n", "<br/>") if safe_body else ""
        preheader_text = html.escape(str(preheader)) if preheader else labels["preheader_default"].format(shop_name=safe_shop_name)

        # 1. Product Showcase HTML
        showcase_html = cls._render_showcase_section(
            line_items=line_items,
            items_str=items_str,
            product_image_url=product_image_url,
            currency=currency,
            labels=labels,
        )

        # 2. Cadence-Aware Discount Card & Effective URL
        has_discount = bool(discount_code and str(discount_code).strip())
        discount_card_html = ""
        effective_checkout_url = checkout_url or "#"

        if has_discount:
            code_str = str(discount_code).strip()
            discount_pct = cls._extract_discount_percentage(code_str)
            safe_code_str = html.escape(code_str)
            
            # Format discount banner header
            if discount_pct:
                header_badge = f"{labels['discount_reserved']} ({discount_pct} OFF):"
                cta_label = labels["cta_discount"].format(discount=discount_pct)
            else:
                header_badge = f"{labels['discount_reserved']}:"
                cta_label = labels["cta_discount_generic"]

            # Auto-apply discount in checkout link
            if effective_checkout_url and "discount=" not in effective_checkout_url and effective_checkout_url != "#":
                delimiter = "&" if "?" in effective_checkout_url else "?"
                effective_checkout_url = f"{effective_checkout_url}{delimiter}discount={code_str}"

            discount_card_html = f"""
        <!-- CADENCE DISCOUNT CARD -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f0fdf4; border: 2px dashed #10b981; border-radius: 10px; margin: 24px 0;">
          <tr>
            <td align="center" style="padding: 20px 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
              <div style="font-size: 12px; color: #047857; text-transform: uppercase; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 8px;">
                {header_badge}
              </div>
              <div style="display: inline-block; background-color: #ffffff; border: 1px solid #d1fae5; border-radius: 8px; padding: 10px 24px; font-family: 'Courier New', Courier, monospace; font-size: 24px; font-weight: 800; color: #065f46; letter-spacing: 3px; box-shadow: 0 2px 8px rgba(16, 185, 129, 0.08);">
                {safe_code_str}
              </div>
              <div style="font-size: 12px; color: #047857; margin-top: 8px;">
                {labels['discount_auto_apply']}
              </div>
            </td>
          </tr>
        </table>"""
        else:
            cta_label = labels["cta_neutral"]

        safe_checkout_url = html.escape(effective_checkout_url)
        footer_content = labels["footer_text"].format(shop_name=safe_shop_name)
        app_url = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://shopify-jarvis.onrender.com"
        clean_email_param = urllib.parse.quote(customer_email.strip()) if customer_email else ""
        unsub_link = f"{app_url}/api/unsubscribe?email={clean_email_param}"

        return f"""<!DOCTYPE html>
<html lang="{clean_lang}" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <title>{safe_shop_name}</title>
  <!--[if mso]>
  <xml>
    <o:OfficeDocumentSettings>
      <o:AllowPNG/>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings>
  </xml>
  <![endif]-->
  <style type="text/css">
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; display: block; }}
    body {{ margin: 0; padding: 0; width: 100% !important; min-width: 100%; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
    a[x-apple-data-detectors] {{ color: inherit !important; text-decoration: none !important; font-size: inherit !important; font-family: inherit !important; font-weight: inherit !important; line-height: inherit !important; }}
    @media only screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; max-width: 100% !important; border-radius: 0 !important; }}
      .body-padding {{ padding: 24px 16px !important; }}
      .btn {{ display: block !important; width: 100% !important; box-sizing: border-box !important; text-align: center !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 20px 0; background-color: #f8fafc;">
  <!-- PREHEADER (Hidden preview text) -->
  <div style="display: none; font-size: 1px; color: #f8fafc; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all;">
    {preheader_text}
    &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy;
  </div>

  <!--[if (gte mso 9)|(IE)]>
  <table align="center" border="0" cellpadding="0" cellspacing="0" width="600" style="width:600px;">
  <tr>
  <td align="center" valign="top">
  <![endif]-->

  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="email-container" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);">
    <!-- BRAND HEADER -->
    <tr>
      <td align="center" style="background-color: #0f172a; padding: 28px 24px;">
        <h1 style="margin: 0; font-family: 'Playfair Display', Georgia, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 22px; font-weight: 700; color: #ffffff; letter-spacing: 2px; text-transform: uppercase;">
          {safe_shop_name}
        </h1>
      </td>
    </tr>

    <!-- EMAIL BODY -->
    <tr>
      <td class="body-padding" style="padding: 32px 28px;">
        <!-- Greeting / Message -->
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.65; color: #334155; margin-bottom: 24px;">
          {formatted_body}
        </div>

        {showcase_html}

        {discount_card_html}

        <!-- CTA BUTTON & TRUST BADGE -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 28px 0 20px 0;">
          <tr>
            <td align="center">
              <!--[if mso]>
              <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{safe_checkout_url}" style="height:52px;v-text-anchor:middle;width:340px;" arcsize="15%" stroke="f" fillcolor="#0f172a">
                <w:anchorlock/>
                <center style="color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:15px;font-weight:bold;">
                  {cta_label}
                </center>
              </v:roundrect>
              <![endif]-->
              <!--[if !mso]><!-->
              <a href="{safe_checkout_url}" target="_blank" class="btn" style="display: inline-block; background-color: #0f172a; color: #ffffff !important; padding: 16px 36px; border-radius: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; font-weight: 700; text-decoration: none; letter-spacing: 0.5px; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.18); mso-padding-alt: 0;">
                {cta_label}
              </a>
              <!--<![endif]-->
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; color: #64748b;">
              {labels['secure_checkout']}
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td align="center" style="padding: 24px 20px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; line-height: 1.5; color: #94a3b8;">
        {footer_content}
        <br/>
        <a href="{unsub_link}" style="color: #64748b; text-decoration: underline; margin-top: 8px; display: inline-block;">Dezabonare / Unsubscribe</a>
      </td>
    </tr>
  </table>

  <!--[if (gte mso 9)|(IE)]>
  </td>
  </tr>
  </table>
  <![endif]-->
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

        app_url = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://shopify-jarvis.onrender.com"
        clean_email_param = urllib.parse.quote(to_email.strip())
        unsub_link = f"{app_url}/api/unsubscribe?email={clean_email_param}"
        unsub_header_val = f"<mailto:contact@maisongrozavu.com?subject=unsubscribe>, <{unsub_link}>"

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
                    "text": body_text,
                    "headers": {
                        "List-Unsubscribe": unsub_header_val,
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"
                    }
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
                msg["List-Unsubscribe"] = unsub_header_val
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

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
