"""
backend/visibility_engine.py
SEO + AEO + GEO visibility toolkit for Grozavu (maisongrozavu.com).

  SEO  - rank on Google            -> scored from real Google Search Console data.
  AEO  - be in the answer box      -> answer-first FAQ / "best X for Y" packs (preview only,
                                      nothing is written to Shopify) + readiness score from
                                      the real catalog descriptions.
  GEO  - be recommended by AI      -> live test: Gemini (with Google Search grounding) is asked
                                      real buyer questions; we check whether Grozavu is named.
                                      Plus a mentions plan (Reddit / blogs / reviews) with drafts.

Truthfulness rules:
  * Scores are heuristics computed ONLY from real data; a score is None when its data source
    is missing (never a made-up number).
  * The GEO test measures Gemini, not ChatGPT - labelled as an indicator.
  * Generated copy follows brand rules: "Designed in Spain", no "unisex"/"atelier"/"silk"/
    "Bucharest", no invented materials, shipping, returns or discounts.
"""

import asyncio
import html
import json
import re
import time
from typing import Any, Dict, List, Optional

from growth_studio import (
    BRAND, DOMAIN, _sanitize_brand_copy, _match_products_for_keyword, _product_price, _product_url,
    _classify_product, CATEGORY_RULES,
)

BRAND_RE = re.compile(r"grozavu", re.I)
_GEO_CACHE: Dict[str, Dict[str, Any]] = {}
GEO_CACHE_TTL = 6 * 3600


# ── helpers ──────────────────────────────────────────────────────────────────

def _plain(text: Any) -> str:
    s = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _gsc_queries(gsc_report: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(gsc_report, dict) or not gsc_report.get("connected"):
        return []
    seen, out = set(), []
    for q in (gsc_report.get("opportunity_queries") or []) + (gsc_report.get("top_queries") or []):
        text = str(q.get("query") or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(q)
    return out


# ── Scores ───────────────────────────────────────────────────────────────────

def seo_score(gsc_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(gsc_report, dict) or not gsc_report.get("connected"):
        return {"score": None, "reason": "Search Console neconectat", "details": {}}
    totals = gsc_report.get("totals") or gsc_report.get("summary") or gsc_report
    try:
        clicks = float(totals.get("clicks") or 0)
        impressions = float(totals.get("impressions") or 0)
        position = float(totals.get("position") or totals.get("avg_position") or 0)
    except (TypeError, ValueError):
        return {"score": None, "reason": "Date GSC indisponibile", "details": {}}
    if impressions <= 0 or position <= 0:
        return {"score": None, "reason": "Fără afișări în GSC", "details": {}}
    ctr = clicks / impressions
    pos_score = _clamp(100 - (position - 1) * 5)       # #1 -> 100, #21 -> 0
    ctr_score = _clamp(ctr / 0.05 * 100)                # 5% CTR -> 100
    score = round(0.6 * pos_score + 0.4 * ctr_score)
    return {
        "score": score,
        "details": {
            "clicks": int(clicks), "impressions": int(impressions),
            "avg_position": round(position, 1), "ctr_pct": round(ctr * 100, 2),
        },
        "formula": "60% poziție medie (#1=100, #21=0) + 40% CTR (5%=100)",
    }


def aeo_readiness(products: Optional[List[Dict[str, Any]]], gsc_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    active = [p for p in (products or []) if isinstance(p, dict)
              and str(p.get("status") or "active").lower() == "active"]
    if not active:
        return {"score": None, "reason": "Catalog Shopify indisponibil", "details": {}, "weak_products": []}
    with_desc, with_faq, weak = 0, 0, []
    for p in active:
        body = _plain(p.get("body_html"))
        has_desc = len(body) >= 120
        has_faq = bool(re.search(r"\bfaq\b|întrebări|preguntas|\?", body, re.I)) and has_desc
        with_desc += has_desc
        with_faq += has_faq
        if not has_desc:
            weak.append({"title": str(p.get("title") or "").strip(), "url": _product_url(p),
                         "chars": len(body)})
    n = len(active)
    desc_share, faq_share = with_desc / n, with_faq / n
    score = round(100 * (0.6 * desc_share + 0.4 * faq_share))
    return {
        "score": score,
        "details": {
            "active_products": n,
            "products_with_real_description": with_desc,
            "products_with_faq_or_questions": with_faq,
            "gsc_queries_available": len(_gsc_queries(gsc_report)),
        },
        "formula": "60% produse cu descriere ≥120 caractere + 40% produse cu secțiune de întrebări/FAQ",
        "weak_products": weak[:10],
    }


def geo_score(shop: str) -> Dict[str, Any]:
    cached = _GEO_CACHE.get(shop)
    if not cached:
        return {"score": None, "reason": "Testul GEO nu a fost rulat încă", "details": {}}
    return {
        "score": cached["mention_rate_pct"],
        "details": {
            "prompts_tested": cached["prompts_tested"],
            "brand_mentioned_in": cached["brand_mentioned_count"],
            "tested_at": cached["tested_at_iso"],
            "engine": cached["engine"],
        },
        "formula": "% din întrebările de cumpărător în care AI-ul a menționat Grozavu",
    }


def build_visibility_score(shop: str, products, gsc_report) -> Dict[str, Any]:
    seo = seo_score(gsc_report)
    aeo = aeo_readiness(products, gsc_report)
    geo = geo_score(shop)
    scores = [x["score"] for x in (seo, aeo, geo) if x.get("score") is not None]
    overall = round(sum(scores) / len(scores)) if scores else None

    actions: List[str] = []
    if seo.get("score") is not None and seo["details"]["ctr_pct"] < 3:
        actions.append(f"CTR de {seo['details']['ctr_pct']}% în Google: rescrie titlurile/meta pe query-urile din top 20 (preview, aplici tu).")
    if aeo.get("score") is not None and aeo["details"]["products_with_real_description"] < aeo["details"]["active_products"]:
        miss = aeo["details"]["active_products"] - aeo["details"]["products_with_real_description"]
        actions.append(f"{miss} produse au descriere sub 120 caractere: AI-urile nu au ce cita. Folosește Studio AEO.")
    if aeo.get("score") is not None and aeo["details"]["products_with_faq_or_questions"] == 0:
        actions.append("Niciun produs nu are FAQ: generează pachetul AEO și adaugă-l manual în Shopify.")
    if geo.get("score") is None:
        actions.append("Rulează testul GEO ca să vezi dacă AI-ul recomandă Grozavu.")
    elif geo["score"] < 30:
        actions.append("Grozavu e rar recomandat de AI: urmează planul de mențiuni (Reddit, bloguri, recenzii).")
    return {
        "overall": overall, "seo": seo, "aeo": aeo, "geo": geo,
        "next_actions": actions,
        "note": "Scoruri euristice calculate doar din date reale; None = sursă de date lipsă.",
    }


# ── AEO pack ─────────────────────────────────────────────────────────────────

def _faq_jsonld(faq: List[Dict[str, str]]) -> str:
    data = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["question"],
             "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
            for f in faq
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


async def generate_aeo_pack(keyword: str, products, gsc_report, ai_advisor: Any = None,
                            currency: str = "EUR", lang: str = "ro") -> Dict[str, Any]:
    kw = (keyword or "").strip()[:120] or "streetwear Grozavu"
    matched = _match_products_for_keyword(kw, products or [])
    primary = matched[0] if matched else None
    prod = primary["title"] if primary else f"{BRAND} streetwear"
    price = f"{primary['price']:.2f} {currency}" if primary and primary.get("price") else None
    url = primary["url"] if primary else f"https://{DOMAIN}"
    price_txt = f" la {price}" if price else ""

    answer_first = (
        f"{prod}{price_txt} este varianta {BRAND} pentru „{kw}”: croială relaxată, "
        f"design Designed in Spain, disponibilă direct pe {DOMAIN}."
    )
    faq = [
        {"question": f"Ce este {prod}?",
         "answer": f"{prod} este o piesă streetwear {BRAND}, Designed in Spain, disponibilă pe {DOMAIN}."},
        {"question": f"Unde pot cumpăra {kw}?",
         "answer": f"Poți comanda direct de pe {url}."},
        {"question": f"Cât costă {prod}?",
         "answer": (f"Prețul actual este {price}." if price
                    else "Prețul actual este afișat pe pagina produsului.")},
        {"question": "Cum aleg mărimea?",
         "answer": "[Completează cu recomandarea ta reală din tabelul de mărimi Shopify.]"},
        {"question": "Care sunt condițiile de livrare și retur?",
         "answer": "[Completează cu politica reală de livrare și retur din Shopify.]"},
    ]
    pack: Dict[str, Any] = {
        "kind": "aeo_pack", "source": "template", "target_keyword": kw,
        "matched_products": matched, "target_url": url,
        "answer_first_paragraph": answer_first,
        "faq": faq,
        "article_outline": [
            f"Titlu: Cele mai bune {kw} în 2026: ghid {BRAND}",
            f"Intro (răspuns direct în 2 propoziții): {answer_first}",
            "Secțiune 1: Cum alegi croiala și mărimea (cu tabel real)",
            "Secțiune 2: Cum le porți (3 outfituri din catalog)",
            "Secțiune 3: Întrebări frecvente (FAQ de mai sus)",
            f"CTA: link către {url}",
        ],
        "implementation_ro": [
            "Aceasta este doar o previzualizare: nu s-a scris nimic în Shopify.",
            "Adaugă paragraful-răspuns la începutul paginii/colecției, iar FAQ-ul la final.",
            "Completează manual răspunsurile marcate cu [ ] cu informații reale.",
            "Adaugă JSON-LD-ul în tema Shopify (sau într-o pagină de blog) doar după ce ai completat răspunsurile.",
        ],
    }

    if ai_advisor is not None and len(getattr(ai_advisor, "_get_api_key", lambda: "")()) >= 10:
        ctx = ", ".join(f"{m['title']} ({m['price']} {currency})" if m.get("price") else m["title"] for m in matched) or BRAND
        prompt = f"""Write an answer-engine-optimized content pack for streetwear brand {BRAND} ({DOMAIN}), target query: "{kw}".
Matching real products: {ctx}. URL: {url}.
RULES: "Designed in Spain" only. Never use "unisex", "atelier", "silk", "Bucharest". Do NOT invent materials, sizes, shipping times, return policy, discounts, reviews or stock. If a fact is unknown write exactly "[Completează cu informația reală]".
Language: Romanian for the pack (the answer_first_paragraph also in Spanish as answer_first_es).
Return ONLY JSON: {{"answer_first_paragraph":"2 sentences answering the query directly and naming {BRAND}",
"answer_first_es":"same in Spanish","faq":[{{"question":"...","answer":"..."}}] (5-6 items),
"article_outline":["..."] (6-8 lines)}}"""
        try:
            raw = await ai_advisor._call_advisor_model(prompt, json_mode=True, max_tokens=1100, temperature=0.6)
            parsed = ai_advisor._parse_json_object(raw)
            if isinstance(parsed, dict):
                afp = parsed.get("answer_first_paragraph")
                if isinstance(afp, str) and afp.strip():
                    pack["answer_first_paragraph"] = _sanitize_brand_copy(afp)[:400]
                es = parsed.get("answer_first_es")
                if isinstance(es, str) and es.strip():
                    pack["answer_first_es"] = _sanitize_brand_copy(es)[:400]
                items = []
                for f in (parsed.get("faq") or [])[:6]:
                    if isinstance(f, dict) and f.get("question") and f.get("answer"):
                        items.append({"question": _sanitize_brand_copy(str(f["question"]))[:160],
                                      "answer": _sanitize_brand_copy(str(f["answer"]))[:420]})
                if len(items) >= 3:
                    pack["faq"] = items
                outline = [_sanitize_brand_copy(str(x))[:200] for x in (parsed.get("article_outline") or [])[:8] if str(x).strip()]
                if len(outline) >= 4:
                    pack["article_outline"] = outline
                pack["source"] = "gemini_ai"
        except Exception as e:  # noqa: BLE001 - template stays valid
            print(f"[AEO] Gemini unavailable, template used: {str(e)[:120]}")

    pack["faq_jsonld"] = _faq_jsonld(pack["faq"])
    pack["has_placeholders"] = any("[" in f["answer"] for f in pack["faq"])
    return pack


# ── GEO test ─────────────────────────────────────────────────────────────────

def build_geo_prompts(products, gsc_report) -> List[str]:
    prompts: List[str] = []
    queries = [str(q.get("query")) for q in _gsc_queries(gsc_report)]
    for q in queries:
        if re.search(r"pernera|short|hoodie|sudadera|streetwear|pantal", q, re.I) and "grozavu" not in q.lower():
            prompts.append(f"Recomiéndame marcas o tiendas online para: {q}")
            break
    cats = {_classify_product(p) for p in (products or []) if isinstance(p, dict)}
    labels = {k: lbl for k, lbl, _kw, _ref in CATEGORY_RULES}
    if "bottoms" in cats:
        prompts.append("What are the best premium streetwear shorts and wide-leg pants brands in Europe right now?")
    if "hoodies" in cats:
        prompts.append("What is a good heavyweight oversized hoodie brand from Spain or Europe, mid-premium price?")
    prompts.append("¿Qué marcas de streetwear premium diseñadas en España recomiendas descubrir?")
    prompts.append(f"Is {BRAND} ({DOMAIN}) a good streetwear brand? What do you know about it?")
    del labels
    seen, out = set(), []
    for p in prompts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:5]


async def run_geo_test(shop: str, ai_advisor: Any, products, gsc_report,
                       force: bool = False) -> Dict[str, Any]:
    cached = _GEO_CACHE.get(shop)
    if cached and not force and time.time() - cached["tested_at"] < GEO_CACHE_TTL:
        return {**cached, "from_cache": True}
    if ai_advisor is None or len(getattr(ai_advisor, "_get_api_key", lambda: "")()) < 10:
        return {"ok": False, "error": "gemini_not_configured",
                "message": "GEMINI_API_KEY lipsește: testul GEO nu poate rula."}

    prompts = build_geo_prompts(products, gsc_report)
    sem = asyncio.Semaphore(2)

    async def one(p: str) -> Dict[str, Any]:
        wrapped = (
            f"{p}\n\nAnswer like a shopping assistant in the language of the question. "
            "Recommend up to 5 specific brands or online shops, with one short reason each. "
            "On the very last line write exactly: BRANDS: brand1, brand2, brand3"
        )
        g: Dict[str, Any] = {}
        async with sem:
            try:
                text = await ai_advisor._call_gemini(wrapped, max_tokens=900, temperature=0.3,
                                                     use_web_search=True, grounding_out=g)
            except Exception as e:  # noqa: BLE001
                return {"prompt": p, "error": str(e)[:140], "mentioned": False}
        brands = []
        m = re.search(r"BRANDS:\s*(.+)$", text.strip(), re.I | re.M)
        if m:
            brands = [b.strip(" .*") for b in m.group(1).split(",") if b.strip(" .*")][:8]
        body = re.sub(r"BRANDS:.*$", "", text, flags=re.I | re.M).strip()
        mentioned = bool(BRAND_RE.search(text)) or any(BRAND_RE.search(s.get("url", "")) for s in g.get("sources", []))
        return {
            "prompt": p, "mentioned": mentioned, "brands_recommended": brands,
            "answer_excerpt": body[:420], "sources": (g.get("sources") or [])[:4],
        }

    results = await asyncio.gather(*(one(p) for p in prompts))
    ok = [r for r in results if "error" not in r]
    if not ok:
        return {"ok": False, "error": "gemini_failed",
                "message": "Gemini nu a răspuns: " + (results[0].get("error") if results else "?")}
    hits = sum(1 for r in ok if r["mentioned"])
    competitors: Dict[str, int] = {}
    for r in ok:
        for b in r.get("brands_recommended", []):
            if not BRAND_RE.search(b):
                competitors[b] = competitors.get(b, 0) + 1
    top_comp = sorted(competitors.items(), key=lambda kv: -kv[1])[:8]
    now = time.time()
    out = {
        "ok": True, "engine": "Gemini + Google Search (indicator; nu măsoară ChatGPT)",
        "prompts_tested": len(ok), "brand_mentioned_count": hits,
        "mention_rate_pct": round(100 * hits / len(ok)),
        "results": results,
        "competitors_recommended_instead": [{"brand": b, "times": n} for b, n in top_comp],
        "tested_at": now, "tested_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "from_cache": False,
    }
    _GEO_CACHE[shop] = out
    return out


# ── GEO mentions plan ────────────────────────────────────────────────────────

def build_mentions_plan(products, gsc_report) -> Dict[str, Any]:
    cats = {}
    for p in products or []:
        if isinstance(p, dict):
            cats.setdefault(_classify_product(p), p)
    sample = next(iter(cats.values()), None)
    sample_title = str(sample.get("title") or BRAND).strip() if sample else BRAND
    top_q = next((str(q.get("query")) for q in _gsc_queries(gsc_report) if "grozavu" not in str(q.get("query")).lower()),
                 "shorts de pernera ancha")
    return {
        "principle": "AI-urile recomandă ce au văzut recomandat în surse independente. Postezi tu, cu identitatea reală; Jarvis doar pregătește materialele.",
        "do_not": [
            "Nu posta recenzii false sau conturi multiple.",
            "Nu face spam în subreddit-uri; respectă regulile fiecărei comunități.",
            "Spune mereu că ești fondatorul brandului când recomanzi Grozavu.",
        ],
        "channels": [
            {
                "channel": "Reddit (r/streetwear, r/malefashionadvice, r/SpainFA, r/rumania)",
                "action": f"Participă la discuții pe tema „{top_q}” și răspunde util; menționează brandul doar când e relevant.",
                "draft": (f"Sunt fondatorul Grozavu, brand de streetwear Designed in Spain. Pentru „{top_q}” "
                          f"eu aș alege croieli relaxate cu poze reale purtate; noi avem {sample_title} pe {DOMAIN}, "
                          "dar spune-mi bugetul și îți dau și alternative."),
            },
            {
                "channel": "Bloguri / publicații de modă (Spania & România)",
                "action": "Trimite 5–10 e-mailuri personalizate către bloggeri de streetwear, oferind un produs pentru review sincer.",
                "draft": (f"Salut, sunt fondatorul Grozavu ({DOMAIN}), brand streetwear Designed in Spain. "
                          f"Ți-aș trimite {sample_title} ca să-ți formezi o părere sinceră; fără obligația de a scrie pozitiv."),
            },
            {
                "channel": "Recenzii clienți (Google, Trustpilot, pagină produs)",
                "action": "După livrare, cere recenzii reale clienților (doar celor care au consimțământ de marketing).",
                "draft": "Mulțumim pentru comandă! Ne ajută mult o părere sinceră despre croială și calitate, în 1 minut: [link recenzie].",
            },
            {
                "channel": "Pagina „Despre Grozavu” (pe site)",
                "action": "O pagină clară pe care AI-ul o poate cita: cine sunteți, ce produceți, unde sunteți bazați.",
                "draft": (f"{BRAND} este un brand de streetwear Designed in Spain, disponibil pe {DOMAIN}. "
                          "[Completează: anul fondării, filosofia, ce îl diferențiază.]"),
            },
            {
                "channel": "Instagram / TikTok / YouTube (descrieri și subtitrări)",
                "action": f"Folosește expresiile reale din GSC („{top_q}”) în descrieri și subtitrări; AI-urile indexează transcripturile.",
                "draft": f"{sample_title} · {BRAND} · Designed in Spain · {DOMAIN}",
            },
        ],
    }
