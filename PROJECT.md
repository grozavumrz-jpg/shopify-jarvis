# Project: Shopify Jarvis — 5 Core Revenue Upgrades

## Architecture
Shopify Jarvis is an autonomous revenue recovery and merchant assistant platform built on FastAPI (backend), PostgreSQL (persistence), and React/Vite (frontend).

### Data Flow & Component Interaction
```
Shopify Store (Webhooks / REST API)
       │
       ▼
ShopifyClient (shopify_api.py) ──> extracts enriched line items, images, fulfillments
       │
       ▼
Drip Cadence Manager (cadence_manager.py) & Post-Delivery Service (post_delivery_service.py)
       │ (State persisted in PostgreSQL: checkout_drip_states, post_delivery_automations)
       ├─────────────────────────────────┬────────────────────────────────┐
       ▼                                 ▼                                ▼
EmailDispatcher (email_dispatcher.py)  WhatsAppDispatcher             MobileNotifier (mobile_notifier.py)
  [Luxury Responsive HTML Showcase]      [Twilio / Meta / wa.me]        [Telegram Bot / Discord Webhook]
```

---

## Feature Inventory
Every feature from the Survey phase appears here with its assigned milestone. No feature is left unassigned.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Product Visual Showcase in Emails | Extract complete line item details & images from Shopify checkouts; embed in responsive luxury HTML email template; support multi-language labels. | M1 | Survey 1 |
| 2 | Smart 3-Step Drip Recovery Cadence | Implement 3-stage state machine (Stage 1: 30m no discount; Stage 2: 4h MG10 discount; Stage 3: 24h urgency); auto-cancel on order conversion. | M1 | Survey 2 |
| 3 | Autonomous WhatsApp Dispatcher | Support Twilio WhatsApp API, Meta Cloud API, and canonical 1-click `wa.me` fallback; resolve multi-tenancy settings storage. | M2 | Survey 3 |
| 4 | Instant Mobile Notifications | Real-time merchant alerts via Telegram Bot API and Discord Webhooks for abandoned checkouts, recovered orders, and VIP events. | M2 | Survey 3 |
| 5 | Post-Delivery VIP Review & Upsell Automation | Capture order fulfillments; schedule 5-day post-fulfillment VIP review sequence with `MGVIP15` discount code via Email & WhatsApp. | M3 | Survey 2 |
| 6 | Database Schema & Settings Persistence | Schemas for drip states, post-delivery queue, and store settings for WhatsApp/Telegram/Discord credentials. | M1, M2, M3 | Survey 1, 2, 3 |
| 7 | Full E2E Integration & Adversarial Hardening | Verify 100% pass of E2E test suite (Tiers 1-4) and execute Tier 5 adversarial coverage hardening. | M4 | Dual Track |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Core Checkout Recovery & Visual Email Engine | Features 1 & 2: Line items & image extraction, luxury HTML email showcase, `checkout_drip_states` schema, 30m/4h/24h cadence, MG10 discount logic. | none | **DONE** |
| 2 | Multi-Channel Messaging: WhatsApp & Mobile Alerts | Features 3 & 5: Multi-tenant `shop_settings` columns, Twilio/Meta/wa.me WhatsApp dispatcher, Telegram Bot API & Discord Webhook alerts. | M1 | **DONE** |
| 3 | Post-Delivery VIP Review & Upsell Automation | Feature 4: Ingest fulfillments, 5-day delay queue `post_delivery_automations`, `MGVIP15` discount, AI review copy & multi-channel dispatch. | M1, M2 | PLANNED |
| 4 | Full E2E Integration & Adversarial Hardening | Phase 1: Pass 100% E2E test suite (Tiers 1-4); Phase 2: Challenger-driven adversarial coverage hardening (Tier 5). | M1, M2, M3, E2E | PLANNED |

---

## Interface Contracts

### 1. Database Schema (`backend/database.py`)
- Tables and Columns:
  - `shop_settings` extended with:
    - `whatsapp_provider` VARCHAR(32) DEFAULT 'auto'
    - `whatsapp_api_token` TEXT, `whatsapp_phone_number_id` VARCHAR(64)
    - `twilio_account_sid` VARCHAR(64), `twilio_auth_token` VARCHAR(64), `twilio_whatsapp_number` VARCHAR(64)
    - `whatsapp_webhook_url` TEXT
    - `telegram_bot_token` VARCHAR(128), `telegram_chat_id` VARCHAR(64), `notify_telegram` BOOLEAN DEFAULT FALSE
    - `discord_webhook_url` TEXT, `notify_discord` BOOLEAN DEFAULT FALSE
  - `checkout_drip_states`:
    - `id`, `shop_domain`, `checkout_id` (UNIQUE), `email`, `phone`, `customer_name`, `checkout_url`, `total_price`, `currency`, `items` (JSONB), `created_at`, `current_stage` (0,1,2,3), `stage_1_sent_at`, `stage_2_sent_at`, `stage_3_sent_at`, `status` ('active', 'converted', 'exhausted', 'canceled'), `updated_at`
  - `post_delivery_automations`:
    - `id`, `shop_domain`, `order_id` (UNIQUE), `order_number`, `customer_email`, `customer_phone`, `customer_name`, `fulfilled_at`, `scheduled_for`, `items_summary` (JSONB), `status` ('pending', 'sent', 'canceled'), `sent_at`, `discount_code` ('MGVIP15'), `created_at`

### 2. Line Items & Email Showcase (`backend/shopify_api.py` & `backend/email_dispatcher.py`) [IMPLEMENTED & VERIFIED]
- `ShopifyClient.get_abandoned_checkouts_detailed(created_at_min=None, limit=50) -> List[Dict]`:
  - Returns checkouts with enriched `line_items`:
    `[{ "title": str, "variant_title": str, "quantity": int, "price": str, "image_url": Optional[str] }]`
  - Raw `checkout_url` preserved without premature discount injection.
- `EmailDispatcher.build_html_email(...) -> str`:
  - Table-based luxury responsive email with MSO conditional tags and VML bulletproof buttons.
  - Complete `html.escape()` sanitization preventing XSS injection.
  - Itemized showcase with 90x90 thumbnails, titles, variants, quantities, and prices.
  - Cadence-aware discount card (conditionally rendered only when `discount_code` is passed; omitted for Stage 1).
  - 6-language dictionary (`ro`, `it`, `es`, `de`, `fr`, `en`).

### 3. Drip Cadence Manager (`backend/cadence_manager.py`) [IMPLEMENTED & VERIFIED]
- `DripCadenceManager`:
  - `evaluate_drip_stage(checkout_dict, state_record, now_dt) -> Optional[int]`:
    - Age < 30m: None
    - Age >= 30m and current_stage == 0: Return Stage 1 (no discount)
    - Age >= 4h and current_stage == 1 and elapsed >= 3.5h: Return Stage 2 (code MG10)
    - Age >= 24h and current_stage == 2 and elapsed >= 18h: Return Stage 3 (code MG10, urgency)
    - Age > 72h or current_stage == 3: Return None (mark exhausted)
  - `mark_order_converted(shop: str, order_dict: Dict) -> bool`:
    - Matches order by checkout_id or customer email. Marks state as `'converted'`, cancels subsequent stages.

### 4. Autonomous WhatsApp Dispatcher (`backend/whatsapp_dispatcher.py`) [IMPLEMENTED & VERIFIED]
- `WhatsAppDispatcher`:
  - `send_message(phone: str, message: str, settings: Optional[Dict] = None) -> Dict`:
    - Uses store-specific credentials from `settings` (or DB lookup).
    - If `whatsapp_provider == 'meta'`: sends via Meta Cloud API.
    - If `whatsapp_provider == 'twilio'`: sends via Twilio API.
    - If `whatsapp_provider == 'auto'`: tries Meta -> Twilio -> Webhook -> wa.me fallback link.
    - Returns `{"ok": bool, "status": str, "wa_me_url": str, ...}`.
  - `generate_wa_me_link(phone: str, message: str) -> str`:
    - Returns canonical `https://wa.me/{clean_phone}?text={quote(message)}`.

### 5. Post-Delivery VIP Service (`backend/post_delivery_service.py`)
- `PostDeliveryService`:
  - `sync_fulfilled_orders(shop: str, days_back: int = 14) -> int`:
    - Captures fulfilled orders from Shopify API, parses `fulfillments.created_at`, enqueues in `post_delivery_automations` with `scheduled_for = fulfilled_at + 5 days`.
  - `process_due_vip_automations(shop: str, settings: Dict) -> int`:
    - Dispatches due VIP review & upsell requests with `MGVIP15` discount code via email & WhatsApp.

### 6. Mobile Notifier (`backend/mobile_notifier.py`) [IMPLEMENTED & VERIFIED]
- `MobileNotifier`:
  - `async notify_merchant(event_type: str, data: Dict, settings: Dict) -> Dict`:
    - Supported events: `abandoned_cart`, `recovery_converted`, `vip_upsell_sent`.
    - Channels: Telegram Bot API (HTML formatted), Discord Webhook (Rich Embeds with color coding).

---

## Code Layout
- `backend/database.py` — Database schema, connection, and query functions.
- `backend/shopify_api.py` — Shopify Admin REST API client.
- `backend/email_dispatcher.py` — HTML email template builder and sender.
- `backend/cadence_manager.py` — 3-step drip recovery state machine and timing logic.
- `backend/whatsapp_dispatcher.py` — Multi-tenant WhatsApp dispatcher (Meta, Twilio, wa.me).
- `backend/post_delivery_service.py` — Order fulfillment tracking and 5-day VIP review queue.
- `backend/mobile_notifier.py` — Telegram & Discord merchant notifications.
- `backend/ai_advisor.py` — AI copy generation (Gemini) with multi-language fallbacks.
- `backend/main.py` — FastAPI application routes and background daemon loops.
- `tests/` — Comprehensive test suites (Unit, Integration, and E2E).
