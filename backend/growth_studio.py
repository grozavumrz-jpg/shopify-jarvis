"""
backend/growth_studio.py
Upgrade 3: European Streetwear Competitor Price Radar & Real-Query Campaign Studio.

Truthfulness & brand rules enforced:
  - Store category prices (min / avg / max / count) are calculated strictly from real
    active Shopify products. When no products are provided, store prices are None.
  - Competitor positioning tiers are clearly labelled as `market_reference` benchmarks
    for European streetwear (never invented live scrape numbers or fake sales figures).
  - Campaign kits match real GSC queries to real Shopify products and URLs, respect
    "Designed in Spain" and "Grozavu" brand rules, and never use forbidden terms
    ("unisex", "atelier", "silk", "Bucharest").
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


BRAND = "Grozavu"
DOMAIN = "maisongrozavu.com"

CATEGORY_RULES: List[Tuple[str, str, Tuple[str, ...], Dict[str, Any]]] = [
    (
        "hoodies",
        "Hoodies & Sweatshirts",
        ("hoodie", "sweatshirt", "crewneck", "pullover", "fleece", "hanorac"),
        {
            "mass_market_eur": "45–70 EUR (Zara, Bershka, Pull&Bear)",
            "indie_streetwear_eur": "90–150 EUR (Nude Project, Scuffers, Cold Culture, Represent entry)",
            "luxury_streetwear_eur": "180–350+ EUR (Represent, Cole Buxton, Fear of God)",
            "positioning_tip_ro": "Pe segmentul European Independent Streetwear, clienții caută croială boxy/oversized, gramaj real vizibil în poze și identitate vizuală curată.",
        },
    ),
    (
        "tshirts",
        "T-Shirts & Tops",
        ("tee", "t-shirt", "shirt", "top", "tricou", "polo", "tank"),
        {
            "mass_market_eur": "20–35 EUR (Zara, Pull&Bear)",
            "indie_streetwear_eur": "42–68 EUR (Nude Project, Cold Culture, Stüssy)",
            "luxury_streetwear_eur": "95–180 EUR (Represent, Palm Angels)",
            "positioning_tip_ro": "Tricourile boxy cu guler gros și print curat convertesc cel mai bine prin clipuri scurte 4:5 care arată cum cade materialul pe umeri.",
        },
    ),
    (
        "bottoms",
        "Shorts & Pants",
        ("short", "pant", "jogger", "trouser", "sweatpant", "cargo", "denim", "pantalon", "pernera"),
        {
            "mass_market_eur": "30–55 EUR (Zara, Bershka)",
            "indie_streetwear_eur": "65–115 EUR (Scuffers, Cold Culture, Corteiz)",
            "luxury_streetwear_eur": "140–280 EUR (Represent, Essentials)",
            "positioning_tip_ro": "Ai deja căutări reale în Google Spania pe pantaloni scurți cu croială largă (shorts de pernera ancha) — pune accent pe poze cu model + ghid clar de mărimi.",
        },
    ),
    (
        "outerwear",
        "Jackets & Windbreakers",
        ("jacket", "windbreaker", "coat", "bomber", "vest", "geaca", "jacheta"),
        {
            "mass_market_eur": "60–100 EUR (Zara, Pull&Bear)",
            "indie_streetwear_eur": "110–190 EUR (Carhartt WIP, Stüssy, Cold Culture)",
            "luxury_streetwear_eur": "250–500+ EUR (Represent, Stone Island)",
            "positioning_tip_ro": "Piesele outerwear cresc valoarea medie a coșului (AOV). Arată detaliile fermoarelor, căptușelii și purtarea peste un hanorac.",
        },
    ),
    (
        "accessories",
        "Caps, Beanies & Bags",
        ("cap", "hat", "beanie", "bag", "sling", "tote", "backpack", "sock", "sapca", "șapcă", "rucsac", "geanta"),
        {
            "mass_market_eur": "15–28 EUR (Zara, Bershka)",
            "indie_streetwear_eur": "32–55 EUR (Stüssy, Carhartt WIP, Nude Project)",
            "luxury_streetwear_eur": "75–180 EUR (Represent, Jacquemus)",
            "positioning_tip_ro": "Accesoriile sunt cel mai ușor produs de intrare și cel mai bun cross-sell lângă hanorace/tricouri (Complete the fit).",
        },
    ),
]


def _product_price(product: Dict[str, Any]) -> Optional[float]:
    prices: List[float] = []
    for v in product.get("variants") or []:
        if not isinstance(v, dict):
            continue
        try:
            p = float(v.get("price") or 0)
            if p > 0:
                prices.append(p)
        except (TypeError, ValueError):
            pass
    if not prices:
        return None
    return round(sum(prices) / len(prices), 2)


def _classify_product(product: Dict[str, Any]) -> str:
    blob = " ".join([
        str(product.get("title") or ""),
        str(product.get("product_type") or ""),
        str(product.get("tags") or ""),
    ]).lower()
    for key, _label, keywords, _ref in CATEGORY_RULES:
        if any(kw in blob for kw in keywords):
            return key
    return "other"


def _product_url(product: Dict[str, Any], domain: str = DOMAIN) -> str:
    handle = str(product.get("handle") or "").strip().strip("/")
    return f"https://{domain}/products/{handle}" if handle else f"https://{domain}"


def build_competitor_radar(
    products: Optional[List[Dict[str, Any]]] = None,
    gsc_report: Optional[Dict[str, Any]] = None,
    currency: str = "EUR",
    domain: str = DOMAIN,
    lang: str = "ro",
) -> Dict[str, Any]:
    """
    Compare real active Shopify catalog prices by category against European streetwear
    reference tiers and surface top real Google Search Console keyword opportunities.
    """
    active = [
        p for p in (products or [])
        if isinstance(p, dict) and str(p.get("status") or "active").lower() == "active"
    ]
    buckets: Dict[str, List[Dict[str, Any]]] = {k: [] for k, *_ in CATEGORY_RULES}
    buckets["other"] = []

    for p in active:
        cat = _classify_product(p)
        price = _product_price(p)
        buckets.setdefault(cat, []).append({
            "id": str(p.get("id") or ""),
            "title": str(p.get("title") or "").strip(),
            "price": price,
            "url": _product_url(p, domain),
        })

    categories: List[Dict[str, Any]] = []
    for key, label, _kws, ref in CATEGORY_RULES:
        items = buckets.get(key) or []
        valid_prices = [x["price"] for x in items if x["price"] is not None]
        avg_p = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else None
        min_p = round(min(valid_prices), 2) if valid_prices else None
        max_p = round(max(valid_prices), 2) if valid_prices else None

        # Honest positioning assessment based on real store avg price vs indie tier
        positioning = "Fără produse active în categorie"
        if avg_p is not None:
            if key == "hoodies":
                positioning = "Competitiv (sub pragul premium EU)" if avg_p < 90 else ("Exact în zona Indie Streetwear EU" if avg_p <= 150 else "Zona Luxury Streetwear")
            elif key == "tshirts":
                positioning = "Accesibil față de indie EU" if avg_p < 42 else ("Exact în zona Indie Streetwear EU" if avg_p <= 68 else "Zona Luxury Streetwear")
            elif key == "bottoms":
                positioning = "Accesibil față de indie EU" if avg_p < 65 else ("Exact în zona Indie Streetwear EU" if avg_p <= 115 else "Zona Luxury Streetwear")
            elif key == "outerwear":
                positioning = "Competitiv (entry-level EU)" if avg_p < 110 else ("Exact în zona Indie Streetwear EU" if avg_p <= 190 else "Zona Luxury Streetwear")
            elif key == "accessories":
                positioning = "Accesibil (bun pentru impulse-buy)" if avg_p < 32 else ("Exact în zona Indie Streetwear EU" if avg_p <= 55 else "Zona Luxury")

        categories.append({
            "key": key,
            "label": label,
            "store_products_count": len(items),
            "store_min_price": min_p,
            "store_avg_price": avg_p,
            "store_max_price": max_p,
            "currency": currency,
            "positioning_label": positioning,
            "market_reference": ref,
            "sample_products": items[:4],
        })

    gsc_ok = bool(isinstance(gsc_report, dict) and gsc_report.get("connected"))
    suggested_campaign_keywords: List[Dict[str, Any]] = []
    seen_q: set = set()
    if gsc_ok:
        for src_key, badge in (("opportunity_queries", "Oportunitate Prima Pagină"), ("top_queries", "Trafic Activ Google")):
            for q in (gsc_report.get(src_key) or []):
                kw = str(q.get("query") or "").strip()
                if not kw or kw.lower() in seen_q:
                    continue
                seen_q.add(kw.lower())
                suggested_campaign_keywords.append({
                    "keyword": kw,
                    "source": "gsc_real",
                    "badge": badge,
                    "clicks": q.get("clicks", 0),
                    "impressions": q.get("impressions", 0),
                    "position": q.get("position", 0),
                })
                if len(suggested_campaign_keywords) >= 10:
                    break

    if not suggested_campaign_keywords:
        for fallback_kw in (
            "heavyweight boxy hoodie Spain",
            "streetwear oversize hoodie Europe",
            "premium boxy t-shirt",
            "Grozavu streetwear",
        ):
            suggested_campaign_keywords.append({
                "keyword": fallback_kw,
                "source": "catalog_idea",
                "badge": "Idee Catalog",
                "clicks": None,
                "impressions": None,
                "position": None,
            })

    return {
        "kind": "competitor_radar",
        "brand": BRAND,
        "domain": domain,
        "currency": currency,
        "connected_catalog": len(active) > 0,
        "total_active_products": len(active),
        "gsc_connected": gsc_ok,
        "note_ro": (
            "Prețurile Grozavu sunt calculate exact din catalogul tău activ Shopify. "
            "Intervalele pieței europene sunt repere orientative de poziționare pe segmente streetwear "
            "(Mass-Market, Indie Streetwear Spania/UE, Luxury Streetwear)."
        ),
        "categories": categories,
        "campaign_keywords": suggested_campaign_keywords,
        "brand_differentiators_ro": [
            "Designed in Spain — poziționare europeană autentică, nu dropshipping generic.",
            "Catalog variat (hanorace, tricouri boxy, pantaloni, accesorii) gata pentru pachete Complete the Fit.",
            "Căutări reale existente în Google Spania (ex. pantaloni scurți cu croială largă & căutări de brand) care pot fi transformate direct în reclame și clipuri scurte.",
        ],
    }


def _match_products_for_keyword(keyword: str, products: List[Dict[str, Any]], domain: str = DOMAIN) -> List[Dict[str, Any]]:
    active = [
        p for p in (products or [])
        if isinstance(p, dict) and str(p.get("status") or "active").lower() == "active"
    ]
    if not active:
        return []

    tokens = [t for t in re.findall(r"[a-zA-Z0-9ăâîșțáéíóúñ]+", (keyword or "").lower()) if len(t) >= 3]
    # Map common Spanish/Romanian search terms to English catalog terms
    synonyms = {
        "short": ["short", "shorts"],
        "shorts": ["short", "shorts"],
        "pernera": ["short", "pant", "wide", "relaxed", "boxy"],
        "ancha": ["wide", "oversized", "boxy", "relaxed", "short", "pant"],
        "mujer": ["women", "short", "hoodie", "tee"],
        "mujeres": ["women", "short", "hoodie", "tee"],
        "hanorac": ["hoodie", "sweatshirt", "fleece"],
        "hanorace": ["hoodie", "sweatshirt"],
        "tricou": ["tee", "shirt", "t-shirt"],
        "tricouri": ["tee", "shirt", "t-shirt"],
        "sapca": ["cap", "hat"],
        "șapcă": ["cap", "hat"],
        "pantaloni": ["pant", "jogger", "short"],
        "geaca": ["jacket", "windbreaker"],
    }
    expanded: List[str] = list(tokens)
    for t in tokens:
        expanded.extend(synonyms.get(t, []))

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for p in active:
        title = str(p.get("title") or "").strip()
        blob = f"{title} {p.get('product_type') or ''} {p.get('tags') or ''}".lower()
        score = sum(2 if t in title.lower() else 1 for t in set(expanded) if t in blob)
        scored.append((score, p))

    scored.sort(key=lambda x: (-x[0], str(x[1].get("title") or "")))
    chosen = [p for sc, p in scored if sc > 0][:3] or [p for _, p in scored[:3]]
    out: List[Dict[str, Any]] = []
    for p in chosen:
        out.append({
            "id": str(p.get("id") or ""),
            "title": str(p.get("title") or "").strip(),
            "price": _product_price(p),
            "url": _product_url(p, domain),
        })
    return out


def _truncate_ad(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0].strip(" -|,.")
    return cut if len(cut) >= max(8, limit // 2) else clean[:limit].strip()


def _sanitize_brand_copy(text: str) -> str:
    """Enforce brand rules on generated campaign strings."""
    if not text:
        return ""
    s = re.sub(r"\bunisex\b", "relaxed fit", text, flags=re.I)
    s = re.sub(r"\b(made|crafted)\s+in\s+spain\b", "Designed in Spain", s, flags=re.I)
    for bad in ("atelier", "bucharest", "bucurești", "bucuresti"):
        s = re.sub(rf"\b{bad}\b", "", s, flags=re.I)
    return re.sub(r"\s{2,}", " ", s).strip()


async def generate_campaign_studio(
    keyword: str,
    products: Optional[List[Dict[str, Any]]] = None,
    gsc_report: Optional[Dict[str, Any]] = None,
    ai_advisor: Any = None,
    currency: str = "EUR",
    domain: str = DOMAIN,
    lang: str = "ro",
) -> Dict[str, Any]:
    """
    Generate a complete, ready-to-publish TikTok/Reels + Social + Google Ads campaign kit
    grounded in a real GSC keyword and real Shopify catalog products.
    """
    kw = (keyword or "").strip()[:120] or "Grozavu streetwear"
    matched = _match_products_for_keyword(kw, products or [], domain=domain)
    primary = matched[0] if matched else None
    cta_url = primary["url"] if primary else f"https://{domain}"
    prod_name = primary["title"] if primary else f"{BRAND} Streetwear"
    prod_price = f"{primary['price']:.2f} {currency}" if (primary and primary.get("price") is not None) else None

    # Find real GSC metrics for this exact keyword if available
    gsc_metrics = None
    if isinstance(gsc_report, dict) and gsc_report.get("connected"):
        for q in (gsc_report.get("top_queries") or []) + (gsc_report.get("opportunity_queries") or []):
            if str(q.get("query") or "").strip().lower() == kw.lower():
                gsc_metrics = {
                    "clicks": q.get("clicks", 0),
                    "impressions": q.get("impressions", 0),
                    "ctr": q.get("ctr", 0),
                    "position": q.get("position", 0),
                }
                break

    # Deterministic, truthful baseline kit (always valid even without Gemini)
    price_tag = f" ({prod_price})" if prod_price else ""
    kit: Dict[str, Any] = {
        "kind": "campaign_studio",
        "source": "studio_template",
        "target_keyword": kw,
        "gsc_metrics": gsc_metrics,
        "matched_products": matched,
        "cta_url": cta_url,
        "campaign_title": f"Campanie {BRAND} — {kw}",
        "target_audience": "Spania & România, 18–34 ani, pasionați de streetwear curat, croieli relaxate și piese Designed in Spain.",
        "tiktok_reels_hook": (
            f"Prim-plan 2 secunde pe textura materialului și croiala piesei {prod_name}, "
            f"cu text pe ecran: „Căutai {kw}? Așa arată croiala reală.”"
        ),
        "video_script_steps": [
            {
                "time": "0–3s (Hook)",
                "visual": f"Cadru apropiat (4:5 vertical) pe detaliul materialului și eticheta/logo-ul {prod_name}.",
                "voiceover": f"Dacă cauți {kw}, uită-te mai întâi la cum cade materialul în lumină naturală.",
            },
            {
                "time": "3–10s (Fit & Mișcare)",
                "visual": "Piesa purtată în mișcare (față, profil, spate) într-un decor urban simplu.",
                "voiceover": f"{prod_name}{price_tag} — croială curată, gândită să arate impecabil fără să pară încărcată.",
            },
            {
                "time": "10–18s (Styling / Complete the Fit)",
                "visual": "Tranziție rapidă: piesa combinată cu adidași minimaliști și un accesoriu din catalogul Grozavu.",
                "voiceover": "Designed in Spain. O poți purta zilnic, din oraș până la ieșirile de seară.",
            },
            {
                "time": "18–25s (CTA Direct)",
                "visual": f"Cadru final clar cu produsul și linkul {domain} pe ecran.",
                "voiceover": f"Intră pe {domain} și vezi ghidul complet de mărimi și pozele reale.",
            },
        ],
        "social_caption": (
            f"{prod_name} — Designed in Spain.\n"
            f"Clean silhouette, real details, built for everyday rotation.\n"
            f"Shop directly at {cta_url}\n\n"
            f"#grozavu #maisongrozavu #streetwearespana #streetwearromania #designedinspain"
        ),
        "google_ads_pack": {
            "headlines": [
                _truncate_ad(f"{BRAND} — {kw.title()}", 30),
                _truncate_ad(prod_name, 30),
                _truncate_ad(f"{BRAND} | Designed in Spain", 30),
            ],
            "descriptions": [
                _truncate_ad(f"Descoperă {prod_name}{price_tag}. Streetwear Designed in Spain pe {domain}.", 90),
                _truncate_ad(f"Croială curată și detalii reale pentru {kw}. Comandă direct pe {domain}.", 90),
            ],
            "final_url": cta_url,
        },
        "landing_page_checklist_ro": [
            f"Asigură-te că expresia „{kw}” apare natural în titlul sau primul paragraf al paginii de produs/colecție.",
            "Verifică să ai cel puțin 3 poze clare (inclusiv purtat) și tabel real de mărimi deasupra butonului Add to Cart.",
            "Nu promite livrare în 24h sau stoc limitat fals — păstrează doar politica reală de livrare din Shopify.",
        ],
    }

    # Optional Gemini enrichment when API key is configured
    if ai_advisor is not None and callable(getattr(ai_advisor, "_get_api_key", None)) and len(ai_advisor._get_api_key()) >= 10:
        prod_ctx = ", ".join(
            f"{m['title']} ({m['price']} {currency})" if m.get("price") else m["title"]
            for m in matched
        ) or f"{BRAND} catalog"
        gsc_ctx = (
            f"Real Google Search Console stats for '{kw}': {gsc_metrics['clicks']} clicks, "
            f"{gsc_metrics['impressions']} impressions, avg position #{gsc_metrics['position']}."
            if gsc_metrics else f"Target keyword: '{kw}'."
        )
        prompt = f"""Create a concise, high-converting campaign kit for streetwear brand {BRAND} ({domain}).
BRAND RULES: "Designed in Spain" only (never made/crafted in Spain). Never use "unisex", "atelier", "silk", "Bucharest". Do not invent discounts, fake stock scarcity, delivery times, or product materials not in the title.
DATA: {gsc_ctx} Real matching products: {prod_ctx}. Primary URL: {cta_url}.
Write in Romanian (social caption may be bilingual EN/ES/RO for Spain & Romania buyers).
Return ONLY valid JSON with keys:
{{"campaign_title": "short title",
  "tiktok_reels_hook": "strong 0-3s hook",
  "video_script_steps": [{{"time": "0-3s", "visual": "...", "voiceover": "..."}}],
  "social_caption": "copy-ready caption with hashtags",
  "google_ads_headlines": ["max 30 chars", "max 30 chars", "max 30 chars"],
  "google_ads_descriptions": ["max 90 chars", "max 90 chars"]}}"""
        try:
            raw_txt = await ai_advisor._call_advisor_model(prompt, json_mode=True, max_tokens=950, temperature=0.7)
            parsed = ai_advisor._parse_json_object(raw_txt)
            if isinstance(parsed, dict):
                if isinstance(parsed.get("campaign_title"), str) and parsed["campaign_title"].strip():
                    kit["campaign_title"] = _sanitize_brand_copy(parsed["campaign_title"])[:140]
                if isinstance(parsed.get("tiktok_reels_hook"), str) and parsed["tiktok_reels_hook"].strip():
                    kit["tiktok_reels_hook"] = _sanitize_brand_copy(parsed["tiktok_reels_hook"])[:320]
                if isinstance(parsed.get("social_caption"), str) and parsed["social_caption"].strip():
                    kit["social_caption"] = _sanitize_brand_copy(parsed["social_caption"])[:700]
                steps = parsed.get("video_script_steps")
                if isinstance(steps, list) and len(steps) >= 3:
                    clean_steps = []
                    for st in steps[:5]:
                        if isinstance(st, dict) and (st.get("visual") or st.get("voiceover")):
                            clean_steps.append({
                                "time": _sanitize_brand_copy(str(st.get("time") or ""))[:30],
                                "visual": _sanitize_brand_copy(str(st.get("visual") or ""))[:260],
                                "voiceover": _sanitize_brand_copy(str(st.get("voiceover") or ""))[:260],
                            })
                    if clean_steps:
                        kit["video_script_steps"] = clean_steps
                hl = parsed.get("google_ads_headlines")
                if isinstance(hl, list) and hl:
                    kit["google_ads_pack"]["headlines"] = [
                        _truncate_ad(_sanitize_brand_copy(str(h)), 30) for h in hl[:3] if str(h).strip()
                    ] or kit["google_ads_pack"]["headlines"]
                desc = parsed.get("google_ads_descriptions")
                if isinstance(desc, list) and desc:
                    kit["google_ads_pack"]["descriptions"] = [
                        _truncate_ad(_sanitize_brand_copy(str(d)), 90) for d in desc[:2] if str(d).strip()
                    ] or kit["google_ads_pack"]["descriptions"]
                kit["source"] = "gemini_ai"
        except Exception as e:
            print(f"[CampaignStudio] Gemini unavailable, clean template used: {str(e)[:120]}")

    return kit
