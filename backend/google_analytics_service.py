"""
Official Google Search Console (GSC) & Google Analytics 4 (GA4) Data API client for Jarvis.

Truthfulness & security rules:
  - Zero fabricated traffic numbers: when credentials are missing or Google API returns an error,
    returns connected=False and summary=None (never estimated or sample metrics).
  - Never exposes private keys or raw credential JSON in API responses or logs.
  - Authenticates via standard Google Cloud Service Account OAuth2 JWT Bearer grant (RS256)
    using `cryptography` + async `httpx` (zero heavy SDK bloat).

Supported environment variables:
  - GOOGLE_SERVICE_ACCOUNT_JSON : raw Service Account JSON string
  - GOOGLE_SERVICE_ACCOUNT_B64  : optional base64-encoded Service Account JSON string
  - GSC_SITE_URL                : optional (default: sc-domain:<BRAND_DOMAIN>, with fallback to https://<BRAND_DOMAIN>/)
  - GA4_PROPERTY_ID             : numeric GA4 Property ID (e.g. "412345678")
"""

import base64
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TOKEN_URI = "https://oauth2.googleapis.com/token"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
GA4_API_BASE = "https://analyticsdata.googleapis.com/v1beta"
GOOGLE_API_TIMEOUT = 15.0
REPORT_CACHE_TTL_SECONDS = 900  # 15 minutes


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_property_id(raw: Optional[str]) -> str:
    s = (raw or "").strip()
    if s.lower().startswith("properties/"):
        s = s.split("/", 1)[1].strip()
    return s if re.fullmatch(r"\d{4,20}", s) else ""


def _parse_service_account_from_env() -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Parse Service Account JSON from GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_B64.
    Returns (dict | None, error_str | None). Never logs or returns the private key in error text.
    """
    raw_json = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    raw_b64 = (os.getenv("GOOGLE_SERVICE_ACCOUNT_B64") or "").strip()
    if not raw_json and not raw_b64:
        return None, None

    decoded_str = raw_json
    if not decoded_str and raw_b64:
        try:
            decoded_str = base64.b64decode(raw_b64).decode("utf-8")
        except Exception:
            return None, "GOOGLE_SERVICE_ACCOUNT_B64 nu este un base64 valid."

    try:
        info = json.loads(decoded_str)
    except Exception:
        return None, "GOOGLE_SERVICE_ACCOUNT_JSON nu este un JSON valid."

    if not isinstance(info, dict):
        return None, "Service Account JSON trebuie să fie un obiect JSON."

    client_email = str(info.get("client_email") or "").strip()
    private_key = str(info.get("private_key") or "").strip()
    # Handle literal '\n' escaped strings when pasted into Render/Heroku env vars
    if "\\n" in private_key and "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")

    if not client_email or "@" not in client_email or "PRIVATE KEY" not in private_key:
        return None, "Service Account JSON nu conține câmpurile obligatorii client_email și private_key."

    return {
        "client_email": client_email,
        "private_key": private_key,
        "token_uri": str(info.get("token_uri") or TOKEN_URI).strip() or TOKEN_URI,
    }, None


def build_setup_guide_ro(brand_domain: str = "maisongrozavu.com", service_account_email: Optional[str] = None) -> List[Dict[str, str]]:
    email_hint = (
        f"Adresa ta Service Account detectată: {service_account_email}"
        if service_account_email
        else "Adresa de email a Service Account-ului (ex: jarvis-analytics@proiectul-tau.iam.gserviceaccount.com)"
    )
    return [
        {
            "step": "1",
            "title": "Activează cele 2 API-uri gratuite în Google Cloud Console",
            "detail": (
                "Intră pe console.cloud.google.com → APIs & Services → Library și apasă Enable pe: "
                "1) Google Search Console API și 2) Google Analytics Data API."
            ),
        },
        {
            "step": "2",
            "title": "Creează un Service Account și descarcă cheia JSON",
            "detail": (
                "În IAM & Admin → Service Accounts → Create Service Account (nume ex: jarvis-analytics) → "
                "Keys → Add Key → Create new key (JSON). Se va descărca un fișier .json."
            ),
        },
        {
            "step": "3",
            "title": "Dă acces doar-citire (Viewer / Restricted) în GSC și GA4",
            "detail": (
                f"{email_hint}. "
                f"În Google Search Console ({brand_domain}) → Settings → Users and permissions → Add user (Restricted). "
                "În Google Analytics 4 → Admin → Property Access Management → Add users (Viewer). "
                "Copiază și Property ID-ul numeric din GA4 → Admin → Property Details."
            ),
        },
        {
            "step": "4",
            "title": "Adaugă 3 variabile în Render → Environment",
            "detail": (
                "GOOGLE_SERVICE_ACCOUNT_JSON = conținutul fișierului .json | "
                f"GSC_SITE_URL = sc-domain:{brand_domain} (sau https://{brand_domain}/) | "
                "GA4_PROPERTY_ID = ID-ul numeric GA4 (ex: 412345678). Apoi apasă Save & Deploy."
            ),
        },
    ]


class GoogleTrafficService:
    """Official Google Search Console + Google Analytics 4 reader with TTL caching."""

    def __init__(self, brand_domain: Optional[str] = None):
        self.brand_domain = (brand_domain or os.getenv("FEED_DOMAIN") or "maisongrozavu.com").strip().lower()
        self._token_cache: Dict[str, Tuple[float, str]] = {}
        self._report_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}

    def _service_account(self) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        return _parse_service_account_from_env()

    def _gsc_site_url(self) -> Tuple[str, bool]:
        """Returns (site_url, explicitly_configured_in_env)."""
        explicit = (os.getenv("GSC_SITE_URL") or "").strip()
        if explicit:
            return explicit, True
        return f"sc-domain:{self.brand_domain}", False

    def _ga4_property_id(self) -> str:
        return _normalize_property_id(os.getenv("GA4_PROPERTY_ID"))

    def is_gsc_configured(self) -> bool:
        sa, err = self._service_account()
        return bool(sa and not err)

    def is_ga4_configured(self) -> bool:
        sa, err = self._service_account()
        return bool(sa and not err and self._ga4_property_id())

    def is_configured(self) -> bool:
        return self.is_gsc_configured() or self.is_ga4_configured()

    def get_config_status(self) -> Dict[str, Any]:
        sa, sa_err = self._service_account()
        site_url, site_explicit = self._gsc_site_url()
        ga4_id = self._ga4_property_id()
        return {
            "service_account_configured": bool(sa and not sa_err),
            "service_account_email": sa["client_email"] if sa else None,
            "service_account_error": sa_err,
            "gsc_configured": bool(sa and not sa_err),
            "gsc_site_url": site_url,
            "gsc_site_url_explicit": site_explicit,
            "ga4_configured": bool(sa and not sa_err and ga4_id),
            "ga4_property_id": ga4_id or None,
        }

    def clear_cache(self) -> None:
        self._report_cache.clear()
        self._token_cache.clear()

    def _sign_jwt_assertion(self, sa: Dict[str, str], scopes: List[str]) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": sa["client_email"],
            "scope": " ".join(scopes),
            "aud": sa["token_uri"],
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = (
            f"{_b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
            f"{_b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
        ).encode("ascii")

        private_key = serialization.load_pem_private_key(
            sa["private_key"].encode("utf-8"),
            password=None,
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode('ascii')}.{_b64url(signature)}"

    async def _get_access_token(self, scopes: List[str]) -> Tuple[Optional[str], Optional[str]]:
        sa, sa_err = self._service_account()
        if sa_err:
            return None, sa_err
        if not sa:
            return None, "GOOGLE_SERVICE_ACCOUNT_JSON nu este configurat."

        cache_key = f"{sa['client_email']}|{' '.join(sorted(scopes))}"
        cached = self._token_cache.get(cache_key)
        if cached and time.time() < cached[0]:
            return cached[1], None

        try:
            assertion = self._sign_jwt_assertion(sa, scopes)
        except Exception as e:
            return None, f"Cheia privată din Service Account nu a putut semna tokenul ({type(e).__name__})."

        try:
            async with httpx.AsyncClient(timeout=GOOGLE_API_TIMEOUT) as client:
                res = await client.post(
                    sa["token_uri"],
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                )
        except httpx.HTTPError as e:
            return None, f"Nu am putut contacta Google OAuth ({type(e).__name__})."

        if res.status_code != 200:
            err_msg = ""
            try:
                body = res.json()
                err_msg = body.get("error_description") or body.get("error") or ""
            except Exception:
                pass
            return None, f"Google OAuth a refuzat autentificarea ({res.status_code}{': ' + err_msg[:120] if err_msg else ''})."

        try:
            data = res.json()
            token = str(data.get("access_token") or "").strip()
            expires_in = int(data.get("expires_in") or 3600)
        except Exception:
            return None, "Răspuns invalid de la Google OAuth."

        if not token:
            return None, "Google OAuth nu a returnat access_token."

        ttl = max(60, expires_in - 300)
        self._token_cache[cache_key] = (time.time() + ttl, token)
        return token, None

    # ── Google Search Console API v3 ──────────────────────────────────────────

    async def _query_gsc(self, client: httpx.AsyncClient, token: str, site_url: str, body: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], int, str]:
        encoded_site = urllib.parse.quote(site_url, safe="")
        url = f"{GSC_API_BASE}/sites/{encoded_site}/searchAnalytics/query"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            res = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            return None, 0, f"Eroare rețea Google Search Console ({type(e).__name__})"
        if res.status_code != 200:
            detail = ""
            try:
                err = res.json().get("error") or {}
                detail = str(err.get("message") or "")[:160]
            except Exception:
                pass
            return None, res.status_code, detail or f"HTTP {res.status_code}"
        try:
            return res.json(), 200, ""
        except ValueError:
            return None, 200, "Răspuns JSON invalid din Google Search Console"

    async def fetch_search_console_report(self, days: int = 28) -> Dict[str, Any]:
        days = max(1, min(int(days or 28), 90))
        site_url, explicit = self._gsc_site_url()
        base: Dict[str, Any] = {
            "configured": self.is_gsc_configured(),
            "connected": False,
            "site_url": site_url,
            "days": days,
            "error": None,
            "summary": None,
            "top_queries": [],
            "opportunity_queries": [],
            "top_pages": [],
        }
        if not base["configured"]:
            _, sa_err = self._service_account()
            base["error"] = sa_err or "Adaugă GOOGLE_SERVICE_ACCOUNT_JSON pentru a conecta Google Search Console."
            return base

        token, tok_err = await self._get_access_token([GSC_SCOPE])
        if not token:
            base["error"] = tok_err
            return base

        end_dt = datetime.now(timezone.utc).date() - timedelta(days=2)
        start_dt = end_dt - timedelta(days=days - 1)
        date_range = {"startDate": start_dt.isoformat(), "endDate": end_dt.isoformat()}

        candidates = [site_url]
        if not explicit:
            alt = f"https://{self.brand_domain}/"
            if alt not in candidates:
                candidates.append(alt)

        chosen_site = site_url
        summary_data = None
        last_err = ""
        last_status = 0

        async with httpx.AsyncClient(timeout=GOOGLE_API_TIMEOUT) as client:
            for cand in candidates:
                data, code, err = await self._query_gsc(client, token, cand, {**date_range, "rowLimit": 1})
                if data is not None:
                    chosen_site = cand
                    summary_data = data
                    break
                last_status, last_err = code, err
                if code not in (403, 404):
                    break

            if summary_data is None:
                hint = ""
                if last_status == 403:
                    sa, _ = self._service_account()
                    email = sa["client_email"] if sa else "Service Account"
                    hint = f" Adaugă {email} ca utilizator în Google Search Console pentru {chosen_site}."
                base["site_url"] = chosen_site
                base["error"] = f"Google Search Console: {last_err}.{hint}".strip()
                return base

            q_data, _, _ = await self._query_gsc(
                client, token, chosen_site, {**date_range, "dimensions": ["query"], "rowLimit": 25}
            )
            p_data, _, _ = await self._query_gsc(
                client, token, chosen_site, {**date_range, "dimensions": ["page"], "rowLimit": 15}
            )

        rows_sum = summary_data.get("rows") or []
        if rows_sum:
            r0 = rows_sum[0]
            summary = {
                "clicks": _safe_int(r0.get("clicks")),
                "impressions": _safe_int(r0.get("impressions")),
                "ctr": round(_safe_float(r0.get("ctr")) * 100.0, 2),
                "avg_position": round(_safe_float(r0.get("position")), 1),
            }
        else:
            summary = {"clicks": 0, "impressions": 0, "ctr": 0.0, "avg_position": 0.0}

        top_queries: List[Dict[str, Any]] = []
        opportunity_queries: List[Dict[str, Any]] = []
        for r in (q_data or {}).get("rows") or []:
            keys = r.get("keys") or []
            if not keys:
                continue
            item = {
                "query": str(keys[0]),
                "clicks": _safe_int(r.get("clicks")),
                "impressions": _safe_int(r.get("impressions")),
                "ctr": round(_safe_float(r.get("ctr")) * 100.0, 2),
                "position": round(_safe_float(r.get("position")), 1),
            }
            top_queries.append(item)
            if item["impressions"] >= 10 and 4.5 <= item["position"] <= 25.0:
                opportunity_queries.append(item)

        top_queries.sort(key=lambda x: (-x["clicks"], -x["impressions"]))
        opportunity_queries.sort(key=lambda x: (-x["impressions"], x["position"]))

        top_pages: List[Dict[str, Any]] = []
        for r in (p_data or {}).get("rows") or []:
            keys = r.get("keys") or []
            if not keys:
                continue
            top_pages.append({
                "page": str(keys[0]),
                "clicks": _safe_int(r.get("clicks")),
                "impressions": _safe_int(r.get("impressions")),
                "ctr": round(_safe_float(r.get("ctr")) * 100.0, 2),
                "position": round(_safe_float(r.get("position")), 1),
            })
        top_pages.sort(key=lambda x: (-x["clicks"], -x["impressions"]))

        base.update({
            "connected": True,
            "site_url": chosen_site,
            "date_range": date_range,
            "summary": summary,
            "top_queries": top_queries[:15],
            "opportunity_queries": opportunity_queries[:10],
            "top_pages": top_pages[:10],
        })
        return base

    # ── Google Analytics 4 Data API v1beta ────────────────────────────────────

    async def _run_ga4_report(self, client: httpx.AsyncClient, token: str, property_id: str, body: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], int, str]:
        url = f"{GA4_API_BASE}/properties/{property_id}:runReport"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            res = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            return None, 0, f"Eroare rețea Google Analytics 4 ({type(e).__name__})"
        if res.status_code != 200:
            detail = ""
            try:
                err = res.json().get("error") or {}
                detail = str(err.get("message") or "")[:160]
            except Exception:
                pass
            return None, res.status_code, detail or f"HTTP {res.status_code}"
        try:
            return res.json(), 200, ""
        except ValueError:
            return None, 200, "Răspuns JSON invalid din Google Analytics 4"

    async def fetch_ga4_sessions_by_hour(self, days: int = 28) -> Dict[str, Any]:
        """
        Real GA4 sessions per hour of day (property time zone), read-only. Engaged sessions are
        returned too: they are a better signal of real people than raw sessions.
        """
        days = max(7, min(int(days or 28), 90))
        out: Dict[str, Any] = {"connected": False, "days": days, "hours": [], "error": None}
        if not self.is_ga4_configured():
            out["error"] = "GA4 neconfigurat"
            return out
        token, tok_err = await self._get_access_token([GA4_SCOPE])
        if not token:
            out["error"] = tok_err
            return out
        async with httpx.AsyncClient(timeout=GOOGLE_API_TIMEOUT) as client:
            res, _code, err = await self._run_ga4_report(client, token, self._ga4_property_id(), {
                "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
                "dimensions": [{"name": "hour"}],
                "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}],
                "limit": 24,
            })
        if res is None:
            out["error"] = f"Google Analytics 4: {err}"
            return out
        hours = []
        for row in res.get("rows") or []:
            dims = row.get("dimensionValues") or []
            mets = row.get("metricValues") or []
            h = _safe_int((dims[0] or {}).get("value") if dims else None, -1)
            if 0 <= h <= 23:
                hours.append({
                    "hour": h,
                    "sessions": _safe_int((mets[0] or {}).get("value") if mets else 0),
                    "engaged_sessions": _safe_int((mets[1] or {}).get("value") if len(mets) > 1 else 0),
                })
        out.update(connected=True, hours=sorted(hours, key=lambda x: x["hour"]))
        return out

    async def fetch_ga4_report(self, days: int = 28) -> Dict[str, Any]:
        days = max(1, min(int(days or 28), 90))
        property_id = self._ga4_property_id()
        base: Dict[str, Any] = {
            "configured": self.is_ga4_configured(),
            "connected": False,
            "property_id": property_id or None,
            "days": days,
            "error": None,
            "summary": None,
            "channels": [],
            "top_pages": [],
            "countries": [],
        }
        if not base["configured"]:
            _, sa_err = self._service_account()
            if sa_err:
                base["error"] = sa_err
            elif not property_id:
                base["error"] = "Adaugă GA4_PROPERTY_ID (ID-ul numeric al proprietății GA4) în Render."
            else:
                base["error"] = "Adaugă GOOGLE_SERVICE_ACCOUNT_JSON pentru a conecta Google Analytics 4."
            return base

        token, tok_err = await self._get_access_token([GA4_SCOPE])
        if not token:
            base["error"] = tok_err
            return base

        date_ranges = [{"startDate": f"{days}daysAgo", "endDate": "today"}]

        async with httpx.AsyncClient(timeout=GOOGLE_API_TIMEOUT) as client:
            summary_res, code, err = await self._run_ga4_report(
                client,
                token,
                property_id,
                {
                    "dateRanges": date_ranges,
                    "metrics": [
                        {"name": "sessions"},
                        {"name": "totalUsers"},
                        {"name": "newUsers"},
                        {"name": "screenPageViews"},
                        {"name": "engagementRate"},
                        {"name": "averageSessionDuration"},
                        {"name": "ecommercePurchases"},
                    ],
                },
            )
            if summary_res is None:
                hint = ""
                if code == 403:
                    sa, _ = self._service_account()
                    email = sa["client_email"] if sa else "Service Account"
                    hint = f" Adaugă {email} cu rol Viewer în GA4 → Admin → Property Access Management."
                base["error"] = f"Google Analytics 4: {err}.{hint}".strip()
                return base

            channels_res, _, _ = await self._run_ga4_report(
                client,
                token,
                property_id,
                {
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "sessionDefaultChannelGroup"}],
                    "metrics": [{"name": "sessions"}, {"name": "totalUsers"}],
                    "limit": 10,
                },
            )
            pages_res, _, _ = await self._run_ga4_report(
                client,
                token,
                property_id,
                {
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "pagePath"}],
                    "metrics": [{"name": "screenPageViews"}, {"name": "sessions"}],
                    "limit": 10,
                },
            )
            countries_res, _, _ = await self._run_ga4_report(
                client,
                token,
                property_id,
                {
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "country"}],
                    "metrics": [{"name": "sessions"}, {"name": "totalUsers"}],
                    "limit": 15,
                },
            )

        rows = summary_res.get("rows") or []
        if rows:
            mv = [m.get("value") for m in (rows[0].get("metricValues") or [])]
            while len(mv) < 7:
                mv.append("0")
            summary = {
                "sessions": _safe_int(mv[0]),
                "total_users": _safe_int(mv[1]),
                "new_users": _safe_int(mv[2]),
                "page_views": _safe_int(mv[3]),
                "engagement_rate": round(_safe_float(mv[4]) * 100.0, 1),
                "avg_session_duration_sec": round(_safe_float(mv[5]), 1),
                "purchases": _safe_int(mv[6]),
            }
        else:
            summary = {
                "sessions": 0,
                "total_users": 0,
                "new_users": 0,
                "page_views": 0,
                "engagement_rate": 0.0,
                "avg_session_duration_sec": 0.0,
                "purchases": 0,
            }

        channels = []
        for r in (channels_res or {}).get("rows") or []:
            dv = r.get("dimensionValues") or []
            mv = r.get("metricValues") or []
            if dv:
                channels.append({
                    "channel": str(dv[0].get("value") or "Unknown"),
                    "sessions": _safe_int(mv[0].get("value") if len(mv) > 0 else 0),
                    "users": _safe_int(mv[1].get("value") if len(mv) > 1 else 0),
                })

        top_pages = []
        for r in (pages_res or {}).get("rows") or []:
            dv = r.get("dimensionValues") or []
            mv = r.get("metricValues") or []
            if dv:
                top_pages.append({
                    "path": str(dv[0].get("value") or "/"),
                    "views": _safe_int(mv[0].get("value") if len(mv) > 0 else 0),
                    "sessions": _safe_int(mv[1].get("value") if len(mv) > 1 else 0),
                })

        countries = []
        for r in (countries_res or {}).get("rows") or []:
            dv = r.get("dimensionValues") or []
            mv = r.get("metricValues") or []
            if dv:
                countries.append({
                    "country": str(dv[0].get("value") or "Unknown"),
                    "sessions": _safe_int(mv[0].get("value") if len(mv) > 0 else 0),
                    "users": _safe_int(mv[1].get("value") if len(mv) > 1 else 0),
                })

        base.update({
            "connected": True,
            "summary": summary,
            "channels": channels,
            "top_pages": top_pages,
            "countries": countries,
        })
        return base

    # ── Traffic Quality & Bot Filter (Upgrade 1) ─────────────────────────────

    EU_PRIORITY_COUNTRIES = {
        "Spain", "Romania", "France", "Germany", "Italy", "Portugal", "Netherlands",
        "Belgium", "Austria", "United Kingdom", "Ireland", "Poland", "Sweden", "Denmark",
        "Greece", "Czechia", "Hungary", "Bulgaria", "Croatia", "Switzerland",
    }

    @classmethod
    def analyze_traffic_quality(cls, gsc: Dict[str, Any], ga4: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Deterministic analysis of real GA4 + GSC traffic to separate qualified human sessions
        from suspected Direct/Unassigned bot inflation and surface actionable SEO alerts.
        Returns None when neither GSC nor GA4 is connected.
        """
        gsc_ok = bool(isinstance(gsc, dict) and gsc.get("connected"))
        ga4_ok = bool(isinstance(ga4, dict) and ga4.get("connected"))
        if not gsc_ok and not ga4_ok:
            return None

        ga4_sum = (ga4.get("summary") or {}) if ga4_ok else {}
        total_sessions = _safe_int(ga4_sum.get("sessions"))
        engagement_rate = _safe_float(ga4_sum.get("engagement_rate"))
        channels = (ga4.get("channels") or []) if ga4_ok else []
        countries = (ga4.get("countries") or []) if ga4_ok else []

        direct_unassigned = 0
        qualified_sessions = 0
        organic_search_sessions = 0
        organic_social_sessions = 0
        for ch in channels:
            name = str(ch.get("channel") or "").strip().lower()
            sess = _safe_int(ch.get("sessions"))
            if name in ("direct", "unassigned", "(other)", ""):
                direct_unassigned += sess
            else:
                qualified_sessions += sess
                if "organic search" in name:
                    organic_search_sessions += sess
                elif "social" in name:
                    organic_social_sessions += sess

        direct_pct = round((direct_unassigned / total_sessions) * 100.0, 1) if total_sessions > 0 else 0.0
        eu_sessions = sum(_safe_int(c.get("sessions")) for c in countries if str(c.get("country") or "") in cls.EU_PRIORITY_COUNTRIES)
        eu_breakdown = [
            {"country": c.get("country"), "sessions": _safe_int(c.get("sessions"))}
            for c in countries
            if str(c.get("country") or "") in cls.EU_PRIORITY_COUNTRIES
        ][:6]

        # Classic bot/crawler inflation signature: >=65% Direct/Unassigned AND engagement < 38% with >=100 sessions
        bot_alert = bool(ga4_ok and total_sessions >= 100 and direct_pct >= 65.0 and engagement_rate < 38.0)
        suspected_bot_sessions = direct_unassigned if bot_alert else 0

        if not ga4_ok:
            bot_summary_ro = "GA4 nu este conectat încă — filtrul de boți așteaptă date GA4."
        elif bot_alert:
            bot_summary_ro = (
                f"Posibil trafic automat (estimare, nu certitudine): {direct_pct}% din sesiunile GA4 "
                f"({direct_unassigned:,} din {total_sessions:,}) sunt Direct/Unassigned, cu angajament mic ({engagement_rate}%). "
                "Tiparul ăsta apare des la boți, dar poate fi și trafic din aplicații sau linkuri fără UTM. "
                f"Sesiuni din canale identificate (Organic Search, Social, Referral): {qualified_sessions:,}."
            )
        else:
            bot_summary_ro = (
                f"Nu apare tiparul tipic de trafic automat: {qualified_sessions:,} sesiuni din canale identificate "
                f"și rată de angajament {engagement_rate}%."
            )

        top_queries = (gsc.get("top_queries") or []) if gsc_ok else []
        opp_queries = (gsc.get("opportunity_queries") or []) if gsc_ok else []
        top10_queries = [q for q in top_queries if _safe_float(q.get("position"), 99.0) <= 10.0][:8]

        alerts: List[Dict[str, str]] = []
        if bot_alert:
            alerts.append({
                "severity": "warning",
                "code": "ga4_bot_traffic_inflation",
                "title": f"Posibil trafic de boți în GA4 ({direct_pct}% Direct/Unassigned) — estimare",
                "detail": bot_summary_ro,
            })
        if gsc_ok and opp_queries:
            best = opp_queries[0]
            alerts.append({
                "severity": "opportunity",
                "code": "gsc_page1_opportunity",
                "title": f"{len(opp_queries)} cuvinte-cheie aproape de Top 5 Google",
                "detail": (
                    f"Cea mai bună oportunitate: „{best['query']}” (poziția #{best['position']}, "
                    f"{best['impressions']} afișări, {best['clicks']} click-uri)."
                ),
            })
        if gsc_ok:
            gsc_sum = gsc.get("summary") or {}
            if _safe_int(gsc_sum.get("impressions")) >= 500 and _safe_float(gsc_sum.get("ctr")) < 1.5:
                alerts.append({
                    "severity": "warning",
                    "code": "gsc_low_ctr",
                    "title": f"CTR Google scăzut ({gsc_sum.get('ctr')}% la {gsc_sum.get('impressions'):,} afișări)",
                    "detail": "Oamenii văd produsele în Google, dar dau rar click. Îmbunătățește titlurile/meta-descrierile pe paginile din Top 10.",
                })

        return {
            "total_ga4_sessions": total_sessions,
            "qualified_human_sessions": qualified_sessions,
            "organic_search_sessions": organic_search_sessions,
            "organic_social_sessions": organic_social_sessions,
            "direct_unassigned_sessions": direct_unassigned,
            "direct_unassigned_pct": direct_pct,
            "suspected_bot_sessions": suspected_bot_sessions,
            "bot_alert": bot_alert,
            "bot_summary_ro": bot_summary_ro,
            "eu_priority_sessions": eu_sessions,
            "eu_breakdown": eu_breakdown,
            "top10_queries_count": len(top10_queries),
            "top10_queries": top10_queries,
            "opportunity_queries_count": len(opp_queries),
            "alerts": alerts,
        }

    # ── Combined Report & AI Prompt Context ───────────────────────────────────

    async def get_combined_report(self, days: int = 28, force_refresh: bool = False) -> Dict[str, Any]:
        days = max(1, min(int(days or 28), 90))
        if not force_refresh:
            cached = self._report_cache.get(days)
            if cached and time.time() - cached[0] < REPORT_CACHE_TTL_SECONDS:
                return dict(cached[1])

        cfg = self.get_config_status()
        gsc = await self.fetch_search_console_report(days=days)
        ga4 = await self.fetch_ga4_report(days=days)
        quality = self.analyze_traffic_quality(gsc, ga4)

        report: Dict[str, Any] = {
            "configured": bool(cfg["gsc_configured"] or cfg["ga4_configured"]),
            "connected": bool(gsc.get("connected") or ga4.get("connected")),
            "days": days,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "domain": self.brand_domain,
            "config": cfg,
            "search_console": gsc,
            "ga4": ga4,
            "traffic_quality": quality,
            "setup_guide_ro": build_setup_guide_ro(
                brand_domain=self.brand_domain,
                service_account_email=cfg.get("service_account_email"),
            ),
        }
        self._report_cache[days] = (time.time(), report)
        return dict(report)

    @staticmethod
    def to_prompt_context(report: Optional[Dict[str, Any]]) -> str:
        """
        Format verified GSC + GA4 numbers into a compact prompt block for AIAdvisor.
        Returns '' when neither GSC nor GA4 returned live connected data.
        """
        if not isinstance(report, dict) or not report.get("connected"):
            return ""

        days = report.get("days") or 28
        lines = [f"GOOGLE TRAFFIC & SEARCH DATA (real verified Google APIs, last {days} days):"]

        gsc = report.get("search_console") or {}
        if gsc.get("connected") and isinstance(gsc.get("summary"), dict):
            s = gsc["summary"]
            lines.append(
                f"- Google Search Console ({gsc.get('site_url')}): "
                f"{s.get('clicks', 0)} clicks, {s.get('impressions', 0)} impressions, "
                f"CTR {s.get('ctr', 0)}%, avg position {s.get('avg_position', 0)}"
            )
            top_q = gsc.get("top_queries") or []
            if top_q:
                lines.append(
                    "- Top Google search queries: "
                    + ", ".join(
                        f"\"{q['query']}\" ({q['clicks']} clicks, {q['impressions']} impr, pos {q['position']})"
                        for q in top_q[:6]
                    )
                )
            opp_q = gsc.get("opportunity_queries") or []
            if opp_q:
                lines.append(
                    "- Page-1 SEO opportunities (pos 5-25 with impressions): "
                    + ", ".join(
                        f"\"{q['query']}\" (pos {q['position']}, {q['impressions']} impr)"
                        for q in opp_q[:5]
                    )
                )
            top_p = gsc.get("top_pages") or []
            if top_p:
                lines.append(
                    "- Top Google landing pages: "
                    + ", ".join(f"{p['page']} ({p['clicks']} clicks)" for p in top_p[:4])
                )

        ga4 = report.get("ga4") or {}
        if ga4.get("connected") and isinstance(ga4.get("summary"), dict):
            s = ga4["summary"]
            lines.append(
                f"- Google Analytics 4 (property {ga4.get('property_id')}): "
                f"{s.get('sessions', 0)} sessions, {s.get('total_users', 0)} users "
                f"({s.get('new_users', 0)} new), {s.get('page_views', 0)} page views, "
                f"engagement rate {s.get('engagement_rate', 0)}%, "
                f"avg session {s.get('avg_session_duration_sec', 0)}s, "
                f"GA4 purchases {s.get('purchases', 0)}"
            )
            channels = ga4.get("channels") or []
            if channels:
                lines.append(
                    "- Top GA4 traffic channels: "
                    + ", ".join(f"{c['channel']} ({c['sessions']} sessions)" for c in channels[:5])
                )
            countries = ga4.get("countries") or []
            if countries:
                lines.append(
                    "- Top visitor countries (GA4): "
                    + ", ".join(f"{c['country']} ({c['sessions']} sessions)" for c in countries[:5])
                )

        tq = report.get("traffic_quality")
        if isinstance(tq, dict):
            lines.append(
                f"- Traffic Quality Filter: {tq.get('qualified_human_sessions', 0)} qualified sessions "
                f"(Organic Search: {tq.get('organic_search_sessions', 0)}), "
                f"Direct/Unassigned: {tq.get('direct_unassigned_pct', 0)}% "
                f"({'possible bot traffic: heuristic estimate, NOT confirmed' if tq.get('bot_alert') else 'no bot pattern detected'})"
            )

        return "\n".join(lines) if len(lines) > 1 else ""
