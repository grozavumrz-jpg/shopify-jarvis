"""
Messaging compliance guard (EU / Spain LSSI + GDPR).

Rules (CONTRACT.md):
- Marketing messages ONLY with explicit consent for that channel identity
  (email consent -> normalized email, WhatsApp consent -> normalized phone).
  Unknown consent == NO consent. Opt-out always wins.
- Quiet hours 21:00–09:00 Europe/Madrid (zoneinfo, DST-correct).
- Frequency: cart sequence max 3 per checkout; VIP max 1 per order; max 4 marketing
  messages per recipient per rolling 30 days; a NEW sequence/VIP is blocked if the
  recipient got any marketing message in the last 72h (follow-ups of the same
  sequence_key are exempt from that 72h rule).
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

try:
    import database as db
except ImportError:  # pragma: no cover - package-style import
    from backend import database as db

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

QUIET_TIMEZONE = "Europe/Madrid"
QUIET_START_HOUR = 21  # 21:00 local
QUIET_END_HOUR = 9     # 09:00 local
QUIET_HOURS_LABEL = "21:00–09:00 (ora Spaniei)"

FREQUENCY_POLICY: Dict[str, Any] = {
    "cart_max_per_checkout": db.SEQUENCE_LIMITS["cart"],
    "cart_stage_delays": ["30m", "4h", "24h"],
    "vip_max_per_order": db.SEQUENCE_LIMITS["vip"],
    "max_marketing_per_30d": db.MAX_MARKETING_PER_30D,
    "new_sequence_cooldown_hours": db.NEW_SEQUENCE_COOLDOWN_HOURS,
    "followups_exempt_from_cooldown": True,
    "quiet_hours": QUIET_HOURS_LABEL,
    "quiet_hours_timezone": QUIET_TIMEZONE,
    "consent_required": True,
    "unknown_consent_means": "no_consent",
    "description_ro": (
        "Coș abandonat: max 3 mesaje per checkout (30m / 4h / 24h); VIP: max 1 per comandă; "
        "max 4 mesaje de marketing per destinatar în 30 de zile; o secvență nouă este blocată dacă "
        "destinatarul a primit un mesaj de marketing în ultimele 72h. Fără consimțământ explicit = fără mesaje."
    ),
}

# Stable reason prefixes (callers may branch on them via is_transient_block()).
REASON_EMPTY = "Recipient is empty"
REASON_QUIET = "Quiet hours"
REASON_FREQUENCY = "Frequency cap"
REASON_OPTED_OUT = "Customer opted out"
REASON_NO_CONSENT = "No marketing consent"
REASON_DENIED = "Marketing consent denied"

MARKETING = "marketing"
TRANSACTIONAL = "transactional"

_PHONE_CHANNELS = ("whatsapp", "sms", "phone", "wa")


def _madrid_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(QUIET_TIMEZONE)
        except (ZoneInfoNotFoundError, Exception):
            return None
    return None


def _last_sunday(year: int, month: int) -> int:
    # Day-of-month of the last Sunday (EU DST switch rule)
    d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d.day


def _madrid_local_fallback(dt_utc: datetime) -> datetime:
    """EU rule without tz database: CET (+1), CEST (+2) from last Sun of March 01:00 UTC to last Sun of Oct 01:00 UTC."""
    y = dt_utc.year
    start = datetime(y, 3, _last_sunday(y, 3), 1, 0, tzinfo=timezone.utc)
    end = datetime(y, 10, _last_sunday(y, 10), 1, 0, tzinfo=timezone.utc)
    offset = 2 if start <= dt_utc < end else 1
    return (dt_utc + timedelta(hours=offset)).replace(tzinfo=None)


def madrid_local_time(now_dt: Optional[datetime] = None) -> datetime:
    """Local Europe/Madrid wall-clock time for an instant (naive datetimes are treated as UTC)."""
    dt = now_dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = _madrid_tz()
    if tz is not None:
        return dt.astimezone(tz)
    return _madrid_local_fallback(dt.astimezone(timezone.utc))


def is_quiet_hours(now_dt: Optional[datetime] = None) -> bool:
    """True between 21:00 and 09:00 Europe/Madrid local time (DST-correct)."""
    local = madrid_local_time(now_dt)
    return local.hour >= QUIET_START_HOUR or local.hour < QUIET_END_HOUR


REASON_SEQUENCE_EXHAUSTED = "Frequency cap: sequence"
REASON_EPHEMERAL_DB = "Persistent database required"


def ephemeral_db_blocks_marketing() -> bool:
    """
    On Render the local SQLite file is wiped on every restart/deploy. Unsubscribes, consent records and
    the per-person message history would be forgotten, so a customer who opted out could be messaged
    again. Marketing therefore waits for DATABASE_URL (Postgres). JARVIS_ALLOW_EPHEMERAL_DB=1 overrides.
    """
    if os.getenv("JARVIS_ALLOW_EPHEMERAL_DB", "").strip().lower() in ("1", "true", "yes"):
        return False
    on_render = bool(os.getenv("RENDER", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip())
    return on_render and bool(getattr(db, "USING_SQLITE", False))


def is_transient_block(reason: Optional[str]) -> bool:
    """
    Quiet hours, the 72h / 30-day frequency windows and a missing persistent database clear with time.
    Consent blocks and an exhausted sequence (e.g. VIP already sent for that order) do not.
    """
    r = reason or ""
    if r.startswith(REASON_SEQUENCE_EXHAUSTED):
        return False
    return r.startswith(REASON_QUIET) or r.startswith(REASON_FREQUENCY) or r.startswith(REASON_EPHEMERAL_DB)


def _is_phone_channel(channel: Optional[str]) -> bool:
    return (channel or "email").strip().lower() in _PHONE_CHANNELS


def can_dispatch_to_customer(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    channel: str = "email",
    bypass_quiet_hours: bool = False,
    now_dt: Optional[datetime] = None,
    message_type: str = MARKETING,
    sequence_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check ONE channel for ONE customer. Returns (allowed, reason).
    - channel "email": uses `email` (email consent); channel "whatsapp"/"sms": uses `phone`
      (phone consent). Email consent never authorizes WhatsApp.
    - message_type "marketing" (default; abandoned cart and VIP ARE marketing) requires
      consent + frequency policy; only an explicit "transactional" skips those.
    - sequence_key e.g. "cart:<checkout_id>" / "vip:<order_id>".
    """
    phone_channel = _is_phone_channel(channel)
    if phone_channel:
        recipient = db.normalize_phone(phone)
        chan = "whatsapp"
    else:
        recipient = db.normalize_email(email)
        if recipient and "@" not in recipient:
            recipient = None
        chan = "email"
    if not recipient:
        return False, f"{REASON_EMPTY} for channel {chan}"

    is_marketing = (message_type or MARKETING).strip().lower() != TRANSACTIONAL

    if is_marketing and ephemeral_db_blocks_marketing():
        return False, (f"{REASON_EPHEMERAL_DB}: DATABASE_URL lipsește — pe Render baza locală se șterge la restart "
                       "și s-ar pierde dezabonările. Marketingul pornește automat după ce adaugi Postgres.")

    if is_marketing:
        status = db.get_consent_status(
            shop_domain,
            email=recipient if not phone_channel else None,
            phone=recipient if phone_channel else None,
            channel="sms" if phone_channel else "email",
        )
        if status == db.CONSENT_OPTED_OUT:
            return False, f"{REASON_OPTED_OUT} ({chan}): customer has explicitly opted out / unsubscribed."
        if status == db.CONSENT_DENIED:
            return False, f"{REASON_DENIED} ({chan}): customer did not accept marketing."
        if status != db.CONSENT_GRANTED:
            return False, f"{REASON_NO_CONSENT} ({chan}): no recorded consent (unknown consent = no consent)."

    if not bypass_quiet_hours and is_quiet_hours(now_dt):
        return False, f"{REASON_QUIET} active ({QUIET_HOURS_LABEL}, {QUIET_TIMEZONE}). Outreach paused."

    if is_marketing:
        # Caps are per PERSON: also count messages sent to this customer's other identity
        other = db.normalize_email(email) if phone_channel else db.normalize_phone(phone)
        ok, freq_reason = db.can_send_message_frequency(
            shop_domain,
            recipient=recipient,
            channel=chan,
            max_per_72h=1,
            max_per_30d=db.MAX_MARKETING_PER_30D,
            sequence_key=sequence_key,
            now_dt=now_dt,
            related_recipients=[other] if other else None,
            message_type=message_type,
        )
        if not ok:
            reason = freq_reason if freq_reason.startswith(REASON_FREQUENCY) else f"{REASON_FREQUENCY}: {freq_reason}"
            return False, reason

    return True, "OK"


def log_customer_dispatch(
    shop_domain: str,
    recipient: str,
    channel: str,
    message_type: str,
    sequence_key: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> bool:
    """Record a dispatched marketing message (normalized recipient) in the frequency tracker."""
    chan = "whatsapp" if _is_phone_channel(channel) else "email"
    return db.record_message_sent(
        shop_domain, recipient, chan, message_type, sequence_key=sequence_key, sent_at=sent_at
    )
