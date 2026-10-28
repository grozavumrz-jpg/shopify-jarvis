from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
import database as db

# Quiet hours: 21:00 (9 PM) to 09:00 (9 AM) in Europe/Bucharest (UTC+2 standard / UTC+3 DST)
# During quiet hours, promotional / marketing messages are withheld to prevent customer annoyance.
def is_quiet_hours(now_dt: Optional[datetime] = None) -> bool:
    """
    Check if the current time falls within night quiet hours (21:00 to 09:00)
    for store's Romanian local time (Europe/Bucharest).
    """
    dt = now_dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Approximate Bucharest local time: UTC + 2 hours (winter) / +3 (summer)
    # Using UTC+2 as baseline safe threshold
    bucharest_hour = (dt.hour + 2) % 24
    return bucharest_hour >= 21 or bucharest_hour < 9


def can_dispatch_to_customer(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    channel: str = "email",
    bypass_quiet_hours: bool = False,
    now_dt: Optional[datetime] = None
) -> Tuple[bool, str]:
    """
    Verify customer marketing consent, frequency caps, and quiet hours.
    Returns (allowed: bool, reason: str).
    """
    recipient = (email or phone or "").strip().lower()
    if not recipient:
        return False, "Recipient is empty"

    # 1. Quiet Hours check
    if not bypass_quiet_hours and is_quiet_hours(now_dt):
        return False, "Quiet hours active (21:00-09:00 Europe/Bucharest). Outreach paused to prevent spam perception."

    # 2. Explicit Consent & Opt-Out check
    if not db.is_consent_given(shop_domain, email=email, phone=phone):
        return False, f"Customer {recipient} has explicitly opted out or denied marketing consent."

    # 3. Frequency Cap check (Max 1 per 72h, max 3 per 30d)
    can_send, freq_reason = db.can_send_message_frequency(
        shop_domain, recipient=recipient, channel=channel, max_per_72h=1, max_per_30d=3
    )
    if not can_send:
        return False, freq_reason

    return True, "OK"


def log_customer_dispatch(
    shop_domain: str,
    recipient: str,
    channel: str,
    message_type: str
) -> bool:
    """Record dispatch in frequency tracker."""
    return db.record_message_sent(shop_domain, recipient, channel, message_type)
