import httpx
from typing import Dict, Any, List


def detect_customer_language_and_country(c_name: str, email: str, phone: str, country_code: str, country_name: str) -> dict:
    cc = (country_code or "").upper().strip()
    
    COUNTRY_MAP = {
        "IT": {"lang": "it", "country": "Italia", "flag": "🇮🇹", "lang_name": "Italiană (Italiano)"},
        "ES": {"lang": "es", "country": "Spania", "flag": "🇪🇸", "lang_name": "Spaniolă (Español)"},
        "MX": {"lang": "es", "country": "Mexic", "flag": "🇲🇽", "lang_name": "Spaniolă (Español)"},
        "AR": {"lang": "es", "country": "Argentina", "flag": "🇦🇷", "lang_name": "Spaniolă (Español)"},
        "CO": {"lang": "es", "country": "Columbia", "flag": "🇨🇴", "lang_name": "Spaniolă (Español)"},
        "CL": {"lang": "es", "country": "Chile", "flag": "🇨🇱", "lang_name": "Spaniolă (Español)"},
        "DE": {"lang": "de", "country": "Germania", "flag": "🇩🇪", "lang_name": "Germană (Deutsch)"},
        "AT": {"lang": "de", "country": "Austria", "flag": "🇦🇹", "lang_name": "Germană (Deutsch)"},
        "CH": {"lang": "de", "country": "Elveția", "flag": "🇨🇭", "lang_name": "Germană (Deutsch)"},
        "FR": {"lang": "fr", "country": "Franța", "flag": "🇫🇷", "lang_name": "Franceză (Français)"},
        "BE": {"lang": "fr", "country": "Belgia", "flag": "🇧🇪", "lang_name": "Franceză (Français)"},
        "RO": {"lang": "ro", "country": "România", "flag": "🇷🇴", "lang_name": "Română"},
        "MD": {"lang": "ro", "country": "Moldova", "flag": "🇲🇩", "lang_name": "Română"},
        "GB": {"lang": "en", "country": "Regatul Unit", "flag": "🇬🇧", "lang_name": "Engleză (English)"},
        "US": {"lang": "en", "country": "Statele Unite", "flag": "🇺🇸", "lang_name": "Engleză (English)"},
        "CA": {"lang": "en", "country": "Canada", "flag": "🇨🇦", "lang_name": "Engleză (English)"},
        "AU": {"lang": "en", "country": "Australia", "flag": "🇦🇺", "lang_name": "Engleză (English)"},
        "NL": {"lang": "nl", "country": "Olanda", "flag": "🇳🇱", "lang_name": "Olandeză (Nederlands)"},
        "PT": {"lang": "pt", "country": "Portugalia", "flag": "🇵🇹", "lang_name": "Portugheză (Português)"},
        "BR": {"lang": "pt", "country": "Brazilia", "flag": "🇧🇷", "lang_name": "Portugheză (Português)"},
    }

    if cc in COUNTRY_MAP:
        return COUNTRY_MAP[cc]

    clean_p = (phone or "").replace(" ", "").replace("-", "")
    if clean_p.startswith("+39") or clean_p.startswith("0039"):
        return COUNTRY_MAP["IT"]
    if clean_p.startswith("+34") or clean_p.startswith("0034"):
        return COUNTRY_MAP["ES"]
    if clean_p.startswith("+49") or clean_p.startswith("0049"):
        return COUNTRY_MAP["DE"]
    if clean_p.startswith("+33") or clean_p.startswith("0033"):
        return COUNTRY_MAP["FR"]
    if clean_p.startswith("+40") or clean_p.startswith("0040"):
        return COUNTRY_MAP["RO"]

    em = (email or "").lower()
    if em.endswith(".it"):
        return COUNTRY_MAP["IT"]
    if em.endswith(".es"):
        return COUNTRY_MAP["ES"]
    if em.endswith(".de") or em.endswith(".at"):
        return COUNTRY_MAP["DE"]
    if em.endswith(".fr"):
        return COUNTRY_MAP["FR"]
    if em.endswith(".ro"):
        return COUNTRY_MAP["RO"]

    nm = (c_name or "").lower()
    if any(k in nm for k in ["lorenzo", "bianchi", "rossi", "marco", "giovanni", "matteo", "luca", "francesco", "esposito", "ricci", "bruno"]):
        return COUNTRY_MAP["IT"]
    if any(k in nm for k in ["gomez", "gómez", "francisco", "rodriguez", "garcia", "garcía", "martinez", "martínez", "lopez", "gonzalez", "carlos", "javier"]):
        return COUNTRY_MAP["ES"]
    if any(k in nm for k in ["egger", "müller", "schmidt", "schneider", "fischer", "weber", "meyer", "wagner", "becker", "schulz", "emilia", "lukas"]):
        return COUNTRY_MAP["DE"]
    if any(k in nm for k in ["constantinescu", "popescu", "ionescu", "radu", "andrei", "stefan", "marius", "gheorghe", "florin", "alexandru", "grozavu"]):
        return COUNTRY_MAP["RO"]
    if any(k in nm for k in ["martin", "bernard", "dubois", "thomas", "robert", "richard", "petit", "durand", "fatima"]):
        return COUNTRY_MAP["ES"]

    return {"lang": "en", "country": country_name or "Internațional", "flag": "🌍", "lang_name": "Engleză (English)"}


class ShopifyClient:
    """Async wrapper around Shopify Admin REST and GraphQL APIs."""

    def __init__(self, shop: str, token: str):
        self.shop = shop
        self.base = f"https://{shop}/admin/api/2024-01"
        self.headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> Dict:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{self.base}{path}",
                headers=self.headers,
                params=params or {},
            )
            if r.status_code != 200:
                print(f"[Shopify API Error] {r.status_code} on {path}: {r.text}")
                from fastapi import HTTPException
                raise HTTPException(status_code=r.status_code, detail=f"Shopify {r.status_code}: {r.text[:200]}")
            return r.json()

    # ── Store info ────────────────────────────────────────────────────────────

    async def get_shop_info(self) -> Dict:
        data = await self._get("/shop.json")
        return data.get("shop", {})

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_recent_orders(self, days: int = 30) -> List[Dict]:
        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        data = await self._get("/orders.json", {
            "status":          "any",
            "created_at_min":  since,
            "limit":           250,
            "fields":          "id,created_at,total_price,financial_status,fulfillment_status,line_items,customer",
        })
        return data.get("orders", [])

    async def get_abandoned_checkouts(self) -> List[Dict]:
        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        data = await self._get("/checkouts.json", {
            "created_at_min": since,
            "limit":          50,
        })
        return data.get("checkouts", [])

    async def get_abandoned_checkouts_detailed(self) -> List[Dict]:
        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=14)).isoformat() + "Z"
        data = await self._get("/checkouts.json", {
            "created_at_min": since,
            "limit":          50,
        })
        checkouts = data.get("checkouts", [])
        detailed = []
        for c in checkouts:
            cust = c.get("customer") or {}
            first = cust.get("first_name", "") or ""
            last = cust.get("last_name", "") or ""
            c_name = f"{first} {last}".strip()
            bill = c.get("billing_address") or {}
            ship = c.get("shipping_address") or {}
            if not c_name:
                c_name = f"{bill.get('first_name', '')} {bill.get('last_name', '')}".strip() or "Client"

            email = c.get("email") or cust.get("email") or ""
            items = [item.get("title") for item in c.get("line_items", []) if item.get("title")]

            country_code = ship.get("country_code") or bill.get("country_code") or c.get("country_code") or ""
            country_name = ship.get("country") or bill.get("country") or ""
            phone = c.get("phone") or bill.get("phone") or ship.get("phone") or ""

            geo = detect_customer_language_and_country(c_name, email, phone, country_code, country_name)

            raw_url = c.get("abandoned_checkout_url") or ""
            if raw_url and "discount=" not in raw_url:
                delimiter = "&" if "?" in raw_url else "?"
                checkout_link = f"{raw_url}{delimiter}discount=MG10"
            else:
                checkout_link = raw_url

            detailed.append({
                "id": str(c.get("id")),
                "token": c.get("token") or "",
                "email": email,
                "customer_name": c_name,
                "total_price": float(c.get("total_price") or 0.0),
                "currency": c.get("currency") or "EUR",
                "items": items or ["Produse din coș"],
                "checkout_url": checkout_link,
                "created_at": c.get("created_at") or "",
                "phone": phone,
                "clean_phone": "".join(ch for ch in phone if ch.isdigit()),
                "has_phone": bool(phone and len("".join(ch for ch in phone if ch.isdigit())) >= 8),
                "detected_lang": geo["lang"],
                "detected_lang_name": geo["lang_name"],
                "detected_country": geo["country"],
                "detected_flag": geo["flag"],
            })
        return detailed

    async def send_recovery_email(self, checkout_id: str) -> bool:
        """Trigger Shopify's native abandoned checkout recovery email if supported."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.base}/checkouts/{checkout_id}/recovery_email.json",
                    headers=self.headers,
                    json={}
                )
                return r.status_code in (200, 201)
        except Exception:
            return False

    # ── Products ──────────────────────────────────────────────────────────────

    async def get_products(self, limit: int = 50) -> List[Dict]:
        data = await self._get("/products.json", {
            "limit":  limit,
            "fields": "id,title,status,variants,images",
        })
        return data.get("products", [])

    async def get_low_stock_products(self, threshold: int = 5) -> List[Dict]:
        products = await self.get_products(250)
        low = []
        for p in products:
            for v in p.get("variants", []):
                qty = v.get("inventory_quantity", 0)
                if 0 <= qty <= threshold:
                    low.append({
                        "product": p["title"],
                        "variant": v.get("title", ""),
                        "qty":     qty,
                    })
        return low

    # ── Customers ─────────────────────────────────────────────────────────────

    async def get_customers_count(self) -> int:
        data = await self._get("/customers/count.json")
        return data.get("count", 0)

    async def get_new_customers_today(self) -> int:
        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        data = await self._get("/customers/count.json", {
            "created_at_min": since,
        })
        return data.get("count", 0)

    # ── Summary snapshot ──────────────────────────────────────────────────────

    async def get_store_snapshot(self) -> Dict[str, Any]:
        """Fetch all relevant data in one call for AI analysis."""
        orders   = await self.get_recent_orders(30)
        today_orders = await self.get_recent_orders(1)
        abandoned = await self.get_abandoned_checkouts()
        low_stock = await self.get_low_stock_products(5)
        new_customers = await self.get_new_customers_today()
        shop_info = await self.get_shop_info()

        # Revenue calc
        revenue_30d = sum(float(o.get("total_price", 0)) for o in orders)
        revenue_today = sum(float(o.get("total_price", 0)) for o in today_orders)
        aov = round(revenue_30d / len(orders), 2) if len(orders) > 0 else 0.0

        # Customer Intelligence & Segmentation
        customer_map: Dict[str, Dict[str, Any]] = {}
        for order in orders:
            cust = order.get("customer")
            if cust:
                cid = str(cust.get("id") or cust.get("email") or "guest")
                first = cust.get("first_name") or ""
                last = cust.get("last_name") or ""
                full_name = f"{first} {last}".strip() or "Client"
                if cid not in customer_map:
                    customer_map[cid] = {
                        "name": full_name,
                        "email": cust.get("email", ""),
                        "orders_count": 0,
                        "total_spent": 0.0,
                    }
                customer_map[cid]["orders_count"] += 1
                customer_map[cid]["total_spent"] += float(order.get("total_price", 0))

        total_unique = len(customer_map)
        repeat_count = sum(1 for c in customer_map.values() if c["orders_count"] > 1)
        returning_rate = round((repeat_count / total_unique * 100), 1) if total_unique > 0 else 0.0
        vip_customers = sorted(customer_map.values(), key=lambda x: x["total_spent"], reverse=True)[:3]

        # Top products from orders
        product_sales: Dict[str, int] = {}
        for order in orders:
            for item in order.get("line_items", []):
                name = item.get("title", "Unknown")
                product_sales[name] = product_sales.get(name, 0) + item.get("quantity", 1)
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "shop_name":              shop_info.get("name", "Magazinul tău"),
            "orders_30d":             len(orders),
            "orders_today":           len(today_orders),
            "revenue_30d":            round(revenue_30d, 2),
            "revenue_today":          round(revenue_today, 2),
            "aov":                    aov,
            "abandoned_carts":        len(abandoned),
            "low_stock_items":        low_stock,
            "new_customers_24h":       new_customers,
            "total_unique_customers": total_unique,
            "repeat_customers":       repeat_count,
            "returning_rate":         returning_rate,
            "vip_customers":          vip_customers,
            "top_products":           [{"name": p[0], "units": p[1]} for p in top_products],
            "currency":               shop_info.get("currency", "USD"),
        }

    # ── GraphQL Billing API ───────────────────────────────────────────────────

    async def _graphql(self, query: str, variables: dict = None) -> Dict:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://{self.shop}/admin/api/2024-01/graphql.json",
                headers=self.headers,
                json={"query": query, "variables": variables or {}}
            )
            r.raise_for_status()
            return r.json()

    async def create_app_subscription(self, return_url: str, test: bool = True) -> str:
        """Create a recurring Shopify app subscription for $9.99/mo with 7 days trial."""
        mutation = """
        mutation AppSubscriptionCreate(
          $name: String!
          $returnUrl: URL!
          $trialDays: Int
          $test: Boolean
          $price: Decimal!
        ) {
          appSubscriptionCreate(
            name: $name
            returnUrl: $returnUrl
            trialDays: $trialDays
            test: $test
            lineItems: [
              {
                plan: {
                  appRecurringPricingDetails: {
                    price: { amount: $price, currencyCode: USD }
                    interval: EVERY_30_DAYS
                  }
                }
              }
            ]
          ) {
            appSubscription {
              id
              status
            }
            confirmationUrl
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "name": "Jarvis Autonomous Pro",
            "returnUrl": return_url,
            "trialDays": 7,
            "test": test,
            "price": 9.99
        }
        res = await self._graphql(mutation, variables)
        data = res.get("data", {}).get("appSubscriptionCreate", {})
        errors = data.get("userErrors", [])
        if errors:
            raise Exception(f"Billing Error: {errors[0].get('message')}")
        return data.get("confirmationUrl")

