import os
import re
import ssl
import html
import asyncio
import logging
import urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, formataddr, formatdate, make_msgid
import httpx
from typing import Dict, Any, List, Optional, Union, Tuple

try:
    import net_guard
except ImportError:  # pragma: no cover - package-style import
    from backend import net_guard

logger = logging.getLogger("jarvis.email")


DEFAULT_APP_URL = "https://shopify-jarvis.onrender.com"
UNSUBSCRIBE_PLACEHOLDER = "%%JARVIS_UNSUBSCRIBE_URL%%"
_TEST_DOMAINS = ("@ilovemyemail.net", "@example.com")
_GENERIC_MAIL_DOMAINS = ("resend.dev", "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com")


def _norm_email(value: Optional[str]) -> str:
    return (value or "").strip().lower() if isinstance(value, str) else ""


def build_unsubscribe_url(shop: Optional[str], email: Optional[str]) -> str:
    """
    Public one-click unsubscribe URL for a customer email:
    {APP_URL|RENDER_EXTERNAL_URL|https://shopify-jarvis.onrender.com}/api/unsubscribe?email=...&shop=...
    The same URL is used in the email footer and in the List-Unsubscribe header.
    """
    base = (os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or DEFAULT_APP_URL).strip().rstrip("/")
    params = [("email", _norm_email(email))]
    clean_shop = (shop or "").strip().lower() if isinstance(shop, str) else ""
    if clean_shop:
        params.append(("shop", clean_shop))
    return f"{base}/api/unsubscribe?{urllib.parse.urlencode(params)}"


def _domain_from_address(value: Optional[str]) -> str:
    if not value:
        return ""
    _, addr = parseaddr(str(value))
    if "@" not in addr:
        return ""
    return addr.split("@", 1)[1].strip().lower()


def resolve_brand_domain(shop_domain: Optional[str] = None, brand_domain: Optional[str] = None) -> str:
    """Sender domain shown in the footer: explicit > env STORE_DOMAIN > SENDER_EMAIL domain > shop domain."""
    for candidate in (brand_domain, os.getenv("STORE_DOMAIN"), os.getenv("PUBLIC_STORE_DOMAIN")):
        if candidate and str(candidate).strip():
            c = str(candidate).strip().lower()
            c = re.sub(r"^https?://", "", c).split("/")[0]
            if c:
                return c
    sender_domain = _domain_from_address(os.getenv("SENDER_EMAIL"))
    if sender_domain and sender_domain not in _GENERIC_MAIL_DOMAINS:
        return sender_domain
    feed_domain = re.sub(r"^https?://", "", (os.getenv("FEED_DOMAIN") or "").strip().lower()).split("/")[0]
    if feed_domain:
        return feed_domain  # the storefront domain, never the internal *.myshopify.com one
    return (shop_domain or "").strip().lower() if isinstance(shop_domain, str) else ""


def email_logo_url() -> str:
    """HTTPS URL of the white logo shown on the black email header (EMAIL_LOGO_URL). Empty = text only."""
    url = (os.getenv("EMAIL_LOGO_URL") or "").strip()
    return url if url.startswith("https://") else ""


EMAIL_I18N: Dict[str, Dict[str, str]] = {
    "en": {
        "items_header": "ITEMS IN YOUR CART",
        "vip_items_header": "YOUR ORDER",
        "qty": "Qty",
        "price": "Price",
        "discount_reserved": "YOUR DISCOUNT CODE",
        "vip_discount_header": "YOUR CODE FOR YOUR NEXT ORDER",
        "discount_auto_apply": "The button below adds it to your checkout — you can also enter it manually",
        "vip_discount_hint": "Enter it at checkout on your next order",
        "cta_discount": "Complete Order with {discount} Off →",
        "cta_discount_generic": "Complete Order with Discount →",
        "cta_neutral": "Complete Your Order →",
        "cta_vip": "Discover the collection →",
        "secure_checkout": "🔒 Secure checkout by Shopify",
        "commercial_label": "Marketing communication",
        "footer_reason": "You are receiving this email because you agreed to receive marketing emails from {shop_name}.",
        "unsubscribe": "Unsubscribe",
        "internal_footer": "Internal notification for the store team — not sent to customers.",
        "preheader_default": "Your cart at {shop_name}",
        "vip_preheader_default": "Thank you for your order at {shop_name}",
    },
    "ro": {
        "items_header": "PRODUSELE DIN COȘUL TĂU",
        "vip_items_header": "COMANDA TA",
        "qty": "Cantitate",
        "price": "Preț",
        "discount_reserved": "CODUL TĂU DE REDUCERE",
        "vip_discount_header": "CODUL TĂU PENTRU URMĂTOAREA COMANDĂ",
        "discount_auto_apply": "Butonul de mai jos îl adaugă la checkout — îl poți introduce și manual",
        "vip_discount_hint": "Introdu-l la checkout la următoarea comandă",
        "cta_discount": "Finalizează Comanda cu {discount} Reducere →",
        "cta_discount_generic": "Finalizează Comanda cu Reducere →",
        "cta_neutral": "Finalizează Comanda Acum →",
        "cta_vip": "Descoperă colecția →",
        "secure_checkout": "🔒 Plată securizată prin Shopify",
        "commercial_label": "Comunicare comercială",
        "footer_reason": "Primești acest email pentru că ai acceptat să primești comunicări de marketing de la {shop_name}.",
        "unsubscribe": "Dezabonare",
        "internal_footer": "Notificare internă pentru echipa magazinului — nu este trimisă clienților.",
        "preheader_default": "Coșul tău la {shop_name}",
        "vip_preheader_default": "Îți mulțumim pentru comanda la {shop_name}",
    },
    "it": {
        "items_header": "GLI ARTICOLI NEL TUO CARRELLO",
        "vip_items_header": "IL TUO ORDINE",
        "qty": "Qtà",
        "price": "Prezzo",
        "discount_reserved": "IL TUO CODICE SCONTO",
        "vip_discount_header": "IL TUO CODICE PER IL PROSSIMO ORDINE",
        "discount_auto_apply": "Il pulsante qui sotto lo aggiunge al checkout — puoi anche inserirlo manualmente",
        "vip_discount_hint": "Inseriscilo al checkout nel tuo prossimo ordine",
        "cta_discount": "Completa l'Ordine con lo Sconto {discount} →",
        "cta_discount_generic": "Completa l'Ordine con lo Sconto →",
        "cta_neutral": "Completa il Tuo Ordine →",
        "cta_vip": "Scopri la collezione →",
        "secure_checkout": "🔒 Checkout sicuro con Shopify",
        "commercial_label": "Comunicazione commerciale",
        "footer_reason": "Ricevi questa email perché hai accettato di ricevere comunicazioni di marketing da {shop_name}.",
        "unsubscribe": "Annulla l'iscrizione",
        "internal_footer": "Notifica interna per il team del negozio — non inviata ai clienti.",
        "preheader_default": "Il tuo carrello su {shop_name}",
        "vip_preheader_default": "Grazie per il tuo ordine su {shop_name}",
    },
    "es": {
        "items_header": "LOS ARTÍCULOS DE TU CARRITO",
        "vip_items_header": "TU PEDIDO",
        "qty": "Cant.",
        "price": "Precio",
        "discount_reserved": "TU CÓDIGO DE DESCUENTO",
        "vip_discount_header": "TU CÓDIGO PARA TU PRÓXIMO PEDIDO",
        "discount_auto_apply": "El botón de abajo lo añade a tu pago — también puedes introducirlo manualmente",
        "vip_discount_hint": "Introdúcelo al finalizar tu próximo pedido",
        "cta_discount": "Finalizar Pedido con {discount} de Descuento →",
        "cta_discount_generic": "Finalizar Pedido con Descuento →",
        "cta_neutral": "Finalizar Mi Pedido →",
        "cta_vip": "Descubre la colección →",
        "secure_checkout": "🔒 Pago seguro con Shopify",
        "commercial_label": "Publicidad",
        "footer_reason": "Recibes este correo porque aceptaste recibir comunicaciones comerciales de {shop_name}.",
        "unsubscribe": "Darse de baja",
        "internal_footer": "Notificación interna para el equipo de la tienda — no se envía a clientes.",
        "preheader_default": "Tu carrito en {shop_name}",
        "vip_preheader_default": "Gracias por tu pedido en {shop_name}",
    },
    "de": {
        "items_header": "ARTIKEL IN DEINEM WARENKORB",
        "vip_items_header": "DEINE BESTELLUNG",
        "qty": "Menge",
        "price": "Preis",
        "discount_reserved": "DEIN RABATTCODE",
        "vip_discount_header": "DEIN CODE FÜR DEINE NÄCHSTE BESTELLUNG",
        "discount_auto_apply": "Der Button unten fügt ihn deinem Checkout hinzu — du kannst ihn auch manuell eingeben",
        "vip_discount_hint": "Gib ihn bei deiner nächsten Bestellung im Checkout ein",
        "cta_discount": "Bestellung mit {discount} Rabatt abschließen →",
        "cta_discount_generic": "Bestellung mit Rabatt abschließen →",
        "cta_neutral": "Bestellung jetzt abschließen →",
        "cta_vip": "Kollektion entdecken →",
        "secure_checkout": "🔒 Sicherer Checkout über Shopify",
        "commercial_label": "Werbung",
        "footer_reason": "Du erhältst diese E-Mail, weil du dem Erhalt von Marketing-E-Mails von {shop_name} zugestimmt hast.",
        "unsubscribe": "Abmelden",
        "internal_footer": "Interne Benachrichtigung für das Shop-Team — nicht an Kunden gesendet.",
        "preheader_default": "Dein Warenkorb bei {shop_name}",
        "vip_preheader_default": "Danke für deine Bestellung bei {shop_name}",
    },
    "fr": {
        "items_header": "LES ARTICLES DE VOTRE PANIER",
        "vip_items_header": "VOTRE COMMANDE",
        "qty": "Qté",
        "price": "Prix",
        "discount_reserved": "VOTRE CODE DE RÉDUCTION",
        "vip_discount_header": "VOTRE CODE POUR VOTRE PROCHAINE COMMANDE",
        "discount_auto_apply": "Le bouton ci-dessous l'ajoute à votre paiement — vous pouvez aussi le saisir manuellement",
        "vip_discount_hint": "Saisissez-le lors de votre prochaine commande",
        "cta_discount": "Finaliser ma Commande avec {discount} de Réduction →",
        "cta_discount_generic": "Finaliser ma Commande avec Réduction →",
        "cta_neutral": "Finaliser ma Commande →",
        "cta_vip": "Découvrir la collection →",
        "secure_checkout": "🔒 Paiement sécurisé via Shopify",
        "commercial_label": "Communication commerciale",
        "footer_reason": "Vous recevez cet e-mail car vous avez accepté de recevoir des communications marketing de {shop_name}.",
        "unsubscribe": "Se désabonner",
        "internal_footer": "Notification interne pour l'équipe de la boutique — non envoyée aux clients.",
        "preheader_default": "Votre panier sur {shop_name}",
        "vip_preheader_default": "Merci pour votre commande sur {shop_name}",
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
                
                qty = html.escape(str(item.get("quantity") or 1))
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
        customer_name: str = "",
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
        shop_domain: Optional[str] = None,
        email_kind: str = "cart",
        cta_url: Optional[str] = None,
        cta_label: Optional[str] = None,
        brand_domain: Optional[str] = None,
        is_internal: bool = False,
    ) -> str:
        """
        Customer email HTML. Footer identifies the sender (brand + domain), marks the
        message as commercial communication (es "Publicidad", ...) and carries a working
        unsubscribe link built with build_unsubscribe_url(shop_domain, customer_email).
        Without customer_email the link is a placeholder that send_email() fills in with
        the real recipient. email_kind: "cart" (abandoned checkout) or "vip" (post-delivery).
        is_internal=True (merchant alerts/tests): no marketing label, no unsubscribe link.
        """
        clean_lang = cls._normalize_lang(lang)
        labels = dict(EMAIL_I18N[clean_lang])
        kind = (email_kind or "cart").strip().lower()
        is_vip = kind == "vip"
        if is_vip:
            labels["items_header"] = labels["vip_items_header"]

        safe_shop_name = html.escape(str(shop_name or ""))
        safe_body = html.escape(str(text_body or ""))
        formatted_body = safe_body.replace("\n", "<br/>") if safe_body else ""
        if preheader:
            preheader_text = html.escape(str(preheader))
        else:
            key = "vip_preheader_default" if is_vip else "preheader_default"
            preheader_text = labels[key].format(shop_name=safe_shop_name)

        domain = resolve_brand_domain(shop_domain, brand_domain)
        storefront_url = f"https://{domain}" if domain else ""

        # 1. Product Showcase HTML
        showcase_html = cls._render_showcase_section(
            line_items=line_items,
            items_str=items_str,
            product_image_url=product_image_url,
            currency=currency,
            labels=labels,
        )

        # 2. Discount Card & Effective URL
        has_discount = bool(discount_code and str(discount_code).strip())
        discount_card_html = ""
        # Never a dead "#" button when the storefront domain is known.
        effective_checkout_url = cta_url or checkout_url or storefront_url or "#"

        if has_discount:
            code_str = str(discount_code).strip()
            discount_pct = cls._extract_discount_percentage(code_str)
            safe_code_str = html.escape(code_str)

            header_key = "vip_discount_header" if is_vip else "discount_reserved"
            if discount_pct:
                header_badge = f"{labels[header_key]} ({discount_pct} OFF):"
                default_cta = labels["cta_vip"] if is_vip else labels["cta_discount"].format(discount=discount_pct)
            else:
                header_badge = f"{labels[header_key]}:"
                default_cta = labels["cta_vip"] if is_vip else labels["cta_discount_generic"]
            final_cta = cta_label or default_cta
            hint = labels["vip_discount_hint"] if is_vip else labels["discount_auto_apply"]

            # Pre-fill the discount on the checkout link (cart emails only)
            if (not is_vip and effective_checkout_url and effective_checkout_url != "#"
                    and "discount=" not in effective_checkout_url):
                delimiter = "&" if "?" in effective_checkout_url else "?"
                effective_checkout_url = f"{effective_checkout_url}{delimiter}discount={urllib.parse.quote(code_str)}"

            discount_card_html = f"""
        <!-- CADENCE DISCOUNT CARD -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #fafafa; border: 2px dashed #111111; border-radius: 10px; margin: 24px 0;">
          <tr>
            <td align="center" style="padding: 20px 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
              <div style="font-size: 12px; color: #111111; text-transform: uppercase; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 8px;">
                {header_badge}
              </div>
              <div style="display: inline-block; background-color: #ffffff; border: 1px solid #e5e5e5; border-radius: 8px; padding: 10px 24px; font-family: 'Courier New', Courier, monospace; font-size: 24px; font-weight: 800; color: #000000; letter-spacing: 3px;">
                {safe_code_str}
              </div>
              <div style="font-size: 12px; color: #525252; margin-top: 8px;">
                {hint}
              </div>
            </td>
          </tr>
        </table>"""
        else:
            final_cta = cta_label or (labels["cta_vip"] if is_vip else labels["cta_neutral"])
        cta_label = html.escape(final_cta, quote=False)

        safe_checkout_url = html.escape(effective_checkout_url)
        trust_line = "" if is_vip else labels["secure_checkout"]

        logo_url = email_logo_url()
        logo_html = (
            f'<img src="{html.escape(logo_url)}" alt="{safe_shop_name}" width="96" '
            f'style="display: block; margin: 0 auto 14px auto; width: 96px; max-width: 96px; height: auto; border: 0;" />'
            if logo_url else ""
        )

        # 3. Footer: sender identity + commercial label + unsubscribe
        sender_identity = f"© {safe_shop_name}" + (f" · {html.escape(domain)}" if domain else "")
        if is_internal:
            footer_content = f"{sender_identity}<br/>{labels['internal_footer']}"
            unsubscribe_html = ""
        else:
            if customer_email and _norm_email(customer_email):
                unsub_href = html.escape(build_unsubscribe_url(shop_domain, customer_email))
            else:
                unsub_href = UNSUBSCRIBE_PLACEHOLDER
            footer_content = (
                f"<strong>{labels['commercial_label']}</strong> · {sender_identity}<br/>"
                f"{labels['footer_reason'].format(shop_name=safe_shop_name)}"
            )
            unsubscribe_html = (
                f'<br/><a href="{unsub_href}" style="color: #64748b; text-decoration: underline; '
                f'margin-top: 8px; display: inline-block;">{labels["unsubscribe"]}</a>'
            )

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
      <td align="center" style="background-color: #000000; padding: 30px 24px 26px 24px;">
        {logo_html}
        <h1 style="margin: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: 7px; text-transform: uppercase;">
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
              <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{safe_checkout_url}" style="height:52px;v-text-anchor:middle;width:340px;" arcsize="15%" stroke="f" fillcolor="#000000">
                <w:anchorlock/>
                <center style="color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:15px;font-weight:bold;">
                  {cta_label}
                </center>
              </v:roundrect>
              <![endif]-->
              <!--[if !mso]><!-->
              <a href="{safe_checkout_url}" target="_blank" class="btn" style="display: inline-block; background-color: #000000; color: #ffffff !important; padding: 16px 36px; border-radius: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; font-weight: 700; text-decoration: none; letter-spacing: 0.5px; mso-padding-alt: 0;">
                {cta_label}
              </a>
              <!--<![endif]-->
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; color: #64748b;">
              {trust_line}
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td align="center" style="padding: 24px 20px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12px; line-height: 1.5; color: #94a3b8;">
        {footer_content}
        {unsubscribe_html}
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


    # ── Sending ──────────────────────────────────────────────────────────────

    @staticmethod
    def resolve_sender(settings: Optional[dict] = None) -> Tuple[str, str]:
        """
        (display_name, address). Precedence: shop setting sender_email (unless it is the
        Resend placeholder and env is set) > env SENDER_EMAIL > onboarding@resend.dev.
        A display name already present in the address ("Name <addr>") is kept as-is
        (no double display-name); otherwise settings.sender_name or "Grozavu".
        """
        settings = settings or {}
        env_sender = (os.getenv("SENDER_EMAIL") or "").strip()
        cfg_sender = str(settings.get("sender_email") or "").strip()
        if cfg_sender and parseaddr(cfg_sender)[1].lower() == "onboarding@resend.dev" and env_sender:
            cfg_sender = ""
        raw = cfg_sender or env_sender or "onboarding@resend.dev"
        name, addr = parseaddr(raw)
        if not addr or "@" not in addr:
            name, addr = parseaddr(env_sender) if env_sender else ("", "")
            if not addr or "@" not in addr:
                name, addr = "", "onboarding@resend.dev"
        display = (name or str(settings.get("sender_name") or "").strip() or "Grozavu")
        display = re.sub(r'[\r\n<>"]', "", display).strip() or "Grozavu"
        return display, addr.strip()

    @staticmethod
    def _resolve_reply_to(settings: dict, reply_to: Optional[str]) -> str:
        candidate = reply_to or settings.get("reply_to_email") or os.getenv("REPLY_TO_EMAIL") or ""
        _, addr = parseaddr(str(candidate).strip())
        return addr if addr and "@" in addr else ""

    @staticmethod
    def _smtp_config(settings: dict) -> Dict[str, Any]:
        host = str(settings.get("smtp_host") or os.getenv("SMTP_HOST", "") or "").strip()
        user = str(settings.get("smtp_user") or os.getenv("SMTP_USER", "") or "").strip()
        password = str(settings.get("smtp_password") or os.getenv("SMTP_PASSWORD", "") or "").strip()
        try:
            port = int(settings.get("smtp_port") or os.getenv("SMTP_PORT", "587") or 587)
        except (TypeError, ValueError):
            port = 587
        return {"host": host, "user": user, "password": password, "port": port,
                "configured": bool(host and user and password)}

    @staticmethod
    def _smtp_send_blocking(cfg: Dict[str, Any], from_addr: str, to_addr: str, message: str) -> None:
        # Never send SMTP credentials to a private / loopback host, and verify the server certificate
        # (smtplib's default TLS context does NOT check certificates or hostnames).
        if not net_guard.host_resolves_public(cfg["host"], int(cfg["port"])):
            raise ValueError("SMTP host refuzat: trebuie să fie un server public (nu localhost / rețea privată)")
        tls_context = ssl.create_default_context()
        if int(cfg["port"]) == 465:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15, context=tls_context)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
            server.starttls(context=tls_context)
        try:
            server.login(cfg["user"], cfg["password"])
            # Envelope + header From = the configured sender (not the SMTP login).
            server.sendmail(from_addr, [to_addr], message)
        finally:
            try:
                server.quit()
            except Exception:
                pass

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        settings: Optional[dict] = None,
        shop_domain: Optional[str] = None,
        is_internal: bool = False,
        reply_to: Optional[str] = None,
        unsubscribe_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send via Resend (if a key is configured) and fall back to SMTP when Resend errors.
        Customer (non-internal) emails get List-Unsubscribe + List-Unsubscribe-Post:
        List-Unsubscribe=One-Click pointing to build_unsubscribe_url(shop, to_email), and the
        same URL replaces the unsubscribe placeholder in the HTML footer.
        is_internal=True (merchant alerts, GDPR export, test email): no unsubscribe headers.
        Consent is NOT checked here — use compliance_guard.can_dispatch_to_customer first.
        Always returns {"success": bool, "reason": str, "provider": str, ...}.
        """
        to_clean = (to_email or "").strip() if isinstance(to_email, str) else ""
        _, to_addr = parseaddr(to_clean)
        if (not to_addr or "@" not in to_addr or to_addr.lower().endswith(_TEST_DOMAINS)
                or any(ch in to_clean for ch in "\r\n")):
            return {"success": False, "provider": "none", "reason": "Adresă email invalidă sau de test"}

        settings = settings or {}
        shop = (shop_domain or settings.get("shop") or "")
        shop = shop.strip().lower() if isinstance(shop, str) else ""
        from_name, from_addr = self.resolve_sender(settings)
        reply_to_addr = self._resolve_reply_to(settings, reply_to)
        safe_subject = re.sub(r"[\r\n]+", " ", str(subject or "")).strip()

        text_part = str(body_text or "")
        html_part = body_html if body_html else html.escape(text_part).replace("\n", "<br/>")
        extra_headers: Dict[str, str] = {}
        unsub_link = ""
        if is_internal:
            html_part = html_part.replace(UNSUBSCRIBE_PLACEHOLDER, "")
        else:
            unsub_link = unsubscribe_url or build_unsubscribe_url(shop, to_addr)
            if UNSUBSCRIBE_PLACEHOLDER in html_part:
                html_part = html_part.replace(UNSUBSCRIBE_PLACEHOLDER, html.escape(unsub_link))
            elif unsub_link not in html_part and html.escape(unsub_link) not in html_part:
                html_part += (
                    f'<p style="font-size:12px;color:#64748b;"><a href="{html.escape(unsub_link)}">'
                    f'Unsubscribe / Darse de baja / Dezabonare</a></p>'
                )
            if unsub_link not in text_part:
                text_part = f"{text_part}\n\n--\nUnsubscribe / Darse de baja / Dezabonare: {unsub_link}"
            extra_headers = {
                "List-Unsubscribe": f"<{unsub_link}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }

        resend_key = str(settings.get("resend_api_key") or os.getenv("RESEND_API_KEY", "") or "").strip()
        smtp_cfg = self._smtp_config(settings)
        resend_error: Optional[str] = None

        # 1. Resend API
        if resend_key:
            payload: Dict[str, Any] = {
                "from": f"{from_name} <{from_addr}>",
                "to": [to_addr],
                "subject": safe_subject,
                "html": html_part,
                "text": text_part,
            }
            if extra_headers:
                payload["headers"] = dict(extra_headers)
            if reply_to_addr:
                payload["reply_to"] = reply_to_addr
            try:
                headers = {"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"}
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post("https://api.resend.com/emails", headers=headers, json=payload)
                status_code = getattr(resp, "status_code", None)
                if status_code in (200, 201):
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
                    msg_id = data.get("id") if isinstance(data, dict) else None
                    return {"success": True, "provider": "resend", "reason": "sent", "id": msg_id, "data": data}
                body = str(getattr(resp, "text", "") or "")[:500]
                resend_error = f"Resend HTTP {status_code}: {body}"
                logger.warning("[Resend Error] %s", resend_error)
            except Exception as e:
                resend_error = f"Resend exception: {type(e).__name__}: {e}"
                logger.warning("[Resend Exception] %s", resend_error)

        # 2. SMTP (primary when no Resend key, fallback when Resend failed)
        if smtp_cfg["configured"]:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = safe_subject
                msg["From"] = formataddr((from_name, from_addr))
                msg["To"] = to_addr
                msg["Date"] = formatdate(localtime=False)
                msg["Message-ID"] = make_msgid(domain=from_addr.split("@", 1)[1] if "@" in from_addr else None)
                if reply_to_addr:
                    msg["Reply-To"] = reply_to_addr
                for k, v in extra_headers.items():
                    msg[k] = v
                msg.attach(MIMEText(text_part, "plain", "utf-8"))
                msg.attach(MIMEText(html_part, "html", "utf-8"))
                await asyncio.to_thread(self._smtp_send_blocking, smtp_cfg, from_addr, to_addr, msg.as_string())
                res: Dict[str, Any] = {"success": True, "provider": "smtp", "reason": "sent"}
                if resend_error:
                    res["fallback_from"] = "resend"
                    res["resend_error"] = resend_error
                return res
            except Exception as e:
                smtp_error = f"SMTP exception: {type(e).__name__}: {e}"
                logger.warning("[SMTP Exception] %s", smtp_error)
                reason = f"{resend_error} | {smtp_error}" if resend_error else smtp_error
                return {"success": False, "provider": "smtp", "reason": reason, "error": reason}

        if resend_error:
            return {"success": False, "provider": "resend", "reason": resend_error, "error": resend_error}

        return {
            "success": False,
            "provider": "none",
            "reason": "Niciun serviciu de expediere email configurat (Resend API Key sau SMTP necesar)"
        }
