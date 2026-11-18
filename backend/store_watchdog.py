"""
backend/store_watchdog.py
Dedicated 24/7 Store Watchdog & Auto-Repair Agent ("Gardian 24/7").

Continuously audits the Shopify store, storefront uptime, Google Merchant feed,
catalog conversion blockers, brand discount codes, email DNS deliverability, and
backend health — automatically fixing safe issues and reporting anything that
needs the owner's attention with exact product names and Romanian action steps.
"""

import re
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

try:
    from google_merchant_feed import build_feed_items, build_google_merchant_xml, validate_google_merchant_feed
except ImportError:
    from backend.google_merchant_feed import build_feed_items, build_google_merchant_xml, validate_google_merchant_feed

try:
    from seo_optimizer import contains_forbidden, _strip_html
except ImportError:
    from backend.seo_optimizer import contains_forbidden, _strip_html


ALERT_COOLDOWN_SECONDS = 6 * 3600
DNS_AUDIT_CACHE_SECONDS = 6 * 3600
STOREFRONT_SLOW_MS = 4000


class StoreWatchdogAgent:
    """Continuous 24/7 Store Health, Conversion-Blocker & Auto-Repair Agent."""

    def __init__(self, brand_domain: str = "maisongrozavu.com", brand_name: str = "Grozavu"):
        self.brand_domain = brand_domain
        self.brand_name = brand_name
        self._last_dns_at: float = 0.0
        self._last_dns_result: Optional[Dict[str, Any]] = None
        self._alerted_codes: Dict[str, float] = {}
        self._lock: Optional[asyncio.Lock] = None
        self.state: Dict[str, Any] = {
            "agent_name": "Gardian 24/7",
            "is_running": False,
            "scans_completed": 0,
            "last_scan_at": None,
            "last_duration_ms": 0,
            "health_score": None,
            "status": "starting",
            "auto_fixed": [],
            "critical_issues": [],
            "warnings": [],
            "passed_checks": [],
            "recent_history": [],
            "storefront": None,
            "dns_score": None,
            "feed_summary": None,
            "catalog_summary": None,
            "discounts_summary": None,
        }

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _check_storefront(self) -> Dict[str, Any]:
        url = f"https://{self.brand_domain}"
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(url)
            ms = int((time.perf_counter() - t0) * 1000)
            return {
                "url": url,
                "reachable": r.status_code < 400,
                "status_code": r.status_code,
                "latency_ms": ms,
                "error": None if r.status_code < 400 else f"HTTP {r.status_code}",
            }
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            return {
                "url": url,
                "reachable": False,
                "status_code": None,
                "latency_ms": ms,
                "error": str(e)[:160],
            }

    @staticmethod
    def audit_catalog_blockers(products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Scan real active Shopify products for conversion killers and traffic losses."""
        active = [p for p in (products or []) if isinstance(p, dict) and str(p.get("status") or "active").lower() == "active"]
        missing_images: List[str] = []
        short_descriptions: List[str] = []
        missing_alt_products: List[str] = []
        forbidden_copy: List[str] = []
        zero_price: List[str] = []
        out_of_stock_tracked: List[str] = []

        for p in active:
            title = str(p.get("title") or f"ID {p.get('id')}").strip()
            images = [i for i in (p.get("images") or []) if isinstance(i, dict) and i.get("src")]
            if not images and not (isinstance(p.get("image"), dict) and p["image"].get("src")):
                missing_images.append(title)
            elif any(not (img.get("alt") or "").strip() for img in images):
                missing_alt_products.append(title)

            body_clean = _strip_html(str(p.get("body_html") or ""))
            if len(body_clean) < 40:
                short_descriptions.append(title)

            bad = contains_forbidden(f"{title} {body_clean}")
            if bad:
                forbidden_copy.append(f"{title} ({', '.join(bad)})")

            variants = [v for v in (p.get("variants") or []) if isinstance(v, dict)]
            has_valid_price = False
            for v in variants:
                try:
                    pr = float(v.get("price") or 0)
                    if pr > 0:
                        has_valid_price = True
                except (TypeError, ValueError):
                    pass
                if str(v.get("inventory_management") or "").lower() == "shopify":
                    try:
                        qty = int(v.get("inventory_quantity") or 0)
                    except (TypeError, ValueError):
                        qty = 0
                    if qty <= 0 and str(v.get("inventory_policy") or "deny").lower() != "continue":
                        out_of_stock_tracked.append(f"{title} ({v.get('title') or 'variantă'})")
            if not has_valid_price:
                zero_price.append(title)

        return {
            "active_products": len(active),
            "missing_images": missing_images,
            "short_descriptions": short_descriptions,
            "missing_alt_products": missing_alt_products,
            "forbidden_copy": forbidden_copy,
            "zero_price": zero_price,
            "out_of_stock_tracked": out_of_stock_tracked,
        }

    async def run_deep_scan(
        self,
        shop: str,
        shopify_client: Any = None,
        products: Optional[List[Dict[str, Any]]] = None,
        deliverability_checker: Any = None,
        self_heal_fn: Optional[Callable] = None,
        mobile_notifier: Any = None,
        shop_settings: Optional[Dict[str, Any]] = None,
        ephemeral_db_blocked: bool = False,
        check_storefront: bool = True,
        check_dns: bool = True,
        auto_fix_discounts: bool = True,
        currency: str = "EUR",
    ) -> Dict[str, Any]:
        """Run a full 7-point autonomous audit + safe auto-repair pass. Never raises."""
        async with self._get_lock():
            t0 = time.perf_counter()
            now_iso = datetime.now(timezone.utc).isoformat()
            now_ts = time.time()

            critical: List[Dict[str, Any]] = []
            warnings: List[Dict[str, Any]] = []
            passed: List[Dict[str, Any]] = []
            auto_fixed: List[Dict[str, Any]] = []

            # 1. Self-heal backend (expired locks, DB, Shopify connection)
            if callable(self_heal_fn):
                try:
                    heal_res = await self_heal_fn(shop=shop, force_discounts=False)
                    for act in (heal_res or {}).get("actions") or []:
                        auto_fixed.append({"time": now_iso, "area": "Auto-Reparare", "detail": str(act)})
                except Exception as e:
                    warnings.append({
                        "code": "self_heal_error",
                        "area": "Auto-Reparare",
                        "title": "Avertisment în auto-reparare",
                        "detail": str(e)[:160],
                        "action_ro": "Verifică jurnalul serverului pe Render.",
                    })

            # 2. Persistent DB guard
            if ephemeral_db_blocked:
                critical.append({
                    "code": "ephemeral_db",
                    "area": "Bază de Date",
                    "title": "Baza de date persistentă (Postgres) lipsește",
                    "detail": "Pe Render baza locală SQLite se șterge la restart; marketingul este pus pe pauză.",
                    "action_ro": "Configurează variabila DATABASE_URL (Neon PostgreSQL) în Render.",
                })
            else:
                passed.append({
                    "area": "Bază de Date",
                    "title": "Bază de date persistentă activă",
                    "detail": "Dezabonările, consimțământul și istoricul clienților sunt protejate permanent.",
                })

            # 3. Shopify connection & products fetch
            loaded_products: Optional[List[Dict[str, Any]]] = products
            if loaded_products is None and shopify_client is not None:
                try:
                    getter = getattr(shopify_client, "get_active_products", None)
                    loaded_products = await (getter() if callable(getter) else shopify_client.get_products(limit=250))
                except Exception as e:
                    critical.append({
                        "code": "shopify_unreachable",
                        "area": "Shopify API",
                        "title": "Nu pot citi produsele din Shopify",
                        "detail": str(getattr(e, "detail", e))[:180],
                        "action_ro": "Verifică conexiunea Shopify și permisiunile aplicației Jarvis.",
                    })
                    loaded_products = None

            if loaded_products is not None:
                passed.append({
                    "area": "Shopify API",
                    "title": f"Conectat live ({len(loaded_products)} produse active)",
                    "detail": f"Catalog sincronizat din {shop}.",
                })
            elif shopify_client is None:
                critical.append({
                    "code": "shopify_not_connected",
                    "area": "Shopify API",
                    "title": "Magazinul Shopify nu este conectat",
                    "detail": "Tokenul de acces Shopify lipsește sau a expirat.",
                    "action_ro": "Deschide aplicația din Shopify Admin sau verifică cheile pe Render.",
                })

            # 4. Brand discount codes (auto-create missing & auto-rename legacy 'Jarvis' titles)
            discounts_summary = None
            if auto_fix_discounts and shopify_client is not None and callable(getattr(shopify_client, "ensure_brand_discount_codes", None)):
                try:
                    d_res = await shopify_client.ensure_brand_discount_codes()
                    discounts_summary = d_res
                    for c in d_res.get("created") or []:
                        auto_fixed.append({"time": now_iso, "area": "Coduri Reducere", "detail": f"Creat automat codul {c} în Shopify"})
                    for c in d_res.get("renamed") or []:
                        auto_fixed.append({"time": now_iso, "area": "Coduri Reducere", "detail": f"Redenumit automat codul {c} (eliminat numele vechi 'Jarvis')"})
                    if d_res.get("errors"):
                        warnings.append({
                            "code": "discount_sync_warning",
                            "area": "Coduri Reducere",
                            "title": "Unele coduri de reducere nu au putut fi verificate/create",
                            "detail": "; ".join(d_res["errors"])[:240],
                            "action_ro": "Verifică dacă permisiunea write_discounts este activă pe versiunea curentă a aplicației.",
                        })
                    else:
                        active_codes = sorted(set((d_res.get("existing") or []) + (d_res.get("created") or [])))
                        passed.append({
                            "area": "Coduri Reducere",
                            "title": f"Toate cele {len(active_codes)} coduri brand active",
                            "detail": ", ".join(active_codes),
                        })
                except Exception as e:
                    warnings.append({
                        "code": "discount_check_failed",
                        "area": "Coduri Reducere",
                        "title": "Eroare la verificarea codurilor de reducere",
                        "detail": str(e)[:160],
                        "action_ro": "Verifică permisiunile Discounts în Shopify Dev Dashboard.",
                    })

            # 5. Live Storefront uptime & speed check
            sf_res = None
            if check_storefront:
                sf_res = await self._check_storefront()
                if not sf_res["reachable"]:
                    critical.append({
                        "code": "storefront_down",
                        "area": "Site Magazin",
                        "title": f"Magazinul {self.brand_domain} nu răspunde!",
                        "detail": sf_res.get("error") or "Timeout",
                        "action_ro": "Verifică imediat domeniul și setările DNS / Shopify Domains.",
                    })
                elif sf_res["latency_ms"] > STOREFRONT_SLOW_MS:
                    warnings.append({
                        "code": "storefront_slow",
                        "area": "Site Magazin",
                        "title": f"Magazinul se încarcă lent ({sf_res['latency_ms']} ms)",
                        "detail": "Timpul mare de răspuns reduce rata de conversie pe mobil.",
                        "action_ro": "Verifică aplicațiile Shopify sau imaginile necomprimate de pe prima pagină.",
                    })
                else:
                    passed.append({
                        "area": "Site Magazin",
                        "title": f"{self.brand_domain} online ({sf_res['latency_ms']} ms)",
                        "detail": f"HTTP {sf_res['status_code']} — răspuns rapid.",
                    })

            # 6. Google Merchant Feed & Catalog Conversion Blockers
            feed_summary = None
            catalog_summary = None
            if loaded_products is not None:
                items, skipped = build_feed_items(
                    loaded_products, shop_domain=self.brand_domain, brand=self.brand_name, currency=currency
                )
                xml_feed = build_google_merchant_xml(
                    loaded_products, shop_domain=self.brand_domain, store_name=self.brand_name, currency=currency
                )
                val = validate_google_merchant_feed(xml_feed)
                # Map product groups still missing color/size to real human product titles
                missing_color_titles = sorted({
                    str(it.get("title") or "").split(" - ")[0].strip()
                    for it in items if not (it.get("color") or "").strip()
                })
                missing_size_titles = sorted({
                    str(it.get("title") or "").split(" - ")[0].strip()
                    for it in items if not (it.get("size") or "").strip()
                })
                feed_summary = {
                    "valid": val["valid"],
                    "items_count": val["items_count"],
                    "product_groups": val.get("product_groups", 0),
                    "errors_count": len(val["errors"]),
                    "warnings_count": val.get("warnings_count", len(val["warnings"])),
                    "skipped_count": len(skipped),
                    "missing_color_products": missing_color_titles,
                    "missing_size_products": missing_size_titles,
                }
                if not val["valid"] or val["errors"]:
                    critical.append({
                        "code": "google_feed_errors",
                        "area": "Google Shopping Feed",
                        "title": f"{len(val['errors'])} erori critice în feed-ul Google Shopping",
                        "detail": "; ".join(val["errors"][:3]),
                        "action_ro": "Rezolvă produsele fără imagine/preț din Shopify Admin.",
                    })
                else:
                    passed.append({
                        "area": "Google Shopping Feed",
                        "title": f"Feed XML valid: {val['items_count']} variante ({len(val['errors'])} erori)",
                        "detail": "Gata pentru listări gratuite Google Shopping.",
                    })

                if skipped:
                    warnings.append({
                        "code": "feed_skipped_products",
                        "area": "Google Shopping Feed",
                        "title": f"{len(skipped)} produse/variante sărite din feed-ul Google",
                        "detail": ", ".join(f"{s['product']} ({s['reason']})" for s in skipped[:5]),
                        "action_ro": "Adaugă imagine și preț valid produselor active din Shopify ca să intre în Google Shopping.",
                        "affected_items": [f"{s['product']} — {s['reason']}" for s in skipped[:15]],
                    })
                if missing_color_titles:
                    warnings.append({
                        "code": "feed_missing_color",
                        "area": "Google Shopping Feed",
                        "title": f"{len(missing_color_titles)} produse fără culoare detectabilă pentru Google",
                        "detail": "Aceste produse nu menționează culoarea nici în titlu, nici în descriere, nici în numele pozelor.",
                        "action_ro": "Adaugă culoarea reală (ex. 'in black' sau '— Black') în descrierea/titlul acestor produse în Shopify Admin.",
                        "affected_items": missing_color_titles[:20],
                    })
                if missing_size_titles:
                    warnings.append({
                        "code": "feed_missing_size",
                        "area": "Google Shopping Feed",
                        "title": f"{len(missing_size_titles)} produse fără mărime pentru Google",
                        "detail": ", ".join(missing_size_titles[:5]),
                        "action_ro": "Adaugă opțiunea Size în Shopify pentru aceste produse.",
                        "affected_items": missing_size_titles[:20],
                    })

                catalog_summary = self.audit_catalog_blockers(loaded_products)
                if catalog_summary["missing_images"]:
                    critical.append({
                        "code": "products_missing_images",
                        "area": "Catalog Produse",
                        "title": f"{len(catalog_summary['missing_images'])} produse active fără poze",
                        "detail": ", ".join(catalog_summary["missing_images"][:5]),
                        "action_ro": "Adaugă fotografii imediat — un produs fără poză nu convertește și e respins de Google.",
                        "affected_items": catalog_summary["missing_images"][:15],
                    })
                if catalog_summary["zero_price"]:
                    critical.append({
                        "code": "products_zero_price",
                        "area": "Catalog Produse",
                        "title": f"{len(catalog_summary['zero_price'])} produse active cu preț 0",
                        "detail": ", ".join(catalog_summary["zero_price"][:5]),
                        "action_ro": "Setează prețul corect în Shopify Admin.",
                        "affected_items": catalog_summary["zero_price"][:15],
                    })
                if catalog_summary["forbidden_copy"]:
                    warnings.append({
                        "code": "forbidden_brand_terms",
                        "area": "Reguli Brand",
                        "title": f"{len(catalog_summary['forbidden_copy'])} produse conțin termeni interziși de brand",
                        "detail": ", ".join(catalog_summary["forbidden_copy"][:5]),
                        "action_ro": "Elimină cuvintele neconforme (ex. 'unisex') din titlu/descriere.",
                        "affected_items": catalog_summary["forbidden_copy"][:15],
                    })
                if catalog_summary["short_descriptions"]:
                    warnings.append({
                        "code": "short_descriptions",
                        "area": "Conversie & SEO",
                        "title": f"{len(catalog_summary['short_descriptions'])} produse cu descriere prea scurtă (< 40 caractere)",
                        "detail": ", ".join(catalog_summary["short_descriptions"][:5]),
                        "action_ro": "Adaugă materialul, gramajul și croiala reală — crește conversia și traficul Google.",
                        "affected_items": catalog_summary["short_descriptions"][:15],
                    })
                if catalog_summary["missing_alt_products"]:
                    warnings.append({
                        "code": "missing_image_alt",
                        "area": "Google Images & SEO",
                        "title": f"{len(catalog_summary['missing_alt_products'])} produse au imagini fără text ALT",
                        "detail": "Imaginile fără ALT pierd trafic gratuit din Google Images.",
                        "action_ro": "Deschide tabul Radar → Audit SEO și copiază textele ALT propuse în Shopify.",
                        "affected_items": catalog_summary["missing_alt_products"][:15],
                    })

            # 7. DNS Email Deliverability Watch (cached 6h)
            dns_score = None
            if check_dns and deliverability_checker is not None:
                if self._last_dns_result is None or (now_ts - self._last_dns_at) >= DNS_AUDIT_CACHE_SECONDS:
                    try:
                        self._last_dns_result = await deliverability_checker.audit_domain(self.brand_domain)
                        self._last_dns_at = now_ts
                    except Exception:
                        pass
                if isinstance(self._last_dns_result, dict):
                    dns_score = self._last_dns_result.get("score")
                    if dns_score is not None and dns_score < 100:
                        critical.append({
                            "code": "dns_deliverability_degraded",
                            "area": "Anti-Spam & Email DNS",
                            "title": f"Scor DNS scăzut: {dns_score}/100 pe {self.brand_domain}",
                            "detail": str(self._last_dns_result.get("rating") or "Înregistrări DNS incomplete"),
                            "action_ro": "Verifică tabul Livrabilitate & Anti-Spam pentru înregistrările SPF/DKIM/DMARC lipsă.",
                        })
                    elif dns_score == 100:
                        passed.append({
                            "area": "Anti-Spam & Email DNS",
                            "title": f"Autentificare email 100/100 ({self.brand_domain})",
                            "detail": "SPF, DKIM și DMARC valide — reputație protejată.",
                        })

            # Compute honest health score from verified checks only
            score = 100
            score -= len(critical) * 20
            score -= min(30, len(warnings) * 5)
            score = max(0, min(100, score))
            status = "critical" if critical else ("warnings" if warnings else "healthy")
            duration_ms = int((time.perf_counter() - t0) * 1000)

            # Notify merchant via Telegram/Discord on NEW critical issues (cooldown 6h per code)
            if critical and mobile_notifier is not None and shop_settings:
                new_crits = [
                    c for c in critical
                    if now_ts - self._alerted_codes.get(c["code"], 0.0) >= ALERT_COOLDOWN_SECONDS
                ]
                if new_crits:
                    for c in new_crits:
                        self._alerted_codes[c["code"]] = now_ts
                    try:
                        summary_txt = " | ".join(f"{c['area']}: {c['title']}" for c in new_crits[:3])
                        await mobile_notifier.notify_merchant(
                            "watchdog_alert",
                            {
                                "shop": shop,
                                "health_score": score,
                                "issues_count": len(new_crits),
                                "summary": summary_txt,
                            },
                            shop_settings,
                        )
                    except Exception:
                        pass

            # Persist state
            prev_fixed = list(self.state.get("auto_fixed") or [])
            merged_fixed = (auto_fixed + prev_fixed)[:30]
            history_entry = {
                "scanned_at": now_iso,
                "health_score": score,
                "status": status,
                "critical_count": len(critical),
                "warning_count": len(warnings),
                "auto_fixed_count": len(auto_fixed),
                "duration_ms": duration_ms,
            }
            history = ([history_entry] + list(self.state.get("recent_history") or []))[:15]

            self.state.update({
                "scans_completed": int(self.state.get("scans_completed") or 0) + 1,
                "last_scan_at": now_iso,
                "last_duration_ms": duration_ms,
                "health_score": score,
                "status": status,
                "auto_fixed": merged_fixed,
                "critical_issues": critical,
                "warnings": warnings,
                "passed_checks": passed,
                "recent_history": history,
                "storefront": sf_res,
                "dns_score": dns_score,
                "feed_summary": feed_summary,
                "catalog_summary": catalog_summary,
                "discounts_summary": discounts_summary,
            })
            return dict(self.state)
