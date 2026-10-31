"""
Drip Cadence Manager & State Machine Engine for Jarvis.
Handles 30m / 4h / 24h recovery cadence timing, dynamic discount injection,
and order conversion reconciliation.
"""

import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import database as db


class DripCadenceManager:
    """
    Autonomous 3-Stage Drip Recovery Cadence:
      - Stage 1: >= 30m post-abandonment (NO discount, assistance tone)
      - Stage 2: >= 4h post-abandonment (MG10 10% discount, sweeten deal)
      - Stage 3: >= 24h post-abandonment (MG10, final reminder — no invented scarcity:
        Shopify does NOT reserve stock for abandoned checkouts)
      - Cutoff: > 72h post-abandonment or current_stage == 3 -> Exhausted

    Concurrency: callers should move a checkout to a stage with
    database.claim_drip_stage(checkout_id, expected_stage, new_stage) BEFORE sending
    and database.release_drip_stage(...) if every channel failed.
    Frequency/compliance: use sequence_key(checkout_id) with compliance_guard.
    """

    STAGE_1_MIN_SECONDS = 30 * 60       # 30 minutes (1,800s)
    STAGE_2_MIN_SECONDS = 4 * 3600      # 4 hours (14,400s)
    STAGE_3_MIN_SECONDS = 24 * 3600     # 24 hours (86,400s)
    CADENCE_CUTOFF_SECONDS = 72 * 3600  # 72 hours (259,200s)

    # Minimum spacing between stage dispatches to prevent rapid cadence cascading
    STAGE_2_MIN_INTERVAL_SECONDS = int(3.5 * 3600)  # 3.5 hours (12,600s) after stage 1
    STAGE_3_MIN_INTERVAL_SECONDS = 18 * 3600        # 18 hours (64,800s) after stage 2

    DISCOUNT_CODE_MG10 = "MG10"

    @staticmethod
    def sequence_key(checkout_id: Any) -> str:
        """Frequency-policy key for an abandoned-cart sequence (compliance_guard sequence_key)."""
        return f"cart:{checkout_id}"

    @classmethod
    def parse_datetime(cls, dt_val: Any) -> Optional[datetime]:
        """Normalizes any ISO string or naive/aware datetime into a UTC timezone-aware datetime.
        Returns None safely if parsing fails or input is invalid."""
        if not dt_val:
            return None
        try:
            if isinstance(dt_val, str):
                clean_str = dt_val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
            elif isinstance(dt_val, datetime):
                dt = dt_val
            else:
                return None

            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None

    def evaluate_drip_stage(
        self,
        checkout_dict: Dict,
        state_record: Optional[Dict] = None,
        now_dt: Optional[datetime] = None
    ) -> Optional[int]:
        """
        Evaluates whether a checkout is eligible to transition to the next drip stage.
        
        Rules:
          - Age < 30m: Returns None (too early)
          - Age >= 30m and stage == 0: Returns 1 (Stage 1)
          - Age >= 4h and stage == 1: Returns 2 (Stage 2)
          - Age >= 24h and stage == 2: Returns 3 (Stage 3)
          - Age > 72h or stage >= 3: Returns None (Exhausted)
          - status != 'active': Returns None (Converted / Canceled / Exhausted)
        """
        now = (self.parse_datetime(now_dt) if now_dt else None) or datetime.now(timezone.utc)

        # 1. Status Check
        if state_record:
            status = state_record.get("status", "active")
            if status != "active":
                return None
            current_stage = int(state_record.get("current_stage", 0) or 0)
            raw_created = state_record.get("created_at") or checkout_dict.get("created_at")
        else:
            current_stage = 0
            raw_created = checkout_dict.get("created_at")

        cart_dt = self.parse_datetime(raw_created)
        if cart_dt is None:
            return None

        age_seconds = (now - cart_dt).total_seconds()

        # Check negative age (cart created in the future due to clock skew)
        if age_seconds < 0:
            return None

        # 2. Cutoff Check (72 hours or stage 3 completed)
        if age_seconds > self.CADENCE_CUTOFF_SECONDS or current_stage >= 3:
            return None

        # 3. Stage 1 Evaluation (>= 30m, current_stage == 0)
        if current_stage == 0:
            if age_seconds >= self.STAGE_1_MIN_SECONDS:
                return 1
            return None

        # 4. Stage 2 Evaluation (>= 4h, current_stage == 1, interval >= 3.5h since Stage 1)
        if current_stage == 1:
            if age_seconds < self.STAGE_2_MIN_SECONDS:
                return None
            if state_record:
                stage_1_sent = state_record.get("stage_1_sent_at")
                if stage_1_sent is not None:
                    s1_dt = self.parse_datetime(stage_1_sent)
                    if s1_dt is None or (now - s1_dt).total_seconds() < self.STAGE_2_MIN_INTERVAL_SECONDS:
                        return None
            return 2

        # 5. Stage 3 Evaluation (>= 24h, current_stage == 2, interval >= 18h since Stage 2)
        if current_stage == 2:
            if age_seconds < self.STAGE_3_MIN_SECONDS:
                return None
            if state_record:
                stage_2_sent = state_record.get("stage_2_sent_at")
                if stage_2_sent is not None:
                    s2_dt = self.parse_datetime(stage_2_sent)
                    if s2_dt is None or (now - s2_dt).total_seconds() < self.STAGE_3_MIN_INTERVAL_SECONDS:
                        return None
            return 3

        return None

    def build_stage_checkout_url(self, raw_url: str, stage: int) -> str:
        """
        Generates checkout URL with strict discount policy:
          - Stage 1: Clean raw checkout link (strips any existing discount query param).
          - Stages 2 & 3: Injects 'discount=MG10'.
        """
        if not raw_url:
            return ""

        parsed = urllib.parse.urlparse(raw_url)
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

        # Filter out existing discount parameter
        filtered_params = [(k, v) for k, v in query_params if k.lower() != "discount"]

        if stage == 1:
            # Stage 1: Strict NO DISCOUNT
            new_query = urllib.parse.urlencode(filtered_params)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
        else:
            # Stage 2 and 3: Apply MG10
            filtered_params.append(("discount", self.DISCOUNT_CODE_MG10))
            new_query = urllib.parse.urlencode(filtered_params)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def get_stage_metadata(self, stage: int) -> Dict[str, Any]:
        """Returns metadata for email template, copywriter, and logging."""
        if stage == 1:
            return {
                "stage": 1,
                "discount_code": None,
                "has_discount": False,
                "discount_percent": 0,
                "tone": "support",
                "urgency": False,
                "label": "Stage 1 — Customer Assistance (30m, No Discount)"
            }
        elif stage == 2:
            return {
                "stage": 2,
                "discount_code": self.DISCOUNT_CODE_MG10,
                "has_discount": True,
                "discount_percent": 10,
                "tone": "exclusive_discount",
                "urgency": False,
                "label": "Stage 2 — Sweeten the Deal (4h, 10% OFF MG10)"
            }
        elif stage == 3:
            return {
                "stage": 3,
                "discount_code": self.DISCOUNT_CODE_MG10,
                "has_discount": True,
                "discount_percent": 10,
                "tone": "urgency",
                "urgency": True,
                "label": "Stage 3 — Final Reminder (24h, MG10)"
            }
        raise ValueError(f"Invalid cadence stage: {stage}")

    def mark_order_converted(self, shop: str, order_dict: Dict) -> bool:
        """
        Reconciles completed order to cancel all remaining drip stages.
        Matches by checkout_id, checkout_token, or customer email.
        Returns True if any drip state was closed. NOTE: that alone is not a "recovery";
        use reconcile_order() to know whether Jarvis had actually sent a message.
        """
        cid = order_dict.get("checkout_id")
        token = order_dict.get("checkout_token")
        cust = order_dict.get("customer") or {}
        if not isinstance(cust, dict):
            cust = {}
        email = db.normalize_email(order_dict.get("email") or order_dict.get("contact_email") or cust.get("email")) or ""
        order_id = str(order_dict.get("id") or "")
        try:
            revenue = float(order_dict.get("total_price") or 0.0)
        except (TypeError, ValueError):
            revenue = 0.0

        rows = db.mark_drip_converted(
            shop=shop,
            checkout_id=str(cid) if cid else None,
            email=email or None,
            checkout_token=str(token) if token else None,
            order_id=order_id,
            revenue=revenue
        )
        return rows > 0

    def reconcile_order(self, shop: str, order_dict: Dict) -> Dict[str, Any]:
        """
        Like mark_order_converted, but truthful about attribution:
        {"converted": <rows closed>, "attributed": <True only if at least one closed checkout
        had received a Jarvis message (current_stage > 0)>}. Only fire a "revenue recovered"
        alert when attributed is True.
        """
        cid = order_dict.get("checkout_id")
        token = order_dict.get("checkout_token")
        cust = order_dict.get("customer") or {}
        if not isinstance(cust, dict):
            cust = {}
        email = db.normalize_email(order_dict.get("email") or order_dict.get("contact_email") or cust.get("email")) or ""
        try:
            revenue = float(order_dict.get("total_price") or 0.0)
        except (TypeError, ValueError):
            revenue = 0.0
        rows, attributed = db.mark_drip_converted(
            shop=shop,
            checkout_id=str(cid) if cid else None,
            email=email or None,
            checkout_token=str(token) if token else None,
            order_id=str(order_dict.get("id") or ""),
            revenue=revenue,
            return_attribution=True,
        )
        return {"converted": int(rows or 0), "attributed": bool(attributed)}
