"""
backend/agent_tools.py
What Jarvis' agent may READ and CHANGE in the owner's Shopify store — and nothing else.

Safety rules (the whole point of this module):
  * The AI model never changes the store by itself. A write tool only creates a PROPOSAL
    with a before/after preview. It runs only after the owner presses "Aprobă" in the panel.
  * Right before running, Jarvis re-reads Shopify. If the product/discount/collection changed
    since the preview, the proposal is refused as "stale" (nothing is overwritten blindly).
  * After running, Jarvis reads Shopify again and checks that the change really happened.
  * Every executed change keeps the "before" values, so it can be undone with one click.
  * Allowed: product text/SEO/tags/category metafields, variant prices, new discount codes,
    adding/removing products in MANUAL collections, product status (active/draft) and
    publishing to the Online Store. Never: deleting anything, refunds, payments, emails to
    customers, themes, archiving.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - tzdata missing
    MADRID = timezone.utc

# Category metafields Jarvis fills (the owner wants them ALWAYS filled on every product).
CATEGORY_FIELDS: Dict[str, Dict[str, str]] = {
    "colors": {"key": "color-pattern", "type": "shopify--color-pattern", "label": "Color"},
    "fabrics": {"key": "fabric", "type": "shopify--fabric", "label": "Fabric"},
    "target_gender": {"key": "target-gender", "type": "shopify--target-gender", "label": "Target gender"},
    "age_group": {"key": "age-group", "type": "shopify--age-group", "label": "Age group"},
}
AEO_START = "<!-- grozavu-aeo-start -->"
AEO_END = "<!-- grozavu-aeo-end -->"
_NON_ENGLISH_RE = re.compile(r"[ăâîșțşţáéíóúñüàèòç¿¡]", re.I)
_DISCOUNT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,29}$")
PROPOSAL_TTL = timedelta(hours=24)
MAX_PRODUCTS_PER_COLLECTION_CHANGE = 25


class AgentError(Exception):
    """A clear, owner-facing reason why a read/proposal/execution could not be done."""


# ── small helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gid(kind: str, value: Any) -> str:
    v = str(value or "").strip()
    if v.startswith("gid://shopify/"):
        return v
    if v.isdigit():
        return f"gid://shopify/{kind}/{v}"
    return ""


def _legacy(gid: str) -> str:
    return str(gid or "").rsplit("/", 1)[-1]


def _money(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    try:
        d = round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        raise AgentError(f"Preț invalid: {v!r}")
    return f"{d:.2f}"


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    return re.sub(r"\s+", " ", text).strip()


def _short(v: Any, n: int = 160) -> str:
    s = _strip_html(v) if isinstance(v, str) and "<" in v else str(v if v is not None else "—")
    if s in ("", "None", "[]"):
        s = "—"
    return s if len(s) <= n else s[: n - 1] + "…"


def _aeo_block(html: str) -> str:
    html = str(html or "")
    i, j = html.find(AEO_START), html.find(AEO_END)
    if i == -1 or j == -1 or j < i:
        return ""
    return html[i: j + len(AEO_END)]


def _as_html(text: str) -> str:
    """Plain text from the model becomes simple paragraphs; HTML is kept as it is."""
    t = str(text or "").strip()
    if "<" in t and ">" in t:
        return t
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paras)


def _parse_when(value: Any, end_of_day: bool = False) -> Optional[datetime]:
    """'2026-12-01' (Madrid day) or a full ISO time → UTC datetime."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            d = datetime.strptime(s, "%Y-%m-%d")
            local = d.replace(hour=23, minute=59, second=59) if end_of_day else d
            return local.replace(tzinfo=MADRID).astimezone(timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MADRID)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise AgentError(f"Dată invalidă: {s!r} (folosește AAAA-LL-ZZ)")


def _user_errors(payload: Dict[str, Any], what: str) -> None:
    errs = [e for e in (payload or {}).get("userErrors") or [] if isinstance(e, dict)]
    if errs:
        raise AgentError(f"Shopify a refuzat {what}: " + "; ".join(str(e.get("message")) for e in errs)[:400])


# ── the toolbox ──────────────────────────────────────────────────────────────

class AgentToolbox:
    """Reads and (after approval) writes through the store's ShopifyClient (GraphQL)."""

    WRITE_ACTIONS = ("update_product", "change_prices", "create_discount", "change_collection", "set_product_status")

    def __init__(self, client: Any, ai: Any = None, shop: str = "", scopes: Optional[List[str]] = None):
        self.client = client
        self.ai = ai
        self.shop = shop or getattr(client, "shop", "")
        self.scopes = list(scopes) if scopes else None  # None = unknown (then Shopify decides)
        self._metaobjects: Dict[str, List[Dict[str, str]]] = {}
        self._online_store_pub: Optional[str] = None

    # ── GraphQL core ──────────────────────────────────────────────────────────

    async def _gql(self, query: str, variables: Optional[dict] = None) -> Dict[str, Any]:
        try:
            res = await self.client._graphql(query, variables or {})
        except Exception as e:  # network / HTTP status
            raise AgentError(f"Shopify nu a răspuns ({type(e).__name__}: {str(e)[:160]})")
        if not isinstance(res, dict):
            raise AgentError("Shopify a trimis un răspuns gol")
        if res.get("errors"):
            errs = res["errors"] if isinstance(res["errors"], list) else [res["errors"]]
            msg = "; ".join(str(e.get("message") if isinstance(e, dict) else e) for e in errs)
            if "access denied" in msg.lower() or "access_denied" in msg.lower():
                raise AgentError("Aplicația Jarvis nu are permisiune pentru asta în Shopify: " + msg[:200])
            raise AgentError("Eroare Shopify: " + msg[:300])
        return res.get("data") or {}

    async def online_store_publication(self) -> Optional[str]:
        if self._online_store_pub:
            return self._online_store_pub
        data = await self._gql("""query { publications(first: 30) { nodes { id channels(first: 3) { nodes { handle name } } } } }""")
        for pub in ((data.get("publications") or {}).get("nodes") or []):
            for ch in ((pub.get("channels") or {}).get("nodes") or []):
                if str(ch.get("handle") or "") == "online_store" or str(ch.get("name") or "") == "Online Store":
                    self._online_store_pub = pub.get("id")
                    return self._online_store_pub
        return None

    async def metaobject_values(self, mo_type: str) -> List[Dict[str, str]]:
        if mo_type in self._metaobjects:
            return self._metaobjects[mo_type]
        data = await self._gql("""query M($t: String!) { metaobjects(type: $t, first: 250) { nodes { id handle displayName } } }""",
                               {"t": mo_type})
        vals = [{"id": n["id"], "handle": str(n.get("handle") or ""), "label": str(n.get("displayName") or "")}
                for n in ((data.get("metaobjects") or {}).get("nodes") or []) if n.get("id")]
        self._metaobjects[mo_type] = vals
        return vals

    def can(self, scope: str) -> bool:
        return self.scopes is None or scope in self.scopes

    async def _labels_to_ids(self, field: str, labels: List[str]) -> List[Dict[str, str]]:
        spec = CATEGORY_FIELDS[field]
        values = await self.metaobject_values(spec["type"])
        out: List[Dict[str, str]] = []
        for raw in labels:
            want = str(raw or "").strip().lower()
            if not want:
                continue
            match = None
            for v in values:  # exact label first, then handle; the first match wins (duplicates exist)
                if v["label"].lower() == want:
                    match = v
                    break
            if match is None:
                for v in values:
                    if v["handle"].lower() == want.replace(" ", "-"):
                        match = v
                        break
            if match is None:
                avail = sorted({v["label"] for v in values})
                raise AgentError(f"Valoarea „{raw}” nu există pentru {spec['label']} în magazin. "
                                 f"Valori posibile: {', '.join(avail[:60])}")
            if match["id"] not in [o["id"] for o in out]:
                out.append(match)
        return out

    # ── READ tools ────────────────────────────────────────────────────────────

    async def resolve_product_id(self, product: Any) -> str:
        gid = _gid("Product", product)
        if gid:
            return gid
        handle = str(product or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,200}", handle):
            raise AgentError(f"Nu știu ce produs este „{product}”. Caută-l întâi cu search_products și folosește id-ul.")
        data = await self._gql("""query H($q: String!) { products(first: 1, query: $q) { nodes { id } } }""",
                               {"q": f"handle:'{handle}'"})
        nodes = (data.get("products") or {}).get("nodes") or []
        if not nodes:
            raise AgentError(f"Nu există niciun produs cu handle-ul „{handle}”.")
        return nodes[0]["id"]

    async def search_products(self, query: str = "", limit: int = 10) -> Dict[str, Any]:
        limit = max(1, min(25, int(limit or 10)))
        data = await self._gql("""
            query S($q: String, $n: Int!) { products(first: $n, query: $q, sortKey: RELEVANCE) { nodes {
              id title handle status productType totalInventory
              priceRangeV2 { minVariantPrice { amount currencyCode } maxVariantPrice { amount } } } } }""",
                               {"q": str(query or "").strip() or None, "n": limit})
        items = []
        for p in (data.get("products") or {}).get("nodes") or []:
            pr = p.get("priceRangeV2") or {}
            items.append({
                "id": p.get("id"), "title": p.get("title"), "handle": p.get("handle"), "status": p.get("status"),
                "type": p.get("productType"), "inventory": p.get("totalInventory"),
                "price_min": ((pr.get("minVariantPrice") or {}).get("amount")),
                "price_max": ((pr.get("maxVariantPrice") or {}).get("amount")),
                "currency": ((pr.get("minVariantPrice") or {}).get("currencyCode")),
            })
        return {"count": len(items), "products": items}

    async def _product_raw(self, product_id: str, variants: int = 100) -> Dict[str, Any]:
        pub = await self.online_store_publication()
        pub_field = "publishedOnPublication(publicationId: $pub)" if pub else ""
        pub_var = ", $pub: ID!" if pub else ""
        variables: Dict[str, Any] = {"id": product_id, "nv": variants}
        if pub:
            variables["pub"] = pub
        data = await self._gql("""
            query P($id: ID!, $nv: Int!""" + pub_var + """) { product(id: $id) {
              id legacyResourceId title handle status productType vendor tags descriptionHtml
              seo { title description } category { fullName } onlineStoreUrl
              """ + pub_field + """ mediaCount { count } totalInventory
              variants(first: $nv) { nodes { id title sku price compareAtPrice inventoryQuantity } }
              collections(first: 30) { nodes { id title } }
              metafields(first: 4, keys: ["shopify.color-pattern", "shopify.fabric", "shopify.target-gender", "shopify.age-group"]) {
                nodes { key value references(first: 10) { nodes { ... on Metaobject { id displayName } } } } }
            } }""", variables)
        p = data.get("product")
        if not p:
            raise AgentError(f"Produsul {product_id} nu există (sau a fost șters).")
        cats: Dict[str, List[Dict[str, str]]] = {k: [] for k in CATEGORY_FIELDS}
        for mf in ((p.get("metafields") or {}).get("nodes") or []):
            key = str(mf.get("key") or "").split(".")[-1]
            for field, spec in CATEGORY_FIELDS.items():
                if spec["key"] == key:
                    cats[field] = [{"id": r.get("id"), "label": r.get("displayName")}
                                   for r in ((mf.get("references") or {}).get("nodes") or []) if r.get("id")]
        p["_category"] = cats
        p["_published"] = bool(p.get("publishedOnPublication")) if pub else bool(p.get("onlineStoreUrl"))
        return p

    async def get_product(self, product: Any) -> Dict[str, Any]:
        pid = await self.resolve_product_id(product)
        p = await self._product_raw(pid)
        desc = str(p.get("descriptionHtml") or "")
        aeo = _aeo_block(desc)
        return {
            "id": p["id"], "title": p.get("title"), "handle": p.get("handle"), "status": p.get("status"),
            "product_type": p.get("productType"), "vendor": p.get("vendor"), "tags": p.get("tags") or [],
            "description_html": desc.replace(aeo, "").strip()[:4000],
            "has_faq_block": bool(aeo),
            "seo_title": (p.get("seo") or {}).get("title"), "seo_description": (p.get("seo") or {}).get("description"),
            "category": (p.get("category") or {}).get("fullName"),
            "published_online_store": p["_published"], "url": p.get("onlineStoreUrl"),
            "images": (p.get("mediaCount") or {}).get("count"), "total_inventory": p.get("totalInventory"),
            "variants": [{"id": v["id"], "title": v.get("title"), "sku": v.get("sku"), "price": v.get("price"),
                          "compare_at_price": v.get("compareAtPrice"), "inventory": v.get("inventoryQuantity")}
                         for v in ((p.get("variants") or {}).get("nodes") or [])],
            "collections": [{"id": c["id"], "title": c.get("title")} for c in ((p.get("collections") or {}).get("nodes") or [])],
            "category_metafields": {f: [x["label"] for x in v] for f, v in p["_category"].items()},
        }

    async def list_collections(self, query: str = "") -> Dict[str, Any]:
        qv = {"q": str(query or "").strip() or None}
        try:
            data = await self._gql("""
                query C($q: String) { collections(first: 60, query: $q) { nodes { id title handle productsCount { count } ruleSet { appliedDisjunctively } } } }""", qv)
        except AgentError:  # newer API versions renamed ruleSet: list without the manual/automatic flag
            data = await self._gql("""
                query C($q: String) { collections(first: 60, query: $q) { nodes { id title handle productsCount { count } } } }""", qv)
        out = [{"id": c["id"], "title": c.get("title"), "handle": c.get("handle"),
                "products": (c.get("productsCount") or {}).get("count"),
                "type": ("automatic (rules)" if c.get("ruleSet") else "manual") if "ruleSet" in c else "unknown"}
               for c in (data.get("collections") or {}).get("nodes") or []]
        return {"count": len(out), "collections": out}

    async def list_discounts(self) -> Dict[str, Any]:
        data = await self._gql("""
            query { discountNodes(first: 30, sortKey: CREATED_AT, reverse: true) { nodes { id discount {
              __typename ... on DiscountCodeBasic { title status startsAt endsAt usageLimit appliesOncePerCustomer asyncUsageCount
                codes(first: 2) { nodes { code } }
                customerGets { value { __typename ... on DiscountPercentage { percentage } ... on DiscountAmount { amount { amount currencyCode } } } } }
              ... on DiscountAutomaticBasic { title status } } } } }""")
        out = []
        for n in (data.get("discountNodes") or {}).get("nodes") or []:
            d = n.get("discount") or {}
            codes = [c.get("code") for c in ((d.get("codes") or {}).get("nodes") or [])]
            val = ((d.get("customerGets") or {}).get("value") or {})
            value = (f"{round(float(val['percentage']) * 100)}%" if val.get("percentage") is not None
                     else (f"{(val.get('amount') or {}).get('amount')} {(val.get('amount') or {}).get('currencyCode')}" if val.get("amount") else None))
            out.append({"id": n.get("id"), "type": d.get("__typename"), "title": d.get("title"), "status": d.get("status"),
                        "codes": codes, "value": value, "starts_at": d.get("startsAt"), "ends_at": d.get("endsAt"),
                        "usage_limit": d.get("usageLimit"), "used": d.get("asyncUsageCount"),
                        "once_per_customer": d.get("appliesOncePerCustomer")})
        return {"count": len(out), "discounts": out}

    async def recent_orders(self, days: int = 7, limit: int = 20) -> Dict[str, Any]:
        days = max(1, min(90, int(days or 7)))
        since = (_now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = await self._gql("""
            query O($q: String!, $n: Int!) { orders(first: $n, query: $q, sortKey: CREATED_AT, reverse: true) { nodes {
              name createdAt displayFinancialStatus displayFulfillmentStatus
              totalPriceSet { shopMoney { amount currencyCode } }
              lineItems(first: 5) { nodes { title quantity } } } } }""",
                               {"q": f"created_at:>={since}", "n": max(1, min(50, int(limit or 20)))})
        out = [{"order": o.get("name"), "date": o.get("createdAt"), "paid": o.get("displayFinancialStatus"),
                "fulfillment": o.get("displayFulfillmentStatus"),
                "total": ((o.get("totalPriceSet") or {}).get("shopMoney") or {}).get("amount"),
                "currency": ((o.get("totalPriceSet") or {}).get("shopMoney") or {}).get("currencyCode"),
                "items": [f"{li.get('quantity')}× {li.get('title')}" for li in ((o.get("lineItems") or {}).get("nodes") or [])]}
               for o in (data.get("orders") or {}).get("nodes") or []]
        return {"days": days, "count": len(out), "orders": out}

    async def web_search(self, query: str) -> Dict[str, Any]:
        if self.ai is None:
            raise AgentError("Căutarea pe internet nu e disponibilă.")
        q = str(query or "").strip()[:500]
        if not q:
            raise AgentError("Spune ce să caut.")
        g: Dict[str, Any] = {}
        prompt = (f"Search Google and answer concisely with facts from the results: {q}\n"
                  "Mention prices with currency, names and dates exactly as the sources show them.")
        try:
            text = await self.ai._call_gemini(prompt, max_tokens=900, temperature=0.2, use_web_search=True,
                                              grounding_out=g, timeout=40.0)
        except Exception as e:
            raise AgentError(f"Căutarea pe internet nu a mers acum ({str(e)[:200]}).")
        sources = [{"title": s.get("title"), "url": s.get("url")} for s in (g.get("sources") or []) if s.get("url")][:8]
        grounded = bool(g.get("web_grounded") or sources)
        return {"answer": text[:3000], "sources": sources, "verified_by_google_search": grounded,
                "note": None if grounded else "NOT based on a Google search: say so to the owner."}

    # ── PROPOSALS (nothing is written here) ───────────────────────────────────

    async def prepare(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if action not in self.WRITE_ACTIONS:
            raise AgentError(f"Acțiunea {action} nu e permisă.")
        fn = getattr(self, f"_prepare_{action}")
        prop = await fn(dict(args or {}))
        prop["action"] = action
        return prop

    async def snapshot(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Current 'before' state, recomputed right before running (stale check)."""
        prop = await getattr(self, f"_prepare_{action}")(dict(args or {}), for_snapshot=True)
        return prop["before"]

    # update_product ----------------------------------------------------------

    async def _prepare_update_product(self, a: Dict[str, Any], for_snapshot: bool = False) -> Dict[str, Any]:
        pid = await self.resolve_product_id(a.get("product") or a.get("product_id"))
        p = await self._product_raw(pid, variants=5)
        desc = str(p.get("descriptionHtml") or "")
        before = {
            "title": p.get("title") or "",
            "description_html": desc,
            "seo_title": (p.get("seo") or {}).get("title") or "",
            "seo_description": (p.get("seo") or {}).get("description") or "",
            "product_type": p.get("productType") or "",
            "tags": sorted(p.get("tags") or []),
        }
        for f in CATEGORY_FIELDS:
            before[f] = [x["id"] for x in p["_category"][f]]
        labels_before = {f: [x["label"] for x in p["_category"][f]] for f in CATEGORY_FIELDS}
        if for_snapshot:
            return {"before": before}

        after = json.loads(json.dumps(before))
        warnings: List[str] = []
        labels_after = dict(labels_before)
        if a.get("title") not in (None, ""):
            t = re.sub(r"\s+", " ", str(a["title"])).strip()
            if len(t) > 255:
                raise AgentError("Titlul e prea lung (max 255 caractere).")
            after["title"] = t
            if _NON_ENGLISH_RE.search(t):
                warnings.append("Titlul conține diacritice — tu vrei titlurile în engleză; verifică înainte să aprobi.")
        if a.get("description_html") not in (None, ""):
            new = _as_html(a["description_html"])
            if len(_strip_html(new)) < 40:
                raise AgentError("Descrierea nouă e prea scurtă (minim 40 de caractere).")
            aeo = _aeo_block(desc)
            if aeo and AEO_START not in new:
                new = new.rstrip() + "\n\n" + aeo  # keep the FAQ/AEO block Jarvis maintains
            after["description_html"] = new
        if a.get("seo_title") not in (None, ""):
            after["seo_title"] = str(a["seo_title"]).strip()
            if len(after["seo_title"]) > 70:
                warnings.append(f"Titlul SEO are {len(after['seo_title'])} caractere; Google arată ~60-70.")
        if a.get("seo_description") not in (None, ""):
            after["seo_description"] = str(a["seo_description"]).strip()
            if len(after["seo_description"]) > 320:
                raise AgentError("Descrierea SEO are peste 320 de caractere (limita Shopify).")
        if a.get("product_type") not in (None, ""):
            after["product_type"] = str(a["product_type"]).strip()[:255]
        tags = set(after["tags"])
        for t in a.get("tags_add") or []:
            t = str(t).strip()
            if t:
                tags.add(t[:255])
        for t in a.get("tags_remove") or []:
            tags.discard(str(t).strip())
        after["tags"] = sorted(tags)
        for f in CATEGORY_FIELDS:
            val = a.get(f)
            if val in (None, "", []):
                continue
            vals = val if isinstance(val, list) else [val]
            matched = await self._labels_to_ids(f, [str(x) for x in vals])
            if f in ("target_gender", "age_group"):
                matched = matched[:1]
            after[f] = [m["id"] for m in matched]
            labels_after[f] = [m["label"] for m in matched]

        rows = []
        names = {"title": "Titlu", "description_html": "Descriere", "seo_title": "Titlu SEO",
                 "seo_description": "Descriere SEO", "product_type": "Tip produs", "tags": "Tag-uri"}
        for k, name in names.items():
            if after[k] != before[k]:
                if k == "tags":
                    added = sorted(set(after[k]) - set(before[k]))
                    removed = sorted(set(before[k]) - set(after[k]))
                    rows.append({"field": name, "before": ", ".join(removed) and f"− {', '.join(removed)}" or "—",
                                 "after": ", ".join(added) and f"+ {', '.join(added)}" or "—"})
                else:
                    rows.append({"field": name, "before": _short(before[k], 300), "after": _short(after[k], 300)})
        for f, spec in CATEGORY_FIELDS.items():
            if after[f] != before[f]:
                rows.append({"field": spec["label"], "before": ", ".join(labels_before[f]) or "—",
                             "after": ", ".join(labels_after[f]) or "—"})
        if not rows:
            raise AgentError("Nu e nimic de schimbat: valorile cerute sunt deja cele din Shopify.")
        missing = [CATEGORY_FIELDS[f]["label"] for f in CATEGORY_FIELDS if not after[f]]
        if missing:
            warnings.append("Lipsesc Category metafields: " + ", ".join(missing) + " (tu vrei să fie mereu completate).")
        if after["description_html"] != before["description_html"] and _aeo_block(desc):
            warnings.append("Blocul FAQ (AEO) de la finalul descrierii rămâne neschimbat.")
        return {
            "args": {**{k: v for k, v in a.items() if k not in ("product", "product_id")}, "product": pid},
            "before": before, "after": after, "labels_after": labels_after,
            "title": f"Modific produsul „{p.get('title')}”", "rows": rows, "warnings": warnings,
            "target": {"type": "product", "id": pid, "label": p.get("title"),
                       "admin_url": f"https://{self.shop}/admin/products/{_legacy(pid)}"},
        }

    async def _write_product_fields(self, pid: str, state: Dict[str, Any], changed: List[str],
                                    rollback_state: Optional[Dict[str, Any]] = None) -> None:
        product: Dict[str, Any] = {"id": pid}
        if "title" in changed:
            product["title"] = state["title"]
        if "description_html" in changed:
            product["descriptionHtml"] = state["description_html"]
        if "product_type" in changed:
            product["productType"] = state["product_type"]
        if "tags" in changed:
            product["tags"] = state["tags"]
        if "seo_title" in changed or "seo_description" in changed:
            product["seo"] = {"title": state["seo_title"], "description": state["seo_description"]}
        if len(product) > 1:
            data = await self._gql("""mutation U($product: ProductUpdateInput!) { productUpdate(product: $product) {
                product { id } userErrors { field message } } }""", {"product": product})
            _user_errors(data.get("productUpdate") or {}, "modificarea produsului")
        try:
            await self._write_category_metafields(pid, state, changed)
        except AgentError as e:
            if len(product) > 1 and rollback_state is not None:
                try:
                    await self._write_product_fields(pid, rollback_state, [k for k in changed if k not in CATEGORY_FIELDS])
                    raise AgentError(f"{e} Am pus la loc și restul câmpurilor: nu s-a schimbat nimic.")
                except AgentError as e2:
                    if "Am pus la loc" in str(e2):
                        raise
                    raise AgentError(f"{e} ATENȚIE: titlul/textele au fost deja schimbate și nu le-am putut pune la loc: {e2}")
            raise

    async def _write_category_metafields(self, pid: str, state: Dict[str, Any], changed: List[str]) -> None:
        to_set, to_delete = [], []
        for f, spec in CATEGORY_FIELDS.items():
            if f in changed:
                if state[f]:
                    to_set.append({"ownerId": pid, "namespace": "shopify", "key": spec["key"],
                                   "type": "list.metaobject_reference", "value": json.dumps(state[f])})
                else:
                    to_delete.append({"ownerId": pid, "namespace": "shopify", "key": spec["key"]})
        if to_set:
            data = await self._gql("""mutation M($m: [MetafieldsSetInput!]!) { metafieldsSet(metafields: $m) {
                metafields { key } userErrors { field message } } }""", {"m": to_set})
            _user_errors(data.get("metafieldsSet") or {}, "category metafields")
        if to_delete:  # only used by undo: restore "was empty"
            data = await self._gql("""mutation D($m: [MetafieldIdentifierInput!]!) { metafieldsDelete(metafields: $m) {
                deletedMetafields { key } userErrors { field message } } }""", {"m": to_delete})
            _user_errors(data.get("metafieldsDelete") or {}, "ștergerea valorii adăugate")

    @staticmethod
    def _changed(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
        return [k for k in after if after.get(k) != before.get(k)]

    @staticmethod
    def _product_state_matches(current: Dict[str, Any], want: Dict[str, Any], keys: List[str]) -> List[str]:
        bad = []
        for k in keys:
            if k == "description_html":
                if _strip_html(current.get(k)) != _strip_html(want.get(k)):
                    bad.append(k)
            elif k == "tags":
                if sorted(current.get(k) or []) != sorted(want.get(k) or []):
                    bad.append(k)
            elif current.get(k) != want.get(k):
                bad.append(k)
        return bad

    # change_prices -------------------------------------------------------------

    async def _prepare_change_prices(self, a: Dict[str, Any], for_snapshot: bool = False) -> Dict[str, Any]:
        pid = await self.resolve_product_id(a.get("product") or a.get("product_id"))
        p = await self._product_raw(pid, variants=100)
        variants = (p.get("variants") or {}).get("nodes") or []
        wanted_ids = [_gid("ProductVariant", v) for v in (a.get("variant_ids") or [])]
        if any(not w for w in wanted_ids):
            raise AgentError("Id de variantă invalid. Folosește id-urile din get_product.")
        by_id = {v["id"]: v for v in variants}
        for w in wanted_ids:
            if w not in by_id:
                raise AgentError(f"Varianta {w} nu aparține produsului „{p.get('title')}”.")
        selected = [by_id[w] for w in wanted_ids] if wanted_ids else variants
        before = {v["id"]: {"price": _money(v.get("price")), "compare_at": _money(v.get("compareAtPrice"))} for v in selected}
        if for_snapshot:
            return {"before": before}
        price = _money(a.get("price")) if a.get("price") not in (None, "") else None
        remove_cmp = bool(a.get("remove_compare_at_price"))
        cmp_ = _money(a.get("compare_at_price")) if a.get("compare_at_price") not in (None, "", 0, "0") else None
        if price is None and cmp_ is None and not remove_cmp:
            raise AgentError("Spune prețul nou și/sau prețul tăiat (compare-at).")
        if price is not None and not (1 <= float(price) <= 10000):
            raise AgentError("Prețul trebuie să fie între 1 și 10.000 EUR.")
        after: Dict[str, Dict[str, Optional[str]]] = {}
        warnings: List[str] = []
        rows = []
        for v in selected:
            b = before[v["id"]]
            np = price or b["price"]
            nc = None if remove_cmp else (cmp_ if cmp_ is not None else b["compare_at"])
            if nc is not None and float(nc) <= float(np):
                raise AgentError(f"Prețul tăiat ({nc}) trebuie să fie mai mare decât prețul ({np}) la „{v.get('title')}”.")
            after[v["id"]] = {"price": np, "compare_at": nc}
            if b != after[v["id"]]:
                rows.append({"field": f"Varianta {v.get('title')}",
                             "before": f"{b['price']} EUR" + (f" (tăiat {b['compare_at']})" if b["compare_at"] else ""),
                             "after": f"{np} EUR" + (f" (tăiat {nc})" if nc else "")})
        if not rows:
            raise AgentError("Prețurile cerute sunt deja cele din Shopify.")
        olds = [float(before[k]["price"]) for k in after if before[k]["price"]]
        if price is not None and olds:
            change = (float(price) - max(olds)) / max(olds) * 100
            if abs(change) >= 30:
                warnings.append(f"Schimbare mare de preț ({change:+.0f}%). Verifică înainte să aprobi.")
            if float(price) < 15:
                warnings.append("Preț foarte mic pentru streetwear premium.")
        if cmp_ is not None and price is not None:
            warnings.append(f"Clientul va vedea reducere de {round((1 - float(price) / float(cmp_)) * 100)}%.")
        if len(rows) > 12:
            rows = rows[:11] + [{"field": f"… încă {len(rows) - 11} variante", "before": "", "after": "la fel"}]
        return {
            "args": {**{k: v for k, v in a.items() if k not in ("product", "product_id")}, "product": pid},
            "before": before, "after": after,
            "title": f"Schimb prețul la „{p.get('title')}” ({len(after)} variante)", "rows": rows, "warnings": warnings,
            "target": {"type": "product", "id": pid, "label": p.get("title"),
                       "admin_url": f"https://{self.shop}/admin/products/{_legacy(pid)}"},
        }

    async def _write_prices(self, pid: str, state: Dict[str, Dict[str, Optional[str]]]) -> None:
        variants = [{"id": vid, "price": s["price"], "compareAtPrice": s["compare_at"]} for vid, s in state.items()]
        data = await self._gql("""mutation V($pid: ID!, $v: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $pid, variants: $v, allowPartialUpdates: false) {
              productVariants { id price compareAtPrice } userErrors { field message } } }""", {"pid": pid, "v": variants})
        _user_errors(data.get("productVariantsBulkUpdate") or {}, "schimbarea prețurilor")

    # create_discount -----------------------------------------------------------

    async def _discount_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        data = await self._gql("""query D($c: String!) { codeDiscountNodeByCode(code: $c) { id codeDiscount {
            ... on DiscountCodeBasic { title status } } } }""", {"c": code})
        node = data.get("codeDiscountNodeByCode")
        return node if isinstance(node, dict) and node.get("id") else None

    async def _prepare_create_discount(self, a: Dict[str, Any], for_snapshot: bool = False) -> Dict[str, Any]:
        code = str(a.get("code") or "").strip().upper()
        if not _DISCOUNT_CODE_RE.match(code):
            raise AgentError("Codul trebuie să aibă 3-30 caractere: litere mari, cifre, - sau _ (ex. BLACKFRIDAY20).")
        if "JARVIS" in code:
            raise AgentError("Codurile de reducere poartă numele mărcii, niciodată „Jarvis”.")
        existing = await self._discount_by_code(code)
        before = {"exists": bool(existing)}
        if for_snapshot:
            return {"before": before}
        if existing:
            raise AgentError(f"Codul {code} există deja în Shopify.")
        pct = a.get("percent")
        amt = a.get("amount_eur")
        if (pct in (None, "", 0)) == (amt in (None, "", 0)):
            raise AgentError("Alege fie procent (percent), fie sumă fixă în EUR (amount_eur).")
        warnings: List[str] = []
        if pct not in (None, "", 0):
            pct = float(pct)
            if not 1 <= pct <= 90:
                raise AgentError("Procentul trebuie să fie între 1 și 90.")
            if pct > 30:
                warnings.append(f"Reducere mare ({pct:g}%) pentru o marcă premium.")
            value_txt = f"{pct:g}%"
        else:
            amt = float(_money(amt))
            if not 1 <= amt <= 500:
                raise AgentError("Suma fixă trebuie să fie între 1 și 500 EUR.")
            value_txt = f"{amt:.2f} EUR"
        starts = _parse_when(a.get("starts_at")) or _now()
        ends = _parse_when(a.get("ends_at"), end_of_day=True)
        if ends and ends <= starts:
            raise AgentError("Data de final trebuie să fie după data de început.")
        usage = a.get("usage_limit")
        usage = int(usage) if usage not in (None, "", 0) else None
        if usage is not None and usage < 1:
            raise AgentError("Limita de utilizări trebuie să fie cel puțin 1.")
        once = a.get("once_per_customer")
        once = True if once is None else bool(once)
        min_sub = _money(a.get("min_subtotal_eur")) if a.get("min_subtotal_eur") not in (None, "", 0) else None
        title = str(a.get("title") or f"Grozavu {code} — {value_txt}").strip()[:255]
        if "jarvis" in title.lower():
            title = f"Grozavu {code} — {value_txt}"
        norm = {"code": code, "percent": pct if isinstance(pct, float) else None,
                "amount_eur": amt if not isinstance(pct, float) else None,
                "starts_at": _iso(starts), "ends_at": _iso(ends) if ends else None, "usage_limit": usage,
                "once_per_customer": once, "min_subtotal_eur": min_sub, "title": title}
        if not ends:
            warnings.append("Codul nu are dată de final (rămâne activ până îl oprești).")
        rows = [
            {"field": "Cod", "before": "—", "after": code},
            {"field": "Valoare", "before": "—", "after": f"{value_txt} la toate produsele"},
            {"field": "Perioadă", "before": "—", "after": f"{starts.astimezone(MADRID):%d.%m.%Y %H:%M} → "
                                                         + (f"{ends.astimezone(MADRID):%d.%m.%Y %H:%M}" if ends else "fără final")},
            {"field": "Limite", "before": "—", "after": ("o dată per client" if once else "nelimitat per client")
                                                       + (f", max {usage} utilizări" if usage else "")
                                                       + (f", comandă minimă {min_sub} EUR" if min_sub else "")},
        ]
        return {"args": norm, "before": before, "after": {"exists": True},
                "title": f"Creez codul de reducere {code} ({value_txt})", "rows": rows, "warnings": warnings,
                "target": {"type": "discount", "id": code, "label": code,
                           "admin_url": f"https://{self.shop}/admin/discounts"}}

    async def _create_discount(self, n: Dict[str, Any]) -> str:
        value = ({"percentage": round(float(n["percent"]) / 100.0, 4)} if n.get("percent")
                 else {"discountAmount": {"amount": f"{float(n['amount_eur']):.2f}", "appliesOnEachItem": False}})
        basic: Dict[str, Any] = {
            "title": n["title"], "code": n["code"], "startsAt": n["starts_at"],
            "context": {"all": "ALL"},
            "customerGets": {"value": value, "items": {"all": True}},
            "appliesOncePerCustomer": bool(n.get("once_per_customer")),
        }
        if n.get("ends_at"):
            basic["endsAt"] = n["ends_at"]
        if n.get("usage_limit"):
            basic["usageLimit"] = int(n["usage_limit"])
        if n.get("min_subtotal_eur"):
            basic["minimumRequirement"] = {"subtotal": {"greaterThanOrEqualToSubtotal": n["min_subtotal_eur"]}}
        mutation = """mutation C($d: DiscountCodeBasicInput!) { discountCodeBasicCreate(basicCodeDiscount: $d) {
            codeDiscountNode { id } userErrors { field message } } }"""
        try:
            data = await self._gql(mutation, {"d": basic})
        except AgentError as e:
            if "context" not in str(e):
                raise
            # older API versions: customerSelection instead of context
            basic.pop("context", None)
            basic["customerSelection"] = {"all": True}
            data = await self._gql(mutation, {"d": basic})
        payload = data.get("discountCodeBasicCreate") or {}
        _user_errors(payload, "crearea codului")
        node = payload.get("codeDiscountNode") or {}
        if not node.get("id"):
            raise AgentError("Shopify nu a confirmat crearea codului.")
        return node["id"]

    # change_collection ---------------------------------------------------------

    async def _prepare_change_collection(self, a: Dict[str, Any], for_snapshot: bool = False) -> Dict[str, Any]:
        cid = _gid("Collection", a.get("collection") or a.get("collection_id"))
        if not cid:
            raise AgentError("Folosește id-ul colecției din list_collections.")
        add = [str(x) for x in (a.get("add_products") or [])]
        rem = [str(x) for x in (a.get("remove_products") or [])]
        if not add and not rem:
            raise AgentError("Spune ce produse adaug sau scot din colecție.")
        if len(add) + len(rem) > MAX_PRODUCTS_PER_COLLECTION_CHANGE:
            raise AgentError(f"Maxim {MAX_PRODUCTS_PER_COLLECTION_CHANGE} produse într-o singură schimbare.")
        try:
            data = await self._gql("""query C($id: ID!) { collection(id: $id) { id title ruleSet { appliedDisjunctively } } }""", {"id": cid})
        except AgentError:
            data = await self._gql("""query C($id: ID!) { collection(id: $id) { id title } }""", {"id": cid})
        col = data.get("collection")
        if not col:
            raise AgentError(f"Colecția {cid} nu există.")
        if col.get("ruleSet"):
            raise AgentError(f"„{col.get('title')}” e o colecție automată (după reguli): produsele intră singure după tag/tip, "
                             "nu pot fi adăugate de mână. Poți adăuga tag-ul potrivit produsului.")
        member: Dict[str, Dict[str, Any]] = {}
        for raw in add + rem:
            pid = await self.resolve_product_id(raw)
            d = await self._gql("""query I($p: ID!, $c: ID!) { product(id: $p) { id title inCollection(id: $c) } }""", {"p": pid, "c": cid})
            pr = d.get("product")
            if not pr:
                raise AgentError(f"Produsul {raw} nu există.")
            member[pid] = {"title": pr.get("title"), "in": bool(pr.get("inCollection"))}
        add_ids = [await self.resolve_product_id(x) for x in add]
        rem_ids = [await self.resolve_product_id(x) for x in rem]
        if for_snapshot:
            return {"before": {pid: member[pid]["in"] for pid in member}}
        to_add = [p for p in dict.fromkeys(add_ids) if not member[p]["in"]]
        to_rem = [p for p in dict.fromkeys(rem_ids) if member[p]["in"] and p not in to_add]
        if not to_add and not to_rem:
            raise AgentError("Nimic de schimbat: produsele sunt deja cum ceri în colecție.")
        before = {pid: member[pid]["in"] for pid in to_add + to_rem}
        after = dict(before)
        for p in to_add:
            after[p] = True
        for p in to_rem:
            after[p] = False
        rows = [{"field": member[p]["title"], "before": "nu e în colecție", "after": "adăugat"} for p in to_add]
        rows += [{"field": member[p]["title"], "before": "în colecție", "after": "scos (produsul rămâne în magazin)"} for p in to_rem]
        return {"args": {"collection": cid, "add_products": to_add, "remove_products": to_rem, "collection_title": col.get("title")},
                "before": before, "after": after,
                "title": f"Schimb produsele din colecția „{col.get('title')}”", "rows": rows, "warnings": [],
                "target": {"type": "collection", "id": cid, "label": col.get("title"),
                           "admin_url": f"https://{self.shop}/admin/collections/{_legacy(cid)}"}}

    async def _set_membership(self, cid: str, pid: str, inside: bool) -> None:
        product = {"id": pid, ("collectionsToJoin" if inside else "collectionsToLeave"): [cid]}
        data = await self._gql("""mutation U($product: ProductUpdateInput!) { productUpdate(product: $product) {
            product { id } userErrors { field message } } }""", {"product": product})
        _user_errors(data.get("productUpdate") or {}, "schimbarea colecției")

    # set_product_status --------------------------------------------------------

    async def _prepare_set_product_status(self, a: Dict[str, Any], for_snapshot: bool = False) -> Dict[str, Any]:
        pid = await self.resolve_product_id(a.get("product") or a.get("product_id"))
        p = await self._product_raw(pid, variants=100)
        before = {"status": p.get("status"), "published": p["_published"]}
        if for_snapshot:
            return {"before": before}
        status = str(a.get("status") or "").strip().upper()
        if status not in ("ACTIVE", "DRAFT"):
            raise AgentError("Statusul poate fi doar ACTIVE (vizibil) sau DRAFT (ciornă). Arhivarea/ștergerea le faci tu din Shopify.")
        publish = a.get("publish_online_store")
        publish = (status == "ACTIVE") if publish is None else bool(publish)
        if status == "DRAFT":
            publish = before["published"]  # drafting does not touch channels
        warnings: List[str] = []
        if publish and not before["published"] and not self.can("write_publications"):
            publish = False
            warnings.append("Produsul nu e pe Online Store și aplicația Jarvis nu are permisiunea de publicare "
                            "(write_publications): după aprobare, bifează Online Store la produs (Publishing) în Shopify.")
        after = {"status": status, "published": bool(publish or before["published"])}
        if after == before:
            raise AgentError("Produsul are deja statusul cerut." if not warnings else warnings[0])
        if status == "ACTIVE":
            if not (p.get("mediaCount") or {}).get("count"):
                warnings.append("Produsul nu are nicio poză.")
            prices = [float(v.get("price") or 0) for v in ((p.get("variants") or {}).get("nodes") or [])]
            if not prices or min(prices) <= 0:
                warnings.append("Are variante cu preț 0.")
            if _NON_ENGLISH_RE.search(str(p.get("title") or "")):
                warnings.append("Titlul pare să nu fie în engleză.")
            if len(_strip_html(p.get("descriptionHtml"))) < 40:
                warnings.append("Descrierea lipsește sau e foarte scurtă.")
            missing = [CATEGORY_FIELDS[f]["label"] for f in CATEGORY_FIELDS if not p["_category"][f]]
            if missing:
                warnings.append("Lipsesc Category metafields: " + ", ".join(missing) + ".")
        rows = []
        if after["status"] != before["status"]:
            rows.append({"field": "Status", "before": before["status"], "after": status})
        if after["published"] != before["published"]:
            rows.append({"field": "Online Store", "before": "nepublicat", "after": "publicat"})
        return {"args": {"product": pid, "status": status, "publish_online_store": after["published"]},
                "before": before, "after": after,
                "title": f"{'Activez' if status == 'ACTIVE' else 'Trec în ciornă'} „{p.get('title')}”",
                "rows": rows, "warnings": warnings,
                "target": {"type": "product", "id": pid, "label": p.get("title"),
                           "admin_url": f"https://{self.shop}/admin/products/{_legacy(pid)}"}}

    async def _write_status(self, pid: str, before: Dict[str, Any], want: Dict[str, Any]) -> None:
        if want["status"] != before["status"]:
            data = await self._gql("""mutation U($product: ProductUpdateInput!) { productUpdate(product: $product) {
                product { id status } userErrors { field message } } }""", {"product": {"id": pid, "status": want["status"]}})
            _user_errors(data.get("productUpdate") or {}, "schimbarea statusului")
        if want["published"] != before["published"]:
            pub = await self.online_store_publication()
            if not pub:
                raise AgentError("Nu găsesc canalul Online Store în magazin.")
            if want["published"]:
                data = await self._gql("""mutation P($id: ID!, $in: [PublicationInput!]!) { publishablePublish(id: $id, input: $in) {
                    userErrors { field message } } }""", {"id": pid, "in": [{"publicationId": pub}]})
                _user_errors(data.get("publishablePublish") or {}, "publicarea pe Online Store")
            else:
                data = await self._gql("""mutation P($id: ID!, $in: [PublicationInput!]!) { publishableUnpublish(id: $id, input: $in) {
                    userErrors { field message } } }""", {"id": pid, "in": [{"publicationId": pub}]})
                _user_errors(data.get("publishableUnpublish") or {}, "retragerea de pe Online Store")

    # ── EXECUTE / VERIFY / UNDO (only after the owner pressed a button) ──────

    async def execute(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        action, args, before, after = rec["action"], rec["args"], rec["before"], rec["after"]
        if action == "update_product":
            changed = self._changed(before, after)
            await self._write_product_fields(args["product"], after, changed, rollback_state=before)
            return {"changed": changed}
        if action == "change_prices":
            await self._write_prices(args["product"], after)
            return {"variants": len(after)}
        if action == "create_discount":
            did = await self._create_discount(args)
            return {"discount_id": did}
        if action == "change_collection":
            done: List[Tuple[str, bool]] = []
            try:
                for pid in args.get("add_products") or []:
                    await self._set_membership(args["collection"], pid, True)
                    done.append((pid, True))
                for pid in args.get("remove_products") or []:
                    await self._set_membership(args["collection"], pid, False)
                    done.append((pid, False))
            except AgentError as e:
                await self._rollback_membership(args["collection"], done, e)
            return {"added": len(args.get("add_products") or []), "removed": len(args.get("remove_products") or [])}
        if action == "set_product_status":
            try:
                await self._write_status(args["product"], before, after)
            except AgentError as e:
                if after["status"] != before["status"]:
                    try:
                        await self._write_status(args["product"], {"status": after["status"], "published": before["published"]},
                                                 {"status": before["status"], "published": before["published"]})
                    except AgentError as e2:
                        raise AgentError(f"{e} ATENȚIE: statusul a rămas {after['status']} și nu l-am putut pune la loc: {e2}")
                    raise AgentError(f"{e} Am pus statusul la loc: nu s-a schimbat nimic.")
                raise
            return {"status": after["status"], "published": after["published"]}
        raise AgentError(f"Acțiune necunoscută: {action}")

    async def _rollback_membership(self, cid: str, done: List[Tuple[str, bool]], err: AgentError) -> None:
        failed: List[str] = []
        for pid, inside in reversed(done):
            try:
                await self._set_membership(cid, pid, not inside)
            except AgentError:
                failed.append(pid)
        if failed:
            raise AgentError(f"{err} ATENȚIE: {len(failed)} produse au rămas schimbate în colecție.")
        raise AgentError(f"{err} Am pus la loc ce apucasem să schimb: nu s-a schimbat nimic.")

    async def verify(self, rec: Dict[str, Any], want_after: bool = True) -> Tuple[bool, str]:
        """Re-read Shopify and check the state is the expected one (after, or before for undo)."""
        action, args = rec["action"], rec["args"]
        want = rec["after"] if want_after else rec["before"]
        if action == "create_discount":
            node = await self._discount_by_code(args["code"])
            if want_after:
                ok = bool(node) and str(((node or {}).get("codeDiscount") or {}).get("status") or "") in ("ACTIVE", "SCHEDULED")
                return ok, "Codul există în Shopify." if ok else "Codul nu apare activ în Shopify."
            status = str(((node or {}).get("codeDiscount") or {}).get("status") or "")
            ok = (not node) or status in ("EXPIRED",)
            return ok, "Codul nu mai poate fi folosit." if ok else f"Codul are încă statusul {status}."
        current = await self.snapshot(action, args)
        if action == "update_product":
            keys = self._changed(rec["before"], rec["after"])
            bad = self._product_state_matches(current, want, keys)
            return (not bad), ("Verificat în Shopify." if not bad else "Nu se potrivesc: " + ", ".join(bad))
        ok = current == want
        return ok, "Verificat în Shopify." if ok else "Shopify arată altceva decât era de așteptat."

    async def undo(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        action, args, before, after = rec["action"], rec["args"], rec["before"], rec["after"]
        if action == "update_product":
            changed = self._changed(before, after)
            await self._write_product_fields(args["product"], before, changed)
            return {"restored": changed}
        if action == "change_prices":
            await self._write_prices(args["product"], before)
            return {"variants": len(before)}
        if action == "create_discount":
            did = ((rec.get("result") or {}).get("discount_id")) or ((await self._discount_by_code(args["code"])) or {}).get("id")
            if not did:
                raise AgentError("Nu mai găsesc codul în Shopify.")
            data = await self._gql("""mutation X($id: ID!) { discountCodeDeactivate(id: $id) {
                codeDiscountNode { id } userErrors { field message } } }""", {"id": did})
            _user_errors(data.get("discountCodeDeactivate") or {}, "dezactivarea codului")
            return {"deactivated": did}
        if action == "change_collection":
            for pid in args.get("add_products") or []:
                await self._set_membership(args["collection"], pid, False)
            for pid in args.get("remove_products") or []:
                await self._set_membership(args["collection"], pid, True)
            return {"reverted": True}
        if action == "set_product_status":
            await self._write_status(args["product"], after, before)
            return {"status": before["status"]}
        raise AgentError(f"Acțiune necunoscută: {action}")


def proposal_is_expired(rec: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    try:
        created = datetime.fromisoformat(str(rec.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now or _now()) - created > PROPOSAL_TTL
