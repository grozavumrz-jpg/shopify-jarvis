import httpx
from typing import Dict, Any, List


class ShopifyClient:
    """Thin async wrapper around Shopify Admin REST API."""

    def __init__(self, shop: str, token: str):
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
            r.raise_for_status()
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
        revenue_30d = sum(float(o["total_price"]) for o in orders)
        revenue_today = sum(float(o["total_price"]) for o in today_orders)

        # Top products from orders
        product_sales: Dict[str, int] = {}
        for order in orders:
            for item in order.get("line_items", []):
                name = item.get("title", "Unknown")
                product_sales[name] = product_sales.get(name, 0) + item.get("quantity", 1)
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "shop_name":        shop_info.get("name", "Magazinul tău"),
            "orders_30d":       len(orders),
            "orders_today":     len(today_orders),
            "revenue_30d":      round(revenue_30d, 2),
            "revenue_today":    round(revenue_today, 2),
            "abandoned_carts":  len(abandoned),
            "low_stock_items":  low_stock,
            "new_customers_24h": new_customers,
            "top_products":     [{"name": p[0], "units": p[1]} for p in top_products],
            "currency":         shop_info.get("currency", "USD"),
        }
