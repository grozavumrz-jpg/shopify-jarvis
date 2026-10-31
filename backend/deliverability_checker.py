"""
Email authentication (SPF / DKIM / DMARC) audit for a sending domain using Resend.

Resend layout (per Resend "Domains" setup):
  - SPF  TXT  send.<domain>               "v=spf1 include:amazonses.com ~all"   (Return-Path domain)
  - MX        send.<domain>               feedback-smtp.<region>.amazonses.com  priority 10
  - DKIM TXT  resend._domainkey.<domain>  "p=<public key shown in the Resend dashboard>"
  - DMARC TXT _dmarc.<domain>             "v=DMARC1; p=none; ..."  (recommended)
The Return-Path subdomain can be customised in Resend ("custom return path"), and Resend Forge
delegates it with a CNAME to *.forge.rmta.net (SPF + MX live on Resend's side). So every name in
RESEND_RETURN_PATH (default: send, send1, rsend, bounce, mail) is checked and the best one is reported.
The root-domain SPF is NOT used by Resend; it is only checked for duplicates (two SPF
records on the same name = permerror for whoever uses it, e.g. Shopify / Google Workspace).

Per-check status is one of: "ok", "missing", "invalid", "unknown" (DNS lookup failed).
DNS failures are never reported as "missing". Passing these checks does not guarantee
inbox placement (reputation and content still matter) — the UI must not promise it.
"""
import os
import re
import asyncio
from typing import Dict, Any, List, Optional, Tuple

import httpx

DNS_SERVERS = [
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
]
DNS_TIMEOUT = 4.0
RR_TYPES = {"TXT": 16, "MX": 15, "CNAME": 5}
BRAND_DOMAIN = "maisongrozavu.com"
BRAND_MAILBOX = "info@maisongrozavu.com"

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

STATUS_OK, STATUS_MISSING, STATUS_INVALID, STATUS_UNKNOWN = "ok", "missing", "invalid", "unknown"

RESEND_RETURN_PATH_DEFAULTS = ("send", "send1", "rsend", "bounce", "mail")
RESEND_MX_SUFFIXES = (".amazonses.com", ".rmta.net")      # SES feedback-smtp.* / Forge feedback.forge.rmta.net
RESEND_FORGE_CNAME_SUFFIX = ".rmta.net"


def return_path_candidates() -> List[str]:
    """Return-Path subdomains to check: RESEND_RETURN_PATH (comma-separated) or Resend's usual names."""
    names = []
    for part in os.getenv("RESEND_RETURN_PATH", "").split(","):
        n = part.strip().lower().strip(".")
        if n and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", n) and n not in names:
            names.append(n)
    return names or list(RESEND_RETURN_PATH_DEFAULTS)


class DNSLookupError(Exception):
    """All DNS-over-HTTPS resolvers failed (network / SERVFAIL). Result is unknown, not missing."""


def parse_txt_data(data: str) -> str:
    """Join a DNS TXT answer that may be split in several quoted strings: '"a" "b"' -> 'ab'."""
    raw = (data or "").strip()
    chunks = re.findall(r'"((?:[^"\\]|\\.)*)"', raw)
    if not chunks:
        return raw
    return "".join(c.replace('\\"', '"').replace("\\\\", "\\") for c in chunks)


def _dkim_tags(record: str) -> Dict[str, str]:
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = re.sub(r"\s+", "", v.strip())
    return tags


class DeliverabilityChecker:
    def __init__(self, domain: str = BRAND_DOMAIN):
        self.domain = domain

    # ── DNS ───────────────────────────────────────────────────────────────────

    async def _query_records(self, name: str, rtype: str = "TXT") -> List[str]:
        """
        Resolve `name`/`rtype` through DNS-over-HTTPS (Google, then Cloudflare).
        Returns a list of record strings (TXT strings joined; MX as "prio host").
        [] means the name has no such record (NOERROR/NODATA or NXDOMAIN).
        Raises DNSLookupError if every resolver failed.
        """
        type_code = RR_TYPES[rtype]
        errors = []
        for endpoint in DNS_SERVERS:
            try:
                async with httpx.AsyncClient(timeout=DNS_TIMEOUT) as client:
                    resp = await client.get(
                        endpoint,
                        params={"name": name, "type": rtype},
                        headers={"accept": "application/dns-json"},
                    )
                if resp.status_code != 200:
                    errors.append(f"{endpoint}: HTTP {resp.status_code}")
                    continue
                data = resp.json()
                status = data.get("Status")
                if status == 3:  # NXDOMAIN
                    return []
                if status not in (0, None):
                    errors.append(f"{endpoint}: DNS status {status}")
                    continue
                out = []
                for ans in data.get("Answer") or []:
                    if ans.get("type") != type_code:
                        continue
                    raw = str(ans.get("data") or "")
                    if rtype == "TXT":
                        out.append(parse_txt_data(raw))
                    else:
                        out.append(raw.strip().rstrip("."))
                return out
            except Exception as e:
                errors.append(f"{endpoint}: {type(e).__name__}")
                continue
        raise DNSLookupError("; ".join(errors) or "DNS lookup failed")

    async def _query_txt_records(self, name: str) -> List[str]:
        """TXT records for `name` (raises DNSLookupError when DNS is unreachable)."""
        return await self._query_records(name, "TXT")

    async def _lookup(self, name: str, rtype: str) -> Dict[str, Any]:
        try:
            return {"ok": True, "records": await self._query_records(name, rtype), "error": None}
        except Exception as e:
            return {"ok": False, "records": [], "error": str(e)[:200] or "DNS lookup failed"}

    # ── individual checks ─────────────────────────────────────────────────────

    @staticmethod
    def _base_check(key: str, name: str, host_fqdn: str, rel_host: str, rtype: str,
                    recommended_value: str, importance: str, required: bool, weight: int) -> Dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "status": STATUS_UNKNOWN,
            "configured": False,
            "required": required,
            "weight": weight,
            "host": host_fqdn,
            "found": [],
            "record": "",
            "problem": None,
            "recommended_type": rtype,
            "recommended_host": rel_host,
            "recommended_value": recommended_value,
            "importance": importance,
        }

    @staticmethod
    def _finish(check: Dict[str, Any], status: str, problem: Optional[str] = None) -> Dict[str, Any]:
        check["status"] = status
        check["configured"] = status == STATUS_OK
        check["problem"] = problem
        return check

    @staticmethod
    def _forge_cname(cname: Optional[Dict[str, Any]]) -> Optional[str]:
        """The *.rmta.net target when the return path is delegated to Resend Forge by CNAME."""
        if not cname or not cname.get("ok"):
            return None
        for target in cname.get("records") or []:
            if target.lower().rstrip(".").endswith(RESEND_FORGE_CNAME_SUFFIX):
                return target.rstrip(".")
        return None

    def _check_resend_spf(self, domain: str, res: Dict[str, Any], sub: str = "send",
                          cname: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        c = self._base_check(
            "spf", f"SPF Resend ({sub}.)", f"{sub}.{domain}", sub, "TXT",
            "v=spf1 include:amazonses.com ~all",
            f"Autorizează serverele Resend pentru adresa de retur {sub}.<domeniu>.",
            True, 30,
        )
        forge = self._forge_cname(cname)
        if forge:
            c["via_cname"] = forge
        if not res["ok"]:
            return self._finish(c, STATUS_UNKNOWN, f"Interogarea DNS a eșuat: {res['error']}")
        spf = [r for r in res["records"] if r.lower().startswith("v=spf1")]
        c["found"] = spf
        c["record"] = spf[0] if spf else ""
        if not spf:
            return self._finish(c, STATUS_MISSING, f"Nu există înregistrare SPF pe {sub}.<domeniu>.")
        if len(spf) > 1:
            return self._finish(c, STATUS_INVALID, f"{len(spf)} înregistrări SPF pe același nume (permerror) — păstrează una singură.")
        if "include:amazonses.com" not in spf[0].lower() and not forge:
            return self._finish(c, STATUS_INVALID, "SPF-ul nu conține include:amazonses.com.")
        return self._finish(c, STATUS_OK)

    def _check_resend_mx(self, domain: str, res: Dict[str, Any], sub: str = "send") -> Dict[str, Any]:
        c = self._base_check(
            "mx", f"MX Resend ({sub}.)", f"{sub}.{domain}", sub, "MX",
            "feedback-smtp.<regiune>.amazonses.com (prioritate 10 — valoarea exactă e afișată în Resend → Domains)",
            f"Primește bounce-urile și reclamațiile pentru {sub}.<domeniu>.",
            True, 15,
        )
        c["priority"] = 10
        if not res["ok"]:
            return self._finish(c, STATUS_UNKNOWN, f"Interogarea DNS a eșuat: {res['error']}")
        c["found"] = list(res["records"])
        c["record"] = c["found"][0] if c["found"] else ""
        if not c["found"]:
            return self._finish(c, STATUS_MISSING, f"Nu există MX pe {sub}.<domeniu>.")
        if not any(r.lower().rstrip(".").endswith(RESEND_MX_SUFFIXES) for r in c["found"]):
            return self._finish(c, STATUS_INVALID, f"MX-ul de pe {sub}.<domeniu> nu indică serverele de feedback Resend.")
        return self._finish(c, STATUS_OK)

    def _best_return_path(self, domain: str, lookups: Dict[str, Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]],
                          order: List[str]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """Pick the return-path subdomain whose SPF + MX pass best; default to the first name if none passes."""
        best = None
        for idx, sub in enumerate(order):
            txt, mx, cname = lookups[sub]
            spf_c = self._check_resend_spf(domain, txt, sub, cname)
            mx_c = self._check_resend_mx(domain, mx, sub)
            passed = (spf_c["status"] == STATUS_OK) + (mx_c["status"] == STATUS_OK)
            if best is None or passed > best[0]:
                best = (passed, sub, spf_c, mx_c)
        if best[0] == 0:  # nothing configured anywhere: report the default name (unknown stays unknown)
            sub = order[0]
            txt, mx, cname = lookups[sub]
            return sub, self._check_resend_spf(domain, txt, sub, cname), self._check_resend_mx(domain, mx, sub)
        return best[1], best[2], best[3]

    def _check_dkim(self, domain: str, res: Dict[str, Any]) -> Dict[str, Any]:
        c = self._base_check(
            "dkim", "DKIM (resend._domainkey)", f"resend._domainkey.{domain}", "resend._domainkey", "TXT",
            "p=<cheia publică DKIM afișată în Resend → Domains>",
            "Semnătură criptografică: dovedește că mesajul vine de la domeniul tău și nu a fost modificat.",
            True, 35,
        )
        c["value_source"] = "resend_dashboard"
        if not res["ok"]:
            return self._finish(c, STATUS_UNKNOWN, f"Interogarea DNS a eșuat: {res['error']}")
        recs = [r for r in res["records"] if "p=" in r.lower() or "v=dkim1" in r.lower()]
        c["found"] = recs
        c["record"] = recs[0] if recs else ""
        if not recs:
            return self._finish(c, STATUS_MISSING, "Nu există cheie DKIM pe resend._domainkey.")
        if len(recs) > 1:
            return self._finish(c, STATUS_INVALID, "Mai multe înregistrări DKIM pe același selector.")
        tags = _dkim_tags(recs[0])
        key = tags.get("p", "")
        if not key:
            return self._finish(c, STATUS_INVALID, "Cheia DKIM este goală (p=) — cheie revocată.")
        if len(key) < 100 or not re.fullmatch(r"[A-Za-z0-9+/=]+", key):
            return self._finish(c, STATUS_INVALID, "Cheia DKIM pare trunchiată sau coruptă.")
        return self._finish(c, STATUS_OK)

    def _check_dmarc(self, domain: str, res: Dict[str, Any]) -> Dict[str, Any]:
        value = (f"v=DMARC1; p=none; rua=mailto:{BRAND_MAILBOX}" if domain == BRAND_DOMAIN
                 else "v=DMARC1; p=none;")
        c = self._base_check(
            "dmarc", "DMARC", f"_dmarc.{domain}", "_dmarc", "TXT", value,
            "Politica domeniului pentru mesajele care nu trec SPF/DKIM; cerută de Gmail/Yahoo pentru expeditori în volum.",
            True, 20,
        )
        if not res["ok"]:
            return self._finish(c, STATUS_UNKNOWN, f"Interogarea DNS a eșuat: {res['error']}")
        recs = [r for r in res["records"] if r.strip().lower().startswith("v=dmarc1")]
        c["found"] = recs
        c["record"] = recs[0] if recs else ""
        if not recs:
            return self._finish(c, STATUS_MISSING, "Nu există înregistrare DMARC.")
        if len(recs) > 1:
            return self._finish(c, STATUS_INVALID, "Mai multe înregistrări DMARC — DMARC este ignorat.")
        m = re.search(r"(?:^|;)\s*p\s*=\s*([a-z]+)", recs[0].lower())
        if not m or m.group(1) not in ("none", "quarantine", "reject"):
            return self._finish(c, STATUS_INVALID, "Tag-ul p= lipsește sau are o valoare invalidă.")
        c["policy"] = m.group(1)
        return self._finish(c, STATUS_OK)

    def _check_root_spf(self, domain: str, res: Dict[str, Any]) -> Dict[str, Any]:
        c = self._base_check(
            "root_spf", "SPF domeniu principal (@)", domain, "@", "TXT",
            "o singură înregistrare v=spf1 (ex. Shopify / Google Workspace) — Resend NU are nevoie de include aici",
            "Folosit de alte servicii care trimit ca @domeniu. Două înregistrări SPF = eroare (permerror).",
            False, 0,
        )
        if not res["ok"]:
            return self._finish(c, STATUS_UNKNOWN, f"Interogarea DNS a eșuat: {res['error']}")
        spf = [r for r in res["records"] if r.lower().startswith("v=spf1")]
        c["found"] = spf
        c["record"] = spf[0] if spf else ""
        if not spf:
            return self._finish(c, STATUS_MISSING, "Nu există SPF pe domeniul principal (opțional pentru Resend).")
        if len(spf) > 1:
            return self._finish(c, STATUS_INVALID, f"{len(spf)} înregistrări SPF pe domeniul principal (permerror) — unește-le într-una singură.")
        return self._finish(c, STATUS_OK)

    # ── audit ─────────────────────────────────────────────────────────────────

    async def audit_domain(self, domain: str = BRAND_DOMAIN) -> Dict[str, Any]:
        """
        Audit Resend SPF/MX, DKIM, DMARC (+ root SPF duplicates).
        Result: {domain, score (int|None), complete, rating, color, checks{...}, check_list[...],
                 missing_records[...], records_to_add[...], issues[...], guide_ro[...]}
        """
        target = (domain or self.domain or "").strip().lower().rstrip(".")
        if not _DOMAIN_RE.match(target):
            return {
                "domain": target, "error": "invalid_domain", "score": None, "complete": False,
                "rating": "Domeniu invalid", "color": "gray", "checks": {}, "check_list": [],
                "missing_records": [], "records_to_add": [], "issues": ["Domeniu invalid."], "guide_ro": [],
            }

        subs = return_path_candidates()
        root, dkim, dmarc, *rp = await asyncio.gather(
            self._lookup(target, "TXT"),
            self._lookup(f"resend._domainkey.{target}", "TXT"),
            self._lookup(f"_dmarc.{target}", "TXT"),
            *[self._lookup(f"{sub}.{target}", rtype) for sub in subs for rtype in ("TXT", "MX", "CNAME")],
        )
        lookups = {sub: tuple(rp[i * 3:i * 3 + 3]) for i, sub in enumerate(subs)}
        return_path, spf_check, mx_check = self._best_return_path(target, lookups, subs)

        checks = {
            "spf": spf_check,
            "mx": mx_check,
            "dkim": self._check_dkim(target, dkim),
            "dmarc": self._check_dmarc(target, dmarc),
            "root_spf": self._check_root_spf(target, root),
        }
        required = [c for c in checks.values() if c["required"]]
        unknown = [c for c in required if c["status"] == STATUS_UNKNOWN]
        complete = not unknown and checks["root_spf"]["status"] != STATUS_UNKNOWN
        known_required = [c for c in required if c["status"] != STATUS_UNKNOWN]

        if len(unknown) == len(required):
            score = None
        else:
            score = sum(c["weight"] for c in required if c["status"] == STATUS_OK)

        problems = [c for c in checks.values() if c["status"] in (STATUS_MISSING, STATUS_INVALID) and (c["required"] or c["status"] == STATUS_INVALID)]
        issues = [f"{c['name']}: {c['problem']}" for c in checks.values() if c["problem"] and (c["required"] or c["status"] != STATUS_MISSING)]

        all_ok = all(c["status"] == STATUS_OK for c in required)
        root_invalid = checks["root_spf"]["status"] == STATUS_INVALID
        if score is None:
            rating, color = "Nu s-a putut verifica DNS-ul — încearcă din nou mai târziu", "gray"
        elif not complete and not problems:
            rating, color = "Verificare incompletă — unele interogări DNS au eșuat", "gray"
        elif all_ok and not root_invalid:
            rating, color = "Autentificare completă (SPF, DKIM, DMARC valide)", "green"
        elif any(c["status"] == STATUS_OK for c in known_required):
            rating, color = "Configurare parțială — corectează înregistrările marcate", "amber"
        else:
            rating, color = "Autentificare lipsă — risc ridicat de filtrare ca spam", "red"

        records_to_add = []
        for c in problems:
            if c["key"] == "root_spf":
                records_to_add.append({
                    "action": "merge", "type": "TXT", "host": "@", "value": None,
                    "note": "Unește toate mecanismele într-o singură înregistrare v=spf1 … ~all și șterge duplicatul.",
                })
                continue
            entry = {
                "action": "add" if c["status"] == STATUS_MISSING else "fix",
                "check": c["key"],
                "type": c["recommended_type"],
                "host": c["recommended_host"],
                "fqdn": c["host"],
                "value": c["recommended_value"],
            }
            if c["key"] == "mx":
                entry["priority"] = 10
                entry["note"] = "Copiază valoarea exactă (cu regiunea) din Resend → Domains."
            if c["key"] == "dkim":
                entry["note"] = "Copiază cheia publică exactă din Resend → Domains (nu o inventa)."
            records_to_add.append(entry)

        check_list = [checks[k] for k in ("spf", "mx", "dkim", "dmarc", "root_spf")]
        return {
            "domain": target,
            "provider": "resend",
            "return_path": f"{return_path}.{target}",
            "return_path_via": checks["spf"].get("via_cname"),
            "score": score,
            "max_score": 100,
            "complete": complete,
            "rating": rating,
            "color": color,
            "checks": checks,
            "check_list": check_list,
            "missing_records": [c for c in problems if c["key"] != "root_spf"],
            "records_to_add": records_to_add,
            "issues": issues,
            "note": "Autentificarea corectă ajută, dar livrarea în Inbox depinde și de reputația domeniului și de conținut.",
            "guide_ro": [
                "1. Deschide panoul DNS al domeniului (unde e administrat maisongrozavu.com — ex. Shopify Domains, Cloudflare).",
                "2. În Resend → Domains, copiază exact înregistrările afișate pentru domeniu (return-path: SPF + MX pe «send» sau CNAME-ul Forge; DKIM pe «resend._domainkey»).",
                "3. Adaugă înregistrările din lista «records_to_add»; pentru DMARC poți începe cu p=none.",
                "4. Propagarea durează de obicei de la câteva minute la câteva ore; apoi apasă «Verify» în Resend și rulează din nou acest audit.",
            ],
        }
