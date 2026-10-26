# Test Infrastructure Specification: Shopify Jarvis

## 1. Overview & Architecture

The Shopify Jarvis automated test infrastructure is designed according to the opaque-box verification paradigm. It validates all 5 core revenue upgrades against the architectural interface contracts defined in `PROJECT.md` and `ORIGINAL_REQUEST.md` without requiring a live Shopify store, PostgreSQL database, or external messaging APIs.

```
                  ┌──────────────────────────────────────────────┐
                  │          Shopify Jarvis E2E Suite            │
                  │   python -m unittest discover -s tests       │
                  └──────────────────────┬───────────────────────┘
                                         │
        ┌──────────────────┬─────────────┴────────────┬──────────────────┐
        ▼                  ▼                          ▼                  ▼
┌───────────────┐  ┌───────────────┐          ┌───────────────┐  ┌───────────────┐
│    Tier 1     │  │    Tier 2     │          │    Tier 3     │  │    Tier 4     │
│Feature Coverage│  │  Boundaries   │          │ Cross-Feature │  │ Real Workloads│
│  (25 tests)   │  │  (25 tests)   │          │   (6 tests)   │  │   (5 tests)   │
└───────┬───────┘  └───────┬───────┘          └───────┬───────┘  └───────┬───────┘
        │                  │                          │                  │
        └──────────────────┼──────────────────────────┴──────────────────┘
                           ▼
                  ┌──────────────────────────────────────────────┐
                  │               tests/helpers.py               │
                  │  - Synthetic Shopify Fixtures                │
                  │  - Progressive Testability Introspection     │
                  │  - In-Memory Mocking & Client Emulation      │
                  └──────────────────────────────────────────────┘
```

---

## 2. Test Execution Command

The test suite runs with standard Python:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

In PowerShell:
```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 3. The 4-Tier Test Methodology

The test suite contains **61 test cases** organized across 4 tiers:

### Tier 1: Feature Coverage (25 Tests)
Validates the happy-path behavior and contract compliance for each feature:
- **Feature 1: Product Visual Showcase in Emails (`test_tier1_features.py`)**
  - `test_f1_01_single_item_thumbnail_rendering`: Thumbnail (90x90), title, and price rendering.
  - `test_f1_02_multi_item_table_showcase`: Itemized table rendering for multi-item cart.
  - `test_f1_03_stage1_no_discount_suppresses_coupon`: Suppression of coupon box for Stage 1.
  - `test_f1_04_stage2_discount_coupon_rendering`: Coupon card with code `MG10` for Stage 2.
  - `test_f1_05_multilingual_label_localization`: Multi-language CTA buttons (`it`, `ro`, `en`).
- **Feature 2: Smart 3-Step Drip Recovery Cadence (`test_tier1_features.py`)**
  - `test_f2_01_stage1_evaluation_at_30m`: Stage 1 evaluated at >=30m with no discount.
  - `test_f2_02_stage2_evaluation_at_4h`: Stage 2 evaluated at >=4h with code `MG10`.
  - `test_f2_03_stage3_evaluation_at_24h`: Stage 3 evaluated at >=24h with urgency `MG10`.
  - `test_f2_04_under_30m_returns_none`: Evaluation <30m suppressed.
  - `test_f2_05_order_conversion_cancels_drip`: Order conversion halts subsequent drip stages.
- **Feature 3: Autonomous WhatsApp Dispatcher (`test_tier1_features.py`)**
  - `test_f3_01_canonical_wa_me_link_generation`: Canonical `https://wa.me/{clean_phone}?text={quote(message)}`.
  - `test_f3_02_twilio_provider_dispatch`: Twilio API payload and auth dispatch.
  - `test_f3_03_meta_cloud_provider_dispatch`: Meta Cloud API Bearer token dispatch.
  - `test_f3_04_auto_provider_waterfall_to_wa_me`: Automatic fallback to `wa.me` link.
  - `test_f3_05_per_store_settings_injection`: Store-specific settings override globals.
- **Feature 4: Post-Delivery VIP Review & Upsell Automation (`test_tier1_features.py`)**
  - `test_f4_01_fulfillment_ingestion_and_scheduling`: 5-day post-fulfillment scheduling.
  - `test_f4_02_vip_discount_code_mgvip15`: VIP discount code `MGVIP15` enforcement.
  - `test_f4_03_process_due_vip_automations_dispatch`: Processing due records and status `'sent'`.
  - `test_f4_04_vip_copy_generation_gratitude_and_upsell`: Gratitude, review request & upsell copy.
  - `test_f4_05_cross_channel_vip_delivery`: Email and WhatsApp dual VIP dispatch.
- **Feature 5: Instant Mobile Notifications (`test_tier1_features.py`)**
  - `test_f5_01_telegram_abandoned_cart_alert`: Telegram HTML formatted alert.
  - `test_f5_02_discord_abandoned_cart_embed`: Discord Rich Embed with amber color `0xF59E0B`.
  - `test_f5_03_telegram_recovery_converted_alert`: Telegram recovery conversion alert.
  - `test_f5_04_discord_recovery_converted_embed`: Discord Rich Embed with emerald color `0x10B981`.
  - `test_f5_05_vip_upsell_sent_notification`: Discord/Telegram notification with purple `0x6366F1`.

---

### Tier 2: Boundary & Corner Cases (25 Tests)
Validates system resilience under extreme, malformed, or boundary inputs (`test_tier2_boundaries.py`):
- **Feature 1 Boundaries**:
  - `test_f1_b01_empty_line_items_fallback`: Empty line items array `[]`.
  - `test_f1_b02_missing_product_image_placeholder`: `image_url=None` placeholder handling.
  - `test_f1_b03_extreme_long_product_title`: 500-character titles without container overflow.
  - `test_f1_b04_special_characters_html_escaping`: XSS scripts (`<script>`) & quotes escaping.
  - `test_f1_b05_currency_formatting_edge_cases`: Zero values (`0.00`), large values, JPY, EUR, USD.
- **Feature 2 Boundaries**:
  - `test_f2_b01_edge_timestamp_29m_vs_31m`: Boundary check 29m (None) vs 31m (Stage 1).
  - `test_f2_b02_edge_timestamp_3h59m_vs_4h1m`: Boundary check 3h59m (None) vs 4h1m (Stage 2).
  - `test_f2_b03_edge_timestamp_23h59m_vs_24h1m`: Boundary check 23h59m (None) vs 24h1m (Stage 3).
  - `test_f2_b04_cadence_expiration_over_72h`: Expiration check >72h transitions to `'exhausted'`.
  - `test_f2_b05_duplicate_checkout_id_idempotency`: Idempotent evaluation guards.
- **Feature 3 Boundaries**:
  - `test_f3_b01_invalid_and_short_phone_numbers`: Rejection of `"123"`, `"abc"`, `""`, `None`.
  - `test_f3_b02_international_prefix_variations`: Normalization of `+39`, `0039`, `39`, spaces, dashes.
  - `test_f3_b03_meta_24h_window_rejection_fallback`: Meta 400 error `131047` fallback to `wa.me`.
  - `test_f3_b04_network_timeout_resilience`: HTTP timeout resilience with fallback link.
  - `test_f3_b05_url_encoding_special_characters_wa_me`: Special characters (`%`, `&`, `+`, emojis).
- **Feature 4 Boundaries**:
  - `test_f4_b01_order_without_fulfillments_ignored`: Unfulfilled orders suppressed.
  - `test_f4_b02_edge_timestamp_4d23h_vs_5d1m`: Boundary check 4d23h (None) vs 5d1m (due).
  - `test_f4_b03_cancelled_order_fulfillment_suppression`: Cancelled/refunded orders suppressed.
  - `test_f4_b04_multiple_fulfillments_latest_date_used`: Multiple shipments use latest timestamp.
  - `test_f4_b05_empty_customer_email_and_phone`: Missing contact details handled gracefully.
- **Feature 5 Boundaries**:
  - `test_f5_b01_missing_bot_token_or_chat_id`: Missing Telegram credentials handled cleanly.
  - `test_f5_b02_missing_discord_webhook_url`: Missing Discord URL handled cleanly.
  - `test_f5_b03_telegram_html_special_chars_escaping`: Special HTML chars (`<`, `>`, `&`) escaped.
  - `test_f5_b04_discord_embed_field_length_limits`: Discord field length <= 1024 chars truncated.
  - `test_f5_b05_notification_disabled_toggles`: Notification disabled flags respected.

---

### Tier 3: Cross-Feature Combinations (6 Tests)
Validates interactions between independent channels and state machines (`test_tier3_cross_feature.py`):
- `test_f_cross_01_email_and_whatsapp_dual_dispatch`: Visual email + localized wa.me link generation.
- `test_f_cross_02_drip_stage2_discount_triggers_discord_alert`: Stage 2 cadence dispatches discount email and fires Discord alert.
- `test_f_cross_03_conversion_reconciliation_cancels_drip_and_alerts`: Order conversion aborts pending drip stages and sends recovery conversion alert.
- `test_f_cross_04_vip_review_generates_multichannel_and_mobile_alert`: 5-day post-delivery triggers VIP email with `MGVIP15`, generates WhatsApp link, and alerts Telegram.
- `test_f_cross_05_multilingual_geo_to_email_and_whatsapp`: Language detection (`it`) harmonizes across both email template and WhatsApp copy.
- `test_f_cross_06_drip_stage1_preserves_raw_url_and_neutral_whatsapp`: Stage 1 recovery strictly suppresses discount code across all channels.

---

### Tier 4: Real-World Workload Scenarios (5 Tests)
Validates complete application lifecycles from cart creation to post-delivery upsell (`test_tier4_workloads.py`):
- `test_f_workload_01_full_lifecycle_abandon_to_vip_review`: End-to-end 6-day lifecycle: Cart abandon -> Stage 1 (30m) -> Stage 2 (4h) -> Order placed -> Drip cancellation -> Fulfillment -> 5 days later VIP review with `MGVIP15`.
- `test_f_workload_02_early_conversion_aborts_stages_2_and_3`: Conversion at 1h permanently aborts Stage 2 and Stage 3.
- `test_f_workload_03_exhausted_unresponsive_cart`: Unresponsive cart flows through Stages 1-3 and expires at >72h.
- `test_f_workload_04_multi_item_currency_vip_flow`: High-value USD multi-item cart correctly formatted and tracked through VIP sequence.
- `test_f_workload_05_failure_recovery_and_resilience`: Provider timeout triggers safe retry without corrupted state or double discount.

---

## 4. Progressive Testability Mechanism

To allow parallel milestone development without false build-break alerts:
1. `tests/helpers.py` dynamically introspects backend module presence and signature capabilities (`HAS_CADENCE_MANAGER`, `HAS_POST_DELIVERY`, `HAS_MOBILE_NOTIFIER`, `HAS_EMAIL_LINE_ITEMS`, `HAS_WA_SEND_MESSAGE`, `HAS_CANONICAL_WA_ME`).
2. Tests for milestones not yet implemented automatically skip with explicit milestone dependency messages (`"pending Milestone 1"`, `"pending Milestone 2"`, etc.).
3. Once an implementing agent introduces a new module or method, the corresponding tests immediately activate without test suite modifications.

---

## 5. Artifact Manifest

| Path | Purpose | Test Count |
|---|---|---|
| `tests/helpers.py` | Fixtures, mock generators, and progressive capability checks | N/A |
| `tests/test_tier1_features.py` | Tier 1: Core Feature Coverage | 25 tests |
| `tests/test_tier2_boundaries.py` | Tier 2: Boundary & Corner Cases | 25 tests |
| `tests/test_tier3_cross_feature.py` | Tier 3: Cross-Feature Combinations | 6 tests |
| `tests/test_tier4_workloads.py` | Tier 4: Real-World Workload Scenarios | 5 tests |
| `TEST_INFRA.md` | Infrastructure specification and architecture manual | N/A |
| `TEST_READY.md` | Test Suite Readiness Declaration | N/A |
| **Total** | | **61 tests** |
