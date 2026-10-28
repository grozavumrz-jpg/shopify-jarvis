import asyncio
import httpx
from typing import Dict, Any, List

DNS_SERVERS = [
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query"
]

class DeliverabilityChecker:
    def __init__(self, domain: str = "maisongrozavu.com"):
        self.domain = domain

    async def _query_txt_records(self, name: str) -> List[str]:
        """Query TXT DNS records via Google or Cloudflare DNS-over-HTTPS with fallback."""
        for endpoint in DNS_SERVERS:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    if "cloudflare" in endpoint:
                        resp = await client.get(
                            endpoint,
                            params={"name": name, "type": "TXT"},
                            headers={"accept": "application/dns-json"}
                        )
                    else:
                        resp = await client.get(
                            endpoint,
                            params={"name": name, "type": "TXT"}
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        answers = data.get("Answer", [])
                        results = []
                        for ans in answers:
                            if ans.get("type") == 16:  # TXT
                                raw = ans.get("data", "").strip('"')
                                results.append(raw)
                        return results
            except Exception:
                continue
        return []

    async def audit_domain(self, domain: str = "maisongrozavu.com") -> Dict[str, Any]:
        """
        Audit SPF, DKIM, and DMARC posture.
        Returns live status, score, and exact Romanian instructions for missing DNS records.
        """
        target_domain = domain.strip().lower()

        # Run concurrent DNS queries
        spf_task = self._query_txt_records(target_domain)
        dmarc_task = self._query_txt_records(f"_dmarc.{target_domain}")
        dkim_task = self._query_txt_records(f"resend._domainkey.{target_domain}")

        spf_records, dmarc_records, dkim_records = await asyncio.gather(
            spf_task, dmarc_task, dkim_task, return_exceptions=True
        )

        spf_records = spf_records if isinstance(spf_records, list) else []
        dmarc_records = dmarc_records if isinstance(dmarc_records, list) else []
        dkim_records = dkim_records if isinstance(dkim_records, list) else []

        score = 0
        missing_records = []

        # 1. Check SPF
        spf_found = ""
        for r in spf_records:
            if "v=spf1" in r:
                spf_found = r
                break

        spf_status = {
            "name": "SPF (Sender Policy Framework)",
            "configured": bool(spf_found),
            "record": spf_found,
            "recommended_type": "TXT",
            "recommended_host": "@",
            "recommended_value": "v=spf1 include:resend.com ~all",
            "importance": "Crucială — autorizează serverele Resend să trimită emailuri în numele @maisongrozavu.com fără să fie blocate ca spam."
        }
        if spf_found:
            score += 35
        else:
            missing_records.append(spf_status)

        # 2. Check DKIM
        dkim_found = ""
        for r in dkim_records:
            if "k=rsa" in r or "v=DKIM1" in r or "p=" in r:
                dkim_found = r
                break

        dkim_status = {
            "name": "DKIM (DomainKeys Identified Mail)",
            "configured": bool(dkim_found),
            "record": dkim_found,
            "recommended_type": "TXT / CNAME",
            "recommended_host": "resend._domainkey",
            "recommended_value": "k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ...",
            "importance": "Semnătură criptografică unică — garantează furnizorilor (Gmail, Yahoo) că mesajul nu a fost falsificat."
        }
        if dkim_found:
            score += 35
        else:
            missing_records.append(dkim_status)

        # 3. Check DMARC
        dmarc_found = ""
        for r in dmarc_records:
            if "v=DMARC1" in r:
                dmarc_found = r
                break

        dmarc_status = {
            "name": "DMARC (Domain-based Message Authentication)",
            "configured": bool(dmarc_found),
            "record": dmarc_found,
            "recommended_type": "TXT",
            "recommended_host": "_dmarc",
            "recommended_value": "v=DMARC1; p=none; rua=mailto:contact@maisongrozavu.com",
            "importance": "Politică de securitate globală — protejează reputația domeniului și forțează livrarea directă în Inbox (nu Spam)."
        }
        if dmarc_found:
            score += 30
        else:
            missing_records.append(dmarc_status)

        # Overall rating
        if score >= 90:
            rating = "Excelent — Inbox Garantat"
            color = "green"
        elif score >= 35:
            rating = "Parțial Configurat — Risc Mediu de Spam"
            color = "amber"
        else:
            rating = "Înregistrări DNS Lipsă — Risc Ridicat de Filtrare ca Spam"
            color = "red"

        return {
            "domain": target_domain,
            "score": score,
            "rating": rating,
            "color": color,
            "checks": {
                "spf": spf_status,
                "dkim": dkim_status,
                "dmarc": dmarc_status
            },
            "missing_records": missing_records,
            "guide_ro": [
                "1. Deschide panoul de administrare al domeniului tău (Cloudflare, RoTLD, GoDaddy sau Namecheap).",
                "2. Mergi la secțiunea 'DNS Management' sau 'Înregistrări DNS'.",
                "3. Adaugă cele 3 înregistrări TXT specificate mai sus (SPF, DKIM și DMARC).",
                "4. Propagarea durează între 15 minute și 2 ore. Odată active, scorul tău va deveni 100/100, iar emailurile Jarvis vor ajunge garantat în Inbox-ul clienților."
            ]
        }
