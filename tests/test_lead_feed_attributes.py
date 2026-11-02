"""Google Merchant apparel attributes inferred from the real Grozavu catalogue patterns."""

try:
    from tests import _test_env  # noqa: F401  (isolated SQLite file per test run)
except ImportError:  # pragma: no cover
    import _test_env  # noqa: F401
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from google_merchant_feed import build_feed_items  # noqa: E402


def product(title, tags="", ptype="Hoodie", options=None, variants=None):
    return {
        "id": 1, "title": title, "handle": "h", "status": "active", "published_at": "2026-10-01T00:00:00Z",
        "product_type": ptype, "tags": tags, "options": options or [{"name": "Size", "position": 1}],
        "images": [{"id": 1, "src": "https://cdn.shopify.com/x.jpg"}],
        "variants": variants or [{"id": 11, "price": "79.00", "option1": "M"}, {"id": 12, "price": "79.00", "option1": "L"}],
    }


def first_item(p):
    items, _ = build_feed_items([p], shop_domain="maisongrozavu.com", brand="Grozavu")
    return items[0]


class TestFeedApparelAttributes(unittest.TestCase):
    def test_tags_for_both_genders_mean_unisex(self):
        item = first_item(product("Heritage Tartan Hoodie — Bordeaux", tags="all men tops, women hoodies, christmas"))
        self.assertEqual(item["gender"], "unisex")

    def test_title_gender_wins_over_tags(self):
        item = first_item(product("Women's Wide-Leg Pants", tags="men, women, pants", ptype="Pants"))
        self.assertEqual(item["gender"], "female")
        item = first_item(product("Men's Wide Collar Tee", tags="women tees", ptype="T-Shirt"))
        self.assertEqual(item["gender"], "male")

    def test_kids_products_get_kids_age_group(self):
        self.assertEqual(first_item(product("Kids Organic Tee", ptype="T-Shirt"))["age_group"], "kids")
        self.assertEqual(first_item(product("Oversized Heavyweight Crewneck"))["age_group"], "adult")

    def test_colour_only_from_a_pure_colour_suffix(self):
        self.assertEqual(first_item(product("Hare Argyle Sweatshirt — Cocoa"))["color"], "Cocoa")
        self.assertEqual(first_item(product("Logo Crewneck — Black"))["color"], "Black")
        # A graphic colour is not the garment colour -> leave it out rather than guess
        self.assertNotIn("color", first_item(product("SS26 Wide-Leg Pants — Deep Red Mark", ptype="Pants")))
        self.assertNotIn("color", first_item(product("Gold Hare Half-Zip")))

    def test_colour_option_still_wins(self):
        p = product("Oversized Organic Tee", ptype="T-Shirt",
                    options=[{"name": "Color", "position": 1}, {"name": "Size", "position": 2}],
                    variants=[{"id": 21, "price": "45", "option1": "French Navy", "option2": "S"},
                              {"id": 22, "price": "45", "option1": "Black", "option2": "S"}])
        items, _ = build_feed_items([p], shop_domain="maisongrozavu.com", brand="Grozavu")
        self.assertEqual({i["color"] for i in items}, {"French Navy", "Black"})
        self.assertEqual(items[0]["title"], "Oversized Organic Tee - French Navy / S")


if __name__ == "__main__":
    unittest.main()
