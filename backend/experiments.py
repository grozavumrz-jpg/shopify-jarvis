"""
backend/experiments.py
Jarvis learns from REAL results, without tracking pixels:

1. Subject-line A/B tests for the emails Jarvis writes from templates
   (cart reminder step 1, thank-you after delivery, 30-day reminder).
   * Each customer gets variant A or B (stable 50/50 split by a hash of the email).
   * A sale counts for the last test email the customer received in the 7 days before ordering
     (refunded / cancelled orders never count).
   * A winner is declared only with enough data: at least 30 emails per variant, at least
     5 sales in total and 95% probability that it is better. Until then it says so plainly.
   * After a winner: 90% of emails use the winner, 10% keep testing the other one.

2. Best sending hours for NON-urgent emails (thank-you, 30-day reminder), learned from the store's
   real GA4 data: the hours when the most engaged visitors are on the site (inside 09:00–21:00,
   the hours Jarvis is allowed to write). Cart reminders are never delayed.

Only a one-way hash of the email is stored (deleted on GDPR redact).
"""

import hashlib
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import database as db
except ImportError:  # pragma: no cover
    from backend import database as db

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover
    MADRID = timezone.utc

KINDS = {
    "cart_stage_1": "Coș abandonat — primul email",
    "vip": "Mulțumire după livrare",
    "winback": "Reamintire după 30 de zile",
}
MIN_SENDS_PER_VARIANT = 30
MIN_TOTAL_CONVERSIONS = 5
WIN_PROBABILITY = 0.95
EXPLORE_SHARE = 10            # % of emails that keep testing the losing variant
ATTRIBUTION_DAYS = 7
SEND_HOURS_ALLOWED = range(9, 21)   # 09:00–20:59 Madrid (quiet hours 21:00–09:00)
BEST_HOURS_COUNT = 4
MIN_ENGAGED_FOR_HOURS = 60

# ── B variants (A = the existing subjects) ───────────────────────────────────
CART_STAGE1_SUBJECT_B = {
    "ro": "Coșul tău de la {shop} te așteaptă",
    "es": "Tu carrito en {shop} te espera",
    "it": "Il tuo carrello su {shop} ti aspetta",
    "de": "Dein Warenkorb bei {shop} wartet auf dich",
    "fr": "Votre panier sur {shop} vous attend",
    "en": "Your cart at {shop} is waiting",
}
VIP_SUBJECT_B = {
    "ro": "{name_prefix}ce părere ai de noua ta piesă? Ai 15% cu {discount_code}",
    "es": "{name_prefix}¿qué te parece tu nueva prenda? Tienes un 15% con {discount_code}",
    "it": "{name_prefix}come ti trovi con il nuovo capo? 15% con {discount_code}",
    "de": "{name_prefix}wie gefällt dir dein neues Teil? 15% mit {discount_code}",
    "fr": "{name_prefix}votre nouvelle pièce vous plaît ? 15% avec {discount_code}",
    "en": "{name_prefix}how's your new piece? 15% off with {discount_code}",
}
WINBACK_SUBJECT_B = {
    "ro": "{name_prefix}următoarea ta piesă {brand}? Ai 15% cu {discount_code}",
    "es": "{name_prefix}¿tu próxima prenda {brand}? Tienes un 15% con {discount_code}",
    "it": "{name_prefix}pronto per il prossimo capo {brand}? 15% con {discount_code}",
    "de": "{name_prefix}bereit für dein nächstes {brand}-Teil? 15% mit {discount_code}",
    "fr": "{name_prefix}prêt pour votre prochaine pièce {brand} ? 15% avec {discount_code}",
    "en": "{name_prefix}ready for your next {brand} piece? 15% off with {discount_code}",
}


def _lang(lang: Optional[str]) -> str:
    clean = (lang or "en").strip().lower().replace("_", "-").split("-")[0]
    return clean if clean in CART_STAGE1_SUBJECT_B else "en"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _clean_name(name: Optional[str]) -> str:
    n = (name or "").strip()
    return "" if n.lower() in ("client", "valued client", "customer", "cliente", "kunde", "cumpărător") else n


def cart_stage1_subject_b(lang: Optional[str], shop_name: str) -> str:
    return CART_STAGE1_SUBJECT_B[_lang(lang)].format(shop=shop_name)


def vip_subject_b(lang: Optional[str], customer_name: Optional[str], discount_code: str) -> str:
    n = _clean_name(customer_name)
    return _cap(VIP_SUBJECT_B[_lang(lang)].format(name_prefix=f"{n}, " if n else "", discount_code=discount_code))


def winback_subject_b(lang: Optional[str], customer_name: Optional[str], discount_code: str, brand: str) -> str:
    n = _clean_name(customer_name)
    return _cap(WINBACK_SUBJECT_B[_lang(lang)].format(name_prefix=f"{n}, " if n else "",
                                                      discount_code=discount_code, brand=brand))


# ── statistics ───────────────────────────────────────────────────────────────

def _prob_b_better(n_a: int, c_a: int, n_b: int, c_b: int) -> float:
    """P(rate_B > rate_A) with Beta(1,1) priors, normal approximation."""
    pa, pb = (c_a + 1) / (n_a + 2), (c_b + 1) / (n_b + 2)
    va = pa * (1 - pa) / (n_a + 3)
    vb = pb * (1 - pb) / (n_b + 3)
    sd = math.sqrt(va + vb)
    if sd <= 0:
        return 0.5
    return 0.5 * (1 + math.erf((pb - pa) / (sd * math.sqrt(2))))


def evaluate_kind(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by = {r["variant"]: r for r in rows}
    a = by.get("A", {"sends": 0, "conversions": 0, "revenue": 0.0})
    b = by.get("B", {"sends": 0, "conversions": 0, "revenue": 0.0})
    n_a, c_a, n_b, c_b = int(a["sends"]), int(a["conversions"]), int(b["sends"]), int(b["conversions"])
    p_b = _prob_b_better(n_a, c_a, n_b, c_b)
    winner = None
    if min(n_a, n_b) >= MIN_SENDS_PER_VARIANT and (c_a + c_b) >= MIN_TOTAL_CONVERSIONS:
        if p_b >= WIN_PROBABILITY:
            winner = "B"
        elif p_b <= 1 - WIN_PROBABILITY:
            winner = "A"
    if winner:
        status = f"Câștigător: varianta {winner} (sigur în proporție de {round(100 * max(p_b, 1 - p_b))}%)."
    else:
        need = []
        if min(n_a, n_b) < MIN_SENDS_PER_VARIANT:
            need.append(f"minim {MIN_SENDS_PER_VARIANT} emailuri pe variantă (acum A {n_a}, B {n_b})")
        if (c_a + c_b) < MIN_TOTAL_CONVERSIONS:
            need.append(f"minim {MIN_TOTAL_CONVERSIONS} vânzări în total (acum {c_a + c_b})")
        status = ("Se strâng date: " + "; ".join(need) + ".") if need else \
            "Încă nu e o diferență sigură între variante; testul continuă."
    return {
        "variants": {
            "A": {"sends": n_a, "conversions": c_a, "revenue": round(float(a["revenue"]), 2),
                  "rate_pct": round(100 * c_a / n_a, 1) if n_a else None},
            "B": {"sends": n_b, "conversions": c_b, "revenue": round(float(b["revenue"]), 2),
                  "rate_pct": round(100 * c_b / n_b, 1) if n_b else None},
        },
        "probability_b_better_pct": round(100 * p_b),
        "winner": winner,
        "status_ro": status,
    }


_STATS_CACHE: Dict[str, Any] = {}
_STATS_TTL = 600


def _stats(shop: str) -> Dict[str, List[Dict[str, Any]]]:
    hit = _STATS_CACHE.get(shop)
    if hit and time.time() - hit[0] < _STATS_TTL:
        return hit[1]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    try:
        for r in db.get_experiment_stats(shop):
            grouped.setdefault(r["kind"], []).append(r)
    except Exception as e:  # noqa: BLE001 - a stats failure must never block an email
        print(f"[Experiments] stats unavailable: {str(e)[:120]}")
    _STATS_CACHE[shop] = (time.time(), grouped)
    return grouped


def choose_variant(shop: str, kind: str, email: str) -> str:
    """Stable per customer: 50/50 while testing; 90% winner / 10% other after a winner."""
    key = f"{kind}|{(email or '').strip().lower()}"
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100
    winner = evaluate_kind(_stats(shop).get(kind, [])).get("winner")
    if winner:
        other = "B" if winner == "A" else "A"
        return winner if bucket >= EXPLORE_SHARE else other
    return "A" if bucket < 50 else "B"


def record_send(shop: str, kind: str, variant: str, email: str, lang: Optional[str],
                now: Optional[datetime] = None) -> None:
    now = now or datetime.now(timezone.utc)
    try:
        hour = now.astimezone(MADRID).hour
        db.record_experiment_send(shop, kind, variant, email, lang, sent_at=now, send_hour=hour)
        _STATS_CACHE.pop(shop, None)
    except Exception as e:  # noqa: BLE001 - logging a test must never fail an email
        print(f"[Experiments] could not record send: {str(e)[:120]}")


def attribute_order(shop: str, order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mark a sale for the last test email this customer got in the 7 days before ordering."""
    if not isinstance(order, dict):
        return None
    if order.get("cancelled_at") or str(order.get("financial_status") or "").lower() in ("refunded", "voided"):
        return None
    cust = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    email = (order.get("email") or cust.get("email") or "").strip()
    oid = str(order.get("id") or "").strip()
    created = order.get("created_at")
    if not email or not oid or not created:
        return None
    try:
        created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        revenue = float(order.get("total_price") or 0)
        res = db.attribute_experiment_conversion(shop, email, oid, created_dt, revenue, ATTRIBUTION_DAYS)
        if res:
            _STATS_CACHE.pop(shop, None)
        return res
    except Exception as e:  # noqa: BLE001
        print(f"[Experiments] attribution failed for order {oid}: {str(e)[:120]}")
        return None


# ── best sending hours (GA4) ─────────────────────────────────────────────────

BEST_HOURS: Dict[str, Any] = {"hours": [], "computed_at": None, "engaged_sessions": 0, "source": None}


def compute_best_hours(ga4_hours: Dict[str, Any]) -> Dict[str, Any]:
    rows = [r for r in (ga4_hours or {}).get("hours") or [] if isinstance(r, dict)]
    allowed = [r for r in rows if r.get("hour") in SEND_HOURS_ALLOWED]
    engaged_total = sum(int(r.get("engaged_sessions") or 0) for r in allowed)
    result = {"hours": [], "engaged_sessions": engaged_total, "computed_at": time.time(),
              "source": "GA4, ultimele %s zile (fusul orar al proprietății GA4)" % (ga4_hours or {}).get("days", 28)}
    if engaged_total < MIN_ENGAGED_FOR_HOURS:
        result["note_ro"] = (f"Prea puține vizite implicate în GA4 ({engaged_total}) ca să aleg o oră; "
                             "emailurile neurgente pleacă la orice oră permisă (09–21).")
        return result
    top = sorted(allowed, key=lambda r: (-int(r.get("engaged_sessions") or 0), r["hour"]))[:BEST_HOURS_COUNT]
    result["hours"] = sorted(r["hour"] for r in top)
    result["note_ro"] = ("Emailurile de mulțumire și reamintire pleacă la orele cu cei mai mulți vizitatori "
                         "implicați: " + ", ".join(f"{h:02d}:00" for h in result["hours"]) + ".")
    return result


def set_best_hours(result: Dict[str, Any]) -> None:
    BEST_HOURS.clear()
    BEST_HOURS.update(result or {})


def is_good_send_hour(now: Optional[datetime] = None) -> bool:
    """For NON-urgent emails only. True when no hours were learned (no restriction)."""
    hours = BEST_HOURS.get("hours") or []
    if not hours:
        return True
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(MADRID).hour in hours


def learning_report(shop: str) -> Dict[str, Any]:
    stats = _stats(shop)
    tests = []
    for kind, label in KINDS.items():
        ev = evaluate_kind(stats.get(kind, []))
        tests.append({"kind": kind, "label": label, **ev})
    return {
        "tests": tests,
        "rules_ro": [
            "Fiecare client primește mereu aceeași variantă (A sau B), împărțire 50/50.",
            "O vânzare contează pentru ultimul email de test primit în cele 7 zile dinainte de comandă; comenzile anulate sau rambursate nu contează.",
            f"Câștigătorul se alege doar cu minim {MIN_SENDS_PER_VARIANT} emailuri pe variantă, {MIN_TOTAL_CONVERSIONS} vânzări și 95% siguranță.",
            "După ce există un câștigător, 90% din emailuri îl folosesc, 10% continuă testul.",
        ],
        "best_hours": {k: BEST_HOURS.get(k) for k in ("hours", "engaged_sessions", "source", "note_ro")},
    }
