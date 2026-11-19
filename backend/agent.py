"""
backend/agent.py
Jarvis agent: the owner writes in the chat, Gemini decides which store data to read and which
changes to PROPOSE (function calling). Proposals are saved and shown as cards; nothing is written
to Shopify until the owner presses "Aprobă" (approve_action). See agent_tools.py for the rules.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import database as db
    from agent_tools import AgentError, AgentToolbox, proposal_is_expired
    from ai_advisor import GeminiUnavailable, LANG_NAMES, normalize_lang
except ImportError:  # pragma: no cover - package import path
    from backend import database as db
    from backend.agent_tools import AgentError, AgentToolbox, proposal_is_expired
    from backend.ai_advisor import GeminiUnavailable, LANG_NAMES, normalize_lang

MAX_STEPS = 8
MAX_CALLS_PER_STEP = 6
MAX_TOOL_RESULT_CHARS = 12000
_ACTION_LOCKS: Dict[str, asyncio.Lock] = {}

S = {"type": "string"}
N = {"type": "number"}
B = {"type": "boolean"}


def _obj(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {"name": "search_products", "description": "Search the store's products (title words, or Shopify search syntax like 'status:draft', 'tag:hoodie', 'product_type:Hoodie'). Returns ids, titles, status, prices.",
     "parameters": _obj({"query": S, "limit": N})},
    {"name": "get_product", "description": "Full details of one product: variants with ids and prices, tags, SEO, description, collections, category metafields (color, fabric, target gender, age group), publish status.",
     "parameters": _obj({"product": {"type": "string", "description": "product id (gid://shopify/Product/...) or handle"}}, ["product"])},
    {"name": "list_collections", "description": "List collections with ids, product counts and whether they are manual or automatic.",
     "parameters": _obj({"query": S})},
    # no "parameters" key: Gemini rejects an OBJECT with empty properties
    {"name": "list_discounts", "description": "List the store's discounts and discount codes with status and value."},
    {"name": "recent_orders", "description": "Recent orders (number, date, total, status, items). No customer personal data.",
     "parameters": _obj({"days": N, "limit": N})},
    {"name": "web_search", "description": "Search the internet with Google for current outside information (competitors, prices elsewhere, trends, suppliers, news, how-to). Returns an answer with source links.",
     "parameters": _obj({"query": S}, ["query"])},
    {"name": "propose_product_update", "description": "PROPOSE changes to one product (the owner must approve). Titles/SEO/descriptions in ENGLISH. Category metafields take labels like colors=['Black'], fabrics=['Cotton'], target_gender='Male|Female|Unisex', age_group='Adults'.",
     "parameters": _obj({
         "product": {"type": "string", "description": "product id from search_products/get_product"},
         "title": S, "description_html": S, "seo_title": S, "seo_description": S, "product_type": S,
         "tags_add": {"type": "array", "items": S}, "tags_remove": {"type": "array", "items": S},
         "colors": {"type": "array", "items": S}, "fabrics": {"type": "array", "items": S},
         "target_gender": S, "age_group": S}, ["product"])},
    {"name": "propose_price_change", "description": "PROPOSE a new price and/or compare-at (crossed-out) price for a product's variants (all variants unless variant_ids given). The owner must approve.",
     "parameters": _obj({"product": S, "price": N, "compare_at_price": N, "remove_compare_at_price": B,
                         "variant_ids": {"type": "array", "items": S}}, ["product"])},
    {"name": "propose_discount_code", "description": "PROPOSE a new discount code for all products (percent OR amount_eur). Dates as YYYY-MM-DD (Madrid). The owner must approve.",
     "parameters": _obj({"code": S, "percent": N, "amount_eur": N, "starts_at": S, "ends_at": S, "usage_limit": N,
                         "once_per_customer": B, "min_subtotal_eur": N, "title": S}, ["code"])},
    {"name": "propose_collection_change", "description": "PROPOSE adding/removing products in a MANUAL collection (ids from list_collections and search_products). The owner must approve.",
     "parameters": _obj({"collection": S, "add_products": {"type": "array", "items": S},
                         "remove_products": {"type": "array", "items": S}}, ["collection"])},
    {"name": "propose_status_change", "description": "PROPOSE setting a product ACTIVE (visible, published on the Online Store) or DRAFT. The owner must approve.",
     "parameters": _obj({"product": S, "status": {"type": "string", "enum": ["ACTIVE", "DRAFT"]},
                         "publish_online_store": B}, ["product", "status"])},
]

PROPOSE_TO_ACTION = {
    "propose_product_update": "update_product",
    "propose_price_change": "change_prices",
    "propose_discount_code": "create_discount",
    "propose_collection_change": "change_collection",
    "propose_status_change": "set_product_status",
}
READ_TOOLS = {
    "search_products": ("query", "limit"),
    "get_product": ("product",),
    "list_collections": ("query",),
    "list_discounts": (),
    "recent_orders": ("days", "limit"),
    "web_search": ("query",),
}


def system_instruction(shop_name: str, lang: str, store_text: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"""You are Jarvis, the store operator of {shop_name} (maisongrozavu.com), a premium streetwear brand founded in Spain. You work for the owner inside his Shopify admin. Today is {today}. Prices are in EUR.

How you work:
- Use the tools to READ real data before answering or proposing anything. Never invent products, ids, prices, numbers or results. Use ids exactly as tools return them.
- You can NOT change the store yourself. The propose_* tools only create a proposal card; the change happens only after the owner presses "Aprobă" (Approve). After proposing, say clearly what you proposed and that it waits for his approval. Never say a change is done.
- One proposal per product/discount/collection; keep proposals small and precise.
- Product titles, SEO texts and product descriptions are always written in ENGLISH (the owner translates the store with an app).
- When you propose a product update and its category metafields (color, fabric, target gender, age group) are empty, fill them too, based on the product.
- For anything outside the store (competitors, prices elsewhere, trends, suppliers, how-to, news) use web_search and give the source links. If web_search says it is not based on a Google search, tell the owner.
- You never delete, archive, refund, touch payments or themes, or email customers. If asked, explain he has to do it in Shopify admin.
- If a tool returns an error, explain it simply; do not repeat the same failing call.
- Reply in {LANG_NAMES.get(lang, 'Romanian')}, short and clear, with "•" bullets when useful, no markdown headers.

Current store snapshot:
{store_text}"""


def _trim(obj: Any) -> Dict[str, Any]:
    txt = json.dumps(obj, ensure_ascii=False, default=str)
    if len(txt) <= MAX_TOOL_RESULT_CHARS:
        return obj if isinstance(obj, dict) else {"result": obj}
    return {"result_truncated": txt[:MAX_TOOL_RESULT_CHARS]}


def public_action(rec: Dict[str, Any]) -> Dict[str, Any]:
    """What the panel shows for one action (no raw before/after blobs)."""
    status = rec.get("status")
    expired = status == "proposed" and proposal_is_expired(rec)
    return {
        "id": rec.get("id"), "action": rec.get("action"), "status": "expired" if expired else status,
        "title": rec.get("title"), "rows": rec.get("rows") or [], "warnings": rec.get("warnings") or [],
        "target": rec.get("target") or {}, "created_at": rec.get("created_at"),
        "executed_at": rec.get("executed_at"), "undone_at": rec.get("undone_at"),
        "message": rec.get("message"), "error": rec.get("error"),
        "can_approve": status == "proposed" and not expired,
        "can_undo": status == "executed",
    }


async def _dispatch(toolbox: AgentToolbox, shop: str, name: str, args: Dict[str, Any],
                    proposals: List[Dict[str, Any]], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        if name in READ_TOOLS:
            res = await getattr(toolbox, name)(**{k: v for k, v in (args or {}).items() if k in READ_TOOLS[name]})
            if name == "web_search":
                for s in res.get("sources") or []:
                    if s.get("url") and s["url"] not in [x.get("url") for x in sources]:
                        sources.append(s)
            return _trim(res)
        if name in PROPOSE_TO_ACTION:
            prop = await toolbox.prepare(PROPOSE_TO_ACTION[name], args or {})
            rec = {
                "id": uuid.uuid4().hex, "shop": shop, "status": "proposed", "action": prop["action"],
                "args": prop["args"], "before": prop["before"], "after": prop["after"],
                "title": prop["title"], "rows": prop["rows"], "warnings": prop["warnings"],
                "target": prop["target"], "created_at": datetime.now(timezone.utc).isoformat(),
            }
            db.save_agent_action(shop, rec)
            proposals.append(rec)
            return {"status": "proposed_waiting_for_owner_approval", "proposal_id": rec["id"],
                    "summary": rec["title"], "changes": rec["rows"], "warnings": rec["warnings"]}
        return {"error": f"Unknown tool {name}"}
    except AgentError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"Wrong arguments for {name}: {str(e)[:200]}"}


def _history_contents(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in history[-8:]:
        role = "model" if m.get("role") == "assistant" else "user"
        text = str(m.get("content") or "").strip()[:2000]
        if not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["parts"][0]["text"] += "\n" + text
        else:
            out.append({"role": role, "parts": [{"text": text}]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


async def run_agent(ai: Any, toolbox: AgentToolbox, shop: str, shop_name: str, message: str,
                    history: List[Dict[str, Any]], lang: str, store_text: str) -> Dict[str, Any]:
    """One owner message → reply + proposals. Raises GeminiUnavailable if the model is down."""
    lang = normalize_lang(lang, "ro") or "ro"
    contents = _history_contents(history)
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += "\n" + message
    else:
        contents.append({"role": "user", "parts": [{"text": message}]})
    body_base = {
        "systemInstruction": {"parts": [{"text": system_instruction(shop_name, lang, store_text)}]},
        "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }
    proposals: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    tools_used: List[str] = []
    model: Optional[str] = None
    reply = ""
    for _step in range(MAX_STEPS):
        body = dict(body_base, contents=contents)
        # Stay on the model that answered first: its thought signatures only work with itself.
        data, model = await ai._gemini_request(body, models=[model] if model else None)
        cand = ((data or {}).get("candidates") or [{}])[0]
        parts = ((cand.get("content") or {}).get("parts")) or []
        if not parts:
            reply = reply or ""
            break
        contents.append({"role": "model", "parts": parts})
        calls = [p["functionCall"] for p in parts if isinstance(p, dict) and isinstance(p.get("functionCall"), dict)]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        if not calls:
            reply = text.strip()
            break
        responses = []
        for call in calls[:MAX_CALLS_PER_STEP]:
            name = str(call.get("name") or "")
            tools_used.append(name)
            result = await _dispatch(toolbox, shop, name, call.get("args") or {}, proposals, sources)
            fr: Dict[str, Any] = {"name": name, "response": result}
            if call.get("id"):
                fr["id"] = call["id"]
            responses.append({"functionResponse": fr})
        contents.append({"role": "user", "parts": responses})
    else:
        reply = ("Am făcut mulți pași fără să termin. Spune-mi mai precis ce vrei (un produs sau o schimbare odată)."
                 if lang == "ro" else "I took too many steps without finishing. Please ask for one thing at a time.")
    if not reply:
        reply = ("Am pregătit propunerile de mai jos." if proposals else "Nu am primit un răspuns clar de la model; încearcă din nou.") \
            if lang == "ro" else ("I prepared the proposals below." if proposals else "No clear answer from the model; please retry.")
    if proposals and lang == "ro" and "Aprob" not in reply:
        reply += "\n\nNimic nu se schimbă în Shopify până nu apeși „Aprobă” pe fiecare propunere."
    return {"reply": reply, "actions": [public_action(p) for p in proposals], "sources": sources[:8],
            "web_grounded": bool(sources), "tools_used": tools_used, "model": model}


# ── owner buttons ─────────────────────────────────────────────────────────────

def _lock(action_id: str) -> asyncio.Lock:
    lock = _ACTION_LOCKS.get(action_id)
    if lock is None:
        lock = _ACTION_LOCKS[action_id] = asyncio.Lock()
    return lock


def _stale(toolbox: AgentToolbox, rec: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if rec["action"] == "update_product":
        keys = toolbox._changed(rec["before"], rec["after"])
        return bool(toolbox._product_state_matches(current, rec["before"], keys))
    return current != rec["before"]


async def approve_action(toolbox: AgentToolbox, shop: str, action_id: str) -> Dict[str, Any]:
    async with _lock(action_id):
        rec = db.get_agent_action(shop, action_id)
        if not rec:
            raise AgentError("Propunerea nu există.")
        if rec.get("status") != "proposed":
            return public_action(rec)
        if proposal_is_expired(rec):
            rec.update(status="expired", message="Propunerea a expirat (24h). Cere-i lui Jarvis să o refacă.")
            db.save_agent_action(shop, rec)
            return public_action(rec)
        try:
            current = await toolbox.snapshot(rec["action"], rec["args"])
        except AgentError as e:
            rec.update(status="failed", error=f"Nu am putut verifica starea actuală: {e}")
            db.save_agent_action(shop, rec)
            return public_action(rec)
        if _stale(toolbox, rec, current):
            rec.update(status="stale", message="Între timp s-a schimbat ceva în Shopify. Nu am modificat nimic; "
                                                "cere-i lui Jarvis să refacă propunerea cu datele noi.")
            db.save_agent_action(shop, rec)
            return public_action(rec)
        rec["status"] = "executing"
        db.save_agent_action(shop, rec)
        try:
            rec["result"] = await toolbox.execute(rec)
        except AgentError as e:
            rec.update(status="failed", error=str(e))
            db.save_agent_action(shop, rec)
            return public_action(rec)
        except Exception as e:  # unknown outcome: never claim success
            rec.update(status="failed", error=f"Rezultat necunoscut ({type(e).__name__}); verifică în Shopify.")
            db.save_agent_action(shop, rec)
            return public_action(rec)
        rec["executed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            ok, note = await toolbox.verify(rec, want_after=True)
        except AgentError as e:
            ok, note = False, f"Nu am putut reciti Shopify: {e}"
        rec["status"] = "executed"
        rec["message"] = ("✅ Făcut și verificat în Shopify." if ok
                          else f"⚠️ Shopify a acceptat schimbarea, dar verificarea arată altceva: {note}")
        rec["verified"] = ok
        db.save_agent_action(shop, rec)
        return public_action(rec)


async def reject_action(shop: str, action_id: str) -> Dict[str, Any]:
    async with _lock(action_id):
        rec = db.get_agent_action(shop, action_id)
        if not rec:
            raise AgentError("Propunerea nu există.")
        if rec.get("status") == "proposed":
            rec.update(status="rejected", message="Respinsă. Nu s-a schimbat nimic.")
            db.save_agent_action(shop, rec)
        return public_action(rec)


async def undo_action(toolbox: AgentToolbox, shop: str, action_id: str) -> Dict[str, Any]:
    async with _lock(action_id):
        rec = db.get_agent_action(shop, action_id)
        if not rec:
            raise AgentError("Acțiunea nu există.")
        if rec.get("status") != "executed":
            return public_action(rec)
        # Only undo if nobody changed the same thing after us.
        if rec["action"] != "create_discount":
            try:
                current = await toolbox.snapshot(rec["action"], rec["args"])
            except AgentError as e:
                rec["error"] = f"Nu am putut verifica starea actuală: {e}"
                db.save_agent_action(shop, rec)
                return public_action(rec)
            if rec["action"] == "update_product":
                keys = toolbox._changed(rec["before"], rec["after"])
                changed_since = bool(toolbox._product_state_matches(current, rec["after"], keys))
            else:
                changed_since = current != rec["after"]
            if changed_since:
                rec["error"] = "Între timp s-a schimbat din nou în Shopify; nu anulez ca să nu stric modificarea nouă."
                db.save_agent_action(shop, rec)
                return public_action(rec)
        try:
            rec["undo_result"] = await toolbox.undo(rec)
        except AgentError as e:
            rec["error"] = f"Anularea nu a mers: {e}"
            db.save_agent_action(shop, rec)
            return public_action(rec)
        try:
            ok, note = await toolbox.verify(rec, want_after=False)
        except AgentError as e:
            ok, note = False, str(e)
        rec["status"] = "undone"
        rec["undone_at"] = datetime.now(timezone.utc).isoformat()
        rec["error"] = None
        rec["message"] = ("↩️ Anulat și verificat: totul e ca înainte." if ok
                          else f"↩️ Anulat, dar verificarea arată altceva: {note}")
        db.save_agent_action(shop, rec)
        return public_action(rec)
