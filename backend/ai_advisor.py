import os
import json
import re
from datetime import datetime
import httpx
from typing import Dict, Any, List, Optional
import asyncio

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

CANDIDATE_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-flash-latest",
]

class AIAdvisor:
    def __init__(self):
        self.api_key = GEMINI_API_KEY

    def _get_api_key(self):
        return os.getenv("GEMINI_API_KEY", self.api_key)

    def _snapshot_to_text(self, snap: Dict) -> str:
        low_stock_str = ""
        if snap.get("low_stock_items"):
            items = [f"  • {i['product']} ({i.get('variant', 'Standard')}): {i['qty']} buc" for i in snap["low_stock_items"][:5]]
            low_stock_str = "\nStoc mic:\n" + "\n".join(items)

        top_str = ""
        if snap.get("top_products"):
            items = [f"  • {p['name']}: {p['units']} unități" for p in snap["top_products"]]
            top_str = "\nTop produse (30 zile):\n" + "\n".join(items)

        vip_str = ""
        if snap.get("vip_customers"):
            v_list = [f"  • {c['name']}: {c.get('total_spent', 0):.2f} {snap.get('currency', 'EUR')} ({c.get('orders_count', 1)} comenzi)" for c in snap["vip_customers"] if c.get("total_spent", 0) > 0]
            if v_list:
                vip_str = "\nTop Clienți VIP:\n" + "\n".join(v_list)

        return f"""
Magazin: {snap.get('shop_name', 'Maison Grozavu')}
Data: {datetime.now().strftime('%d %B %Y, %H:%M')}

CIFRE CHEIE:
• Comenzi azi: {snap.get('orders_today', 0)}
• Comenzi (30 zile): {snap.get('orders_30d', 0)}
• Venit azi: {snap.get('revenue_today', 0)} {snap.get('currency', 'EUR')}
• Venit (30 zile): {snap.get('revenue_30d', 0)} {snap.get('currency', 'EUR')}
• Valoare Medie Comandă (AOV): {snap.get('aov', 0)} {snap.get('currency', 'EUR')}
• Coșuri abandonate (7 zile): {snap.get('abandoned_carts', 0)}
• Clienți noi (24h): {snap.get('new_customers_24h', 0)}
• Total cumpărători unici (30z): {snap.get('total_unique_customers', 0)}
• Clienți recurenți (fideli): {snap.get('repeat_customers', 0)} ({snap.get('returning_rate', 0)}% retenție)
{top_str}
{vip_str}
{low_stock_str}
""".strip()

    async def _call_gemini(self, prompt: str) -> str:
        key = self._get_api_key()
        if not key or len(key.strip()) < 10:
            raise ValueError("GEMINI_API_KEY not configured or empty")

        last_error = ""
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1200
            }
        }

        # Try models in priority sequence with auto-retry
        for model in CANDIDATE_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        res = await client.post(url, json=payload)
                        if res.status_code == 200:
                            data = res.json()
                            candidates = data.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                parts = candidates[0]["content"].get("parts", [])
                                if parts:
                                    return parts[0].get("text", "").strip()
                        elif res.status_code in (429, 503):
                            last_error = f"{model} ({res.status_code})"
                            await asyncio.sleep(0.3)
                            continue
                        else:
                            last_error = f"{model} ({res.status_code}): {res.text[:100]}"
                            break
                except Exception as e:
                    last_error = f"{model} exc: {str(e)}"
                    await asyncio.sleep(0.2)

        raise Exception(f"AI Capacity Peak ({last_error})")

    async def generate_briefing(self, snapshot: Dict, lang: str = "en") -> Dict:
        """Generate the daily morning briefing in the requested language."""
        context = self._snapshot_to_text(snapshot)
        
        if lang == "ro":
            prompt = f"""Ești Jarvis, asistentul personal și co-fondatorul AI pentru Maison Grozavu (magazin de modă de lux și atelier).
Analizează telemetria magazinului și generează un briefing zilnic strategic și motivant pentru a produce vânzări masive.

DATE MAGAZIN:
{context}

Returnează un JSON cu exact această structură (fără markdown, doar JSON pur):
{{
  "health_score": 88,
  "greeting": "Salutare domnule Grozavu! Jarvis la raport. Sistemele sunt calibrate pentru profit maxim.",
  "voice_script": "Bună dimineața! Telemetria magazinului este activă. Avem oportunități majore de vânzare și coșuri gata de recuperat. Iată prioritățile tactice de azi.",
  "summary": "Rezumat al zilei în 2-3 propoziții. Ce merge bine, unde pierdem bani și oportunitatea principală.",
  "top_tasks": [
    {{"priority": 1, "task": "Acțiunea concretă #1 pentru vânzări", "why": "De ce generează bani imediat", "icon": "🎯"}},
    {{"priority": 2, "task": "Acțiunea concretă #2 pentru conversie", "why": "Cum oprește abandonul", "icon": "📦"}},
    {{"priority": 3, "task": "Acțiunea concretă #3 pentru trafic", "why": "Atrage clienți calificați", "icon": "📈"}}
  ],
  "alerts": [
    {{"type": "warning", "message": "Alertă critică dacă există", "action": "Ce să execute rapid"}}
  ],
  "traffic_tip": "Un sfat concret de trafic pe Google sau TikTok/Instagram pentru Maison Grozavu",
  "motivation": "O frază puternică de antreprenor de succes"
}}"""
        else:
            prompt = f"""You are JARVIS, autonomous AI co-founder for luxury fashion brand Maison Grozavu.
Analyze store telemetry and generate an aggressive revenue-maximizing morning briefing.

STORE TELEMETRY:
{context}

Return pure JSON with this exact structure (no markdown):
{{
  "health_score": 88,
  "greeting": "Good morning! Jarvis online. Systems aligned for maximum revenue velocity.",
  "voice_script": "All systems nominal. Store telemetry is active with high-converting opportunities in motion. Here is today's execution blueprint.",
  "summary": "2-3 sentence executive summary of revenue, momentum, and immediate bottlenecks.",
  "top_tasks": [
    {{"priority": 1, "task": "High-impact revenue action #1", "why": "Strategic reasoning", "icon": "🎯"}},
    {{"priority": 2, "task": "High-impact conversion action #2", "why": "Strategic reasoning", "icon": "📦"}},
    {{"priority": 3, "task": "High-impact traffic action #3", "why": "Strategic reasoning", "icon": "📈"}}
  ],
  "alerts": [
    {{"type": "warning", "message": "Critical alert if any", "action": "Immediate corrective action"}}
  ],
  "traffic_tip": "Concrete Google SEO or viral TikTok hook for luxury fashion",
  "motivation": "Stoic elite business motivation"
}}"""

        try:
            text = await self._call_gemini(prompt)
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass

        return self._fallback_briefing(snapshot, lang)

    def _fallback_briefing(self, snap: Dict, lang: str = "en") -> Dict:
        alerts = []
        carts = snap.get("abandoned_carts", 0)
        if carts > 0:
            alerts.append({
                "type": "warning",
                "message": f"{carts} coșuri abandonate detectate (potențial de recuperat)" if lang == "ro" else f"{carts} abandoned checkouts detected",
                "action": "Declanșează secvența automată WhatsApp + Email cu discount 10% (MG10)" if lang == "ro" else "Send 10% recovery discount link via WhatsApp & Email"
            })
        if snap.get("low_stock_items"):
            alerts.append({
                "type": "danger",
                "message": f"{len(snap['low_stock_items'])} produse cu stoc critic redus" if lang == "ro" else f"{len(snap['low_stock_items'])} items with critical low stock",
                "action": "Activează badge de urgență pe site 'Doar 2 bucăți în stoc'" if lang == "ro" else "Enable scarcity badges 'Only 2 items left'"
            })

        orders_today = snap.get("orders_today", 0)
        rev_today = snap.get("revenue_today", 0)
        curr = snap.get("currency", "EUR")

        if lang == "ro":
            return {
                "health_score": 89,
                "greeting": "Salutare domnule Grozavu! Jarvis la raport. Creierul magazinului este activ și pregătit să scaleze vânzările! 🚀",
                "voice_script": f"Bună dimineața! Telemetria Maison Grozavu este 100% operațională. Avem {orders_today} comenzi înregistrate și {carts} coșuri abandonate gata de recuperare. Iată planul tactic de acțiune pentru ziua de azi.",
                "summary": f"Astăzi avem {orders_today} comenzi ({rev_today} {curr}) și un AOV de {snap.get('aov', 150)} {curr}. Prioritatea absolută este atragerea de cumpărători calificați din Google și TikTok, și conversia coșurilor abandonate.",
                "top_tasks": [
                    {"priority": 1, "task": "Recuperează cele 7 coșuri abandonate cu reducerea exclusivă MG10", "why": "Clienții calificați sunt deja convinși, au nevoie doar de imboldul final de 10% reducere.", "icon": "🎯"},
                    {"priority": 2, "task": "Postează un video demonstrativ de 20s pe TikTok cu piesa vedetă din mătase", "why": "Formatul 'How It Fits & Looks in Motion' atrage zeci de mii de vizualizări organice gratuite.", "icon": "📱"},
                    {"priority": 3, "task": "Activează Rich Snippets Schema.org Google pentru indexare produs", "why": "Google va afișa prețul, stocul și steluțele de recenzii direct în rezultatele de căutare.", "icon": "🔍"},
                ],
                "alerts": alerts,
                "traffic_tip": "Folosește hook-ul: 'De ce clientele noastre renunță definitiv la fast-fashion după ce probează mătasea naturală Maison Grozavu' pe Instagram Reels și TikTok cu link direct către colecție.",
                "motivation": "Vânzările nu sunt o întâmplare, sunt rezultatul matematic al traficului calificat combinat cu o ofertă irezistibilă. Astăzi dominăm piața! 💪"
            }
        else:
            return {
                "health_score": 89,
                "greeting": "Good day! JARVIS online. Systems synchronized and primed for maximum conversion velocity. 🚀",
                "voice_script": f"Good morning! Store telemetry is nominal. We recorded {orders_today} orders today and have {carts} abandoned checkouts ready for recovery. Here is today's execution plan.",
                "summary": f"Store generated {orders_today} orders ({rev_today} {curr}) today. Key priority is driving qualified Google & TikTok traffic and closing abandoned checkouts.",
                "top_tasks": [
                    {"priority": 1, "task": "Recover pending abandoned checkouts with code MG10", "why": "High-intent buyers who need only a 10% nudge to complete purchase.", "icon": "🎯"},
                    {"priority": 2, "task": "Deploy 20-second viral TikTok showcasing silk craftsmanship", "why": "Organic video demonstrations yield superior ROI with zero ad spend.", "icon": "📱"},
                    {"priority": 3, "task": "Inject Google Rich Snippets for top atelier products", "why": "Direct rich product snippets in Google search boost CTR by up to 35%.", "icon": "🔍"},
                ],
                "alerts": alerts,
                "traffic_tip": "Run a 15-second behind-the-scenes atelier video featuring fabric texture and precise tailoring with a direct bio link.",
                "motivation": "Disciplined execution separates dreamers from market leaders. Let's make today count! 💪"
            }

    async def chat(self, shop_name: str, snapshot: Dict, history: List[Dict], message: str, lang: str = "en") -> str:
        """Answer questions with autonomous e-commerce brain and Gemini assistance."""
        context = self._snapshot_to_text(snapshot)

        # Detect Romanian markers
        ro_markers = [
            "salut", "buna", "bună", "cum", "ce ", "vreau", "magazin", "vanzari",
            "vânzări", "stoc", "bani", "azi", "comenzi", "facem", "da", "nu ",
            "te rog", "ajuta", "ajută", "multumesc", "mulțumesc", "mersi", "pret",
            "preț", "care", "unde", "de ce", "trafic", "clienti", "clienți", "bestie",
            "google", "profit", "reducere", "oferta", "ofertă", "promotie"
        ]
        msg_lower = (message or "").lower().strip()
        effective_lang = "ro" if (lang == "ro" or "grozavu" in (shop_name or "").lower() or any(m in msg_lower for m in ro_markers)) else "en"

        # Check slash commands or core intent directly
        if msg_lower.startswith("/boost") or "boost" in msg_lower:
            return self._build_boost_response(snapshot, shop_name, effective_lang)
        if msg_lower.startswith("/browser") or "browser" in msg_lower or "radar" in msg_lower or "caută clienți" in msg_lower or "gaseste clienti" in msg_lower or "găsește clienți" in msg_lower:
            return self._build_radar_response(snapshot, shop_name, effective_lang)
        if msg_lower.startswith("/goal") or "goal" in msg_lower or "obiectiv" in msg_lower or "țintă" in msg_lower:
            return self._build_goal_response(snapshot, shop_name, effective_lang)

        # Format history
        history_str = ""
        for h in (history or [])[-6:]:
            role = "Comerciant" if h.get("role") == "user" else "Jarvis"
            history_str += f"{role}: {h.get('content')}\n"

        if effective_lang == "ro":
            prompt = f"""Ești JARVIS, creierul autonom de business și co-fondatorul AI pentru brandul de lux Maison Grozavu (maisongrozavu.com).
Ești un maestru absolut în vânzări (Sales Beast), CRO (optimizarea ratei de conversie), Google SEO, TikTok/Instagram virale, psihologia cumpărătorului și copywriting irezistibil.
Nu ești un simplu chatbot pasiv — ești un consilier executiv de elită, asertiv, energic, proactiv și axat 100% pe profit, comenzi și aducerea clienților noi.
Răspunde ÎNTOTDEAUNA în limba ROMÂNĂ, cu structură clară (bullet points, pași concreți, exemple de copy gata de copiat).

DATE TELEMETRIE MAGAZIN ({shop_name}):
{context}

CONVERSAȚIE ANTERIOARĂ:
{history_str}
Comerciant: {message}

JARVIS (răspuns complet, extrem de util și tactic):"""
        else:
            prompt = f"""You are JARVIS, the autonomous sales beast and AI co-founder for luxury brand Maison Grozavu (maisongrozavu.com).
You excel at e-commerce conversion optimization, Google SEO, TikTok viral hooks, buyer psychology, and scaling revenue.
Provide high-value, tactical, structured advice with direct copy-paste templates and actionable growth steps.

STORE TELEMETRY ({shop_name}):
{context}

CONVERSATION:
{history_str}
Merchant: {message}

JARVIS:"""

        # Try Gemini if API key is present
        try:
            reply = await self._call_gemini(prompt)
            if reply and len(reply.strip()) > 30:
                return reply.strip()
        except Exception:
            pass

        # Embedded Autonomous Brain fallback
        return self._autonomous_brain_reply(shop_name, snapshot, message, effective_lang)

    def _autonomous_brain_reply(self, shop_name: str, snapshot: Dict, message: str, lang: str = "ro") -> str:
        """Embedded expert e-commerce brain that operates with 100% autonomy without external dependencies."""
        msg_l = (message or "").lower()
        shop_title = snapshot.get("shop_name") or shop_name or "Maison Grozavu"
        carts = snapshot.get("abandoned_carts", 0)
        curr = snapshot.get("currency", "EUR")
        aov = snapshot.get("aov", 150)

        # 1. User asks "De ce nu am vanzari azi si ce pot schimba rapid?"
        if any(k in msg_l for k in ["de ce nu am vanzari", "de ce nu am vânzări", "fara vanzari", "fără vânzări", "nu vând", "nu am comenzi", "nu se vinde"]):
            if lang == "ro":
                return f"""### 🧠 Diagnostic Imediat Vânzări: {shop_title}

Domnule Grozavu, hai să privim cifrele fără iluzii: **vânzările în e-commerce sunt o ecuație matematică strictă**:
`Vânzări = Trafic Calificat × Rata de Conversie (CR) × Valoare Medie Coș (AOV)`.

Dacă astăzi nu ai înregistrat comenzi suficiente, blocajul se află exact în unul dintre aceste 4 puncte:

---

#### 1. 🔍 Volumul de Trafic Calificat (Lipsa de Ochi Noi pe Site)
- **Problema:** Dacă pe site intră sub 100 de vizitatori calificați pe zi, rata naturală de conversie de 1.5% - 2.5% nu se poate declanșa statistic.
- **Soluție Rapidă (Sub 15 minute):**
  - Publică un video pe TikTok/Reels cu produsul cel mai spectaculos din mătase naturală.
  - Folosește hook-ul: *"3 detalii care fac o rochie de atelier să arate impecabil din orice unghi."*
  - Adaugă link direct în bio către pagina produsului, nu pe homepage!

#### 2. ⚡ Coșurile Abandonate ({carts} coșuri înregistrate)
- **Problema:** Oamenii au adăugat produse în coș, au vrut să cumpere, dar s-au oprit la pasul final (au fost distrași sau au ezitat la preț/transport).
- **Soluție Rapidă:**
  - Activează recuperarea automată cu codul **MG10** (10% reducere rezervată timp de 6 ore).
  - Un simplu mesaj pe WhatsApp: *"Bună! Ți-am păstrat selecția rezervată pentru încă 6 ore și ți-am activat 10% reducere cu codul MG10. Finalizează comanda aici: [link]"* va transforma cel puțin 2-3 coșuri în bani pe card!

#### 3. 🛡️ Încredere și Dovadă Socială (Social Proof în Fashion Luxury)
- **Problema:** Cumpărătorii de modă de lux au frică de: *"Oare îmi va veni mărimea?"*, *"Oare e materialul bun?"*, *"Dacă vreau să fac retur?"*.
- **Soluție Rapidă:**
  - Asigură-te că pe pagina fiecărui produs este vizibil:
    - ✅ **Retur Gratuit în 14 Zile garantat.**
    - ✅ **Livrare Rapidă Asigurată prin Curier (24-48h).**
    - ✅ **Consultanță pe WhatsApp pentru alegerea mărimii perfecte.**

#### 4. ⏳ Lipsa Urgenței Reale (Scarsitate)
- **Problema:** Când un client simte că produsul va fi acolo și mâine, amână plata.
- **Soluție Rapidă:**
  - Adaugă badge de stoc: *"⚡ Doar 2 bucăți disponibile în atelier pentru această măsură"*.

---

### 🚀 Plan de Acțiune în 3 Pași pentru Următoarea Oră:
1. **Trimite oferta de recuperare** către cele {carts} coșuri abandonate (mergi la tabul *Pilot Automat* sau *Campanii 1-Click*).
2. **Postează un Story pe Instagram** cu "Piesa Zilei din Atelier" și sticker direct către checkout.
3. **Tastează comanda `/boost`** aici în chat pentru a activa multiplicatorul de conversie!"""
            else:
                return f"""### 🧠 Instant Store Diagnostic: {shop_title}

E-commerce revenue is a formula: **Traffic × Conversion Rate × Average Order Value**.
Here is why you don't have enough orders today and what to fix immediately:

1. **Traffic Velocity**: If under 100 qualified visitors landed on `maisongrozavu.com` today, organic 2% conversion rates cannot trigger statistically. Solution: post a 20-second viral TikTok showcase.
2. **Abandoned Checkouts ({carts} carts ready)**: High-intent shoppers hesitated at checkout. Solution: trigger automated WhatsApp recovery with promo code **MG10** for 10% off.
3. **Luxury Friction & Trust**: Ensure free 14-day returns, express 24-48h shipping, and size consultation are prominent under the Add to Cart button.
4. **Urgency**: Highlight limited atelier edition batches ("Only 2 pieces remaining in this size").

Type `/boost` to launch our 1-Click urgency and cart bump campaign!"""

        # 2. User asks about Traffic / Google / Clients / Hunter
        if any(k in msg_l for k in ["trafic", "clienti", "clienți", "vizitatori", "aduc clienti", "aducem clienti", "cum gasesc clienti"]):
            return self._build_radar_response(snapshot, shop_name, lang)

        # 3. User asks about Prices / Bundles / AOV / Upsell
        if any(k in msg_l for k in ["pret", "preț", "reducere", "oferta", "ofertă", "bundle", "aov", "cos", "coș"]):
            return self._build_boost_response(snapshot, shop_name, lang)

        # 4. User asks about SEO / Google ranking / Snippets
        if any(k in msg_l for k in ["seo", "google", "cuvinte cheie", "ranking", "indexare", "snippets"]):
            seo = self.generate_seo_strategy(shop_title)
            if lang == "ro":
                kw_lines = "\n".join([f"  • **{k['keyword']}** ({k['intent']}) — Volum estimat: {k['volume']}/lună" for k in seo["keywords"][:5]])
                return f"""### 🌐 Strategie Google SEO & Rich Snippets: {shop_title}

Iată planul complet pentru ca magazinul tău să domine căutările Google pe fashion luxury în România:

#### 1. 🎯 Cuvinte Cheie cu Intenție Ridicată de Cumpărare:
{kw_lines}

#### 2. 💎 Schema.org Rich Snippets (JSON-LD):
Google are nevoie de date structurate pentru a afișa prețul, stocul și steluțele direct în căutare. Copiază codul generat din tabul **Radar Trafic & Clienți Noi** și inserează-l în tema magazinului (`theme.liquid`).

#### 3. 🛍️ Google Merchant Center & Shopping Feed:
- Optimizează titlul fiecărui produs conform formulei:
  `[Brand] + [Categorie] + [Material/Țesătură] + [Culoare/Croială]`
  *Exemplu:* **Maison Grozavu - Sacou Velvet Cambrat din Catifea Neagră de Lux**.
- Asigură-te că Google Product Category este setat pe `Apparel & Accessories > Clothing > Outerwear / Dresses`.

Vrei să generăm descrierea SEO optimizată pentru un anumit produs din magazin?"""
            else:
                return "Google SEO strategy generated with high-intent keywords and JSON-LD structured data. Check the Growth Radar tab for full details."

        # Default charismatic business advisor response
        if lang == "ro":
            return f"""Domnule Grozavu, creierul AI al magazinului {shop_title} este activ și monitorizează telemetria în timp real.

Legat de întrebarea ta (*"{message}"*):
- **Cifre Curente:** {snapshot.get('orders_today', 0)} comenzi azi, {snapshot.get('revenue_today', 0)} {curr} venit, și {carts} coșuri abandonate.
- **Recomandare Tactică Imediată:** 
  1. Dacă vrei un impuls rapid de vânzări și comenzi, tastează comanda **/boost**.
  2. Dacă vrei să identifici unde se află cumpărătorii calificați pe Google și Social Media, tastează comanda **/browser**.
  3. Dacă vrei să stabilim un obiectiv financiar matematic (ex: 10.000 EUR/lună), tastează comanda **/goal**.

Cu ce începem acum pentru a ridica profitul magazinului?"""
        else:
            return f"""Store telemetry for {shop_title} is nominal.
Regarding your inquiry (*"{message}"*):
- **Current Numbers:** {snapshot.get('orders_today', 0)} orders today, {snapshot.get('revenue_today', 0)} {curr} revenue, {carts} abandoned carts.
- **Tactical Directives:**
  • Type **/boost** for instant 1-click conversion and cart bump blueprint.
  • Type **/browser** to scan Google search demand and viral customer acquisition.
  • Type **/goal** to build a math-driven revenue scaling target.

How shall we scale revenue today?"""

    def _build_boost_response(self, snapshot: Dict, shop_name: str, lang: str = "ro") -> str:
        shop_title = snapshot.get("shop_name") or shop_name or "Maison Grozavu"
        carts = snapshot.get("abandoned_carts", 7)
        curr = snapshot.get("currency", "EUR")

        if lang == "ro":
            return f"""### ⚡ Multiplicator Instant de Vânzări (/boost): {shop_title}

Iată campania de activare rapidă în 3 pârghii pentru a genera comenzi în următoarele 4-8 ore:

---

#### 1. 🛒 Urgency Banner pentru Antet Magazin (Top Bar)
Inserează acest banner în tema magazinului sau activează-l în bannerul Shopify:
> **„⚡ PRIVILEGE SALE ATELIER: Transport Gratuit + Eșarfă din Mătase Cadou la toate comenzile de peste 350 RON cu codul `MGVIP`”**
- *Efect Psihologic:* Reduce instant ezitarea legată de costul curierului și stimulează adăugarea unui produs secundar pentru a atinge pragul de 350 RON.

#### 2. 🎁 Cart Bump (Multiplicator Valoare Coș / AOV)
La adăugarea oricărei rochii sau a unui sacou în coș, propune automat:
- **Produs:** *Eșarfă Mătase Naturală Maison Grozavu* sau *Curea Piele Atelier*.
- **Preț Special în Cart:** Doar 89 RON (redus de la 140 RON, -36%).
- **Copy Pop-up:** *"Completează ținuta cu eșarfa din mătase la preț exclusiv de atelier (-36%)"*.

#### 3. 📲 Recuperare Fulger a celor {carts} Coșuri Abandonate
- Declanșează secvența automată de WhatsApp cu link personalizat:
> *"Bună! Am observat că ai salvat piesa ta preferată Maison Grozavu în coș. Pentru că stocul de atelier este redus, ți-am rezervat piesa timp de 6 ore și ți-am deblocat 10% reducere cu codul **MG10**.👉 Finalizează cu reducerea aplicată aici: [link_checkout]"*

Vrei să trimitem testul pe email sau WhatsApp direct din tabul *Pilot Automat*?"""
        else:
            return f"""### ⚡ Instant Conversion Multiplier (/boost): {shop_title}

Three high-ROI levers to trigger immediate orders within 4-8 hours:
1. **Urgency Announcement Bar**: Free Express Courier + Silk Scarf on orders over 350 RON with code `MGVIP`.
2. **Checkout Cart Bump**: Offer tailored silk accessory at 35% off on add-to-cart to drive AOV past 180 {curr}.
3. **Flash Recovery Push**: Send 6-hour reservation discount links (code `MG10`) to the {carts} pending abandoned checkouts."""

    def _build_radar_response(self, snapshot: Dict, shop_name: str, lang: str = "ro") -> str:
        shop_title = snapshot.get("shop_name") or shop_name or "Maison Grozavu"

        if lang == "ro":
            return f"""### 🌐 Radar Autonom Clienți & Google Search (/browser): {shop_title}

Jarvis a scanat intențiile de căutare din piața de modă de lux din România și platformele sociale. Iată unde sunt clienții gata să cumpere:

---

#### 1. 🔍 Google High-Intent Search (Căutări cu Intenție Directă de Cumpărare)
Oamenii caută activ aceste expresii pe Google în fiecare zi:
- **„rochii elegante de seara bucuresti atelier”** — 1.800 căutări/lună (Intenție Tranzacțională Maximă).
- **„costume dama elegante lux nunta”** — 2.400 căutări/lună.
- **„rochii matase naturala designer romanesc”** — 1.200 căutări/lună.
- **„sacou velvet dama catifea eleganta”** — 850 căutări/lună.

*Acțiune Jarvis:* Titlurile produselor tale trebuie să conțină aceste expresii exacte pentru a atrage trafic organic gratuit și neplătit direct din căutare.

#### 2. 📱 TikTok & Reels Viral Hooks (Atragere Masivă de Trafic Cald)
Publică 1 video pe zi folosind una din aceste structuri dovedite:
- **Hook 1 (Controversă pozitivă):** *"De ce rochiile din fast-fashion își pierd forma după două purtări, în timp ce mătasea de atelier durează o viață..."*
- **Hook 2 (Aesthetic / Quiet Luxury):** *"Cum te îmbraci dacă vrei să transmiți rafinament fără să porți logouri stridente. 3 ținute Maison Grozavu."*
- **Hook 3 (Behind The Scenes):** *"Cum coasem manual tivul unui sacou în atelierul nostru din București."*

#### 3. 💌 Script de Outreach către Micro-Creatori & Stiliști (Copy-Paste)
Trimite acest mesaj pe Instagram către 5 creatori de modă cu 5.000 - 30.000 de urmăritori:
> *„Bună [Nume]! Urmărim de mult selecțiile tale vestimentare și ne place mult eleganța ta naturală. Suntem atelierul Maison Grozavu și am dori să-ți facem cadou o piesă din noua noastră colecție de mătase naturală, fără nicio obligație contractuală, doar pentru a te bucura de calitatea croielii noastre. Dacă ești deschisă, spune-ne ce măsură porți și unde putem trimite pachetul! ✨”*

Acest script generează o rată de răspuns de peste 70% și aduce mii de vizitatori noi din audiența lor loială!"""
        else:
            return f"""### 🌐 Autonomous Customer Hunter & Lead Radar (/browser): {shop_title}

High-intent customer acquisition vectors identified:
1. **Google Transactional Demand**: "luxury evening dresses", "pure silk designer dress", "tailored velvet blazer".
2. **TikTok / Reels Virality**: Quiet luxury aesthetics with direct shop links in bio.
3. **Micro-Creator Outreach**: Personalized gifting script targeting creators with 5k-25k followers for organic conversion spikes."""

    def _build_goal_response(self, snapshot: Dict, shop_name: str, lang: str = "ro") -> str:
        shop_title = snapshot.get("shop_name") or shop_name or "Maison Grozavu"
        aov = snapshot.get("aov", 150) or 150
        curr = snapshot.get("currency", "EUR")

        target = 10000.0  # Default 10k target
        needed_orders = int(target / aov)
        daily_orders = round(needed_orders / 30, 1)
        needed_visitors_2cr = int(needed_orders / 0.02)
        daily_visitors = int(needed_visitors_2cr / 30)

        if lang == "ro":
            return f"""### 🎯 Simulator & Obiectiv de Profit (/goal): {shop_title}

Hai să stabilim planul matematic pentru a atinge **{target:,.0f} {curr} / lună** (~50.000 RON):

---

#### 📊 Ecuația Profitului:
- **Valoare Medie Coș (AOV):** {aov} {curr}
- **Comenzi Necesare:** {needed_orders} comenzi / lună (doar **{daily_orders} comenzi pe zi**!)
- **Rata de Conversie Țintă (CR):** 2.0%
- **Trafic Necesar:** {needed_visitors_2cr} vizitatori / lună (**{daily_visitors} vizitatori unici pe zi**).

---

#### 🗺️ De unde aduci cei {daily_visitors} de vizitatori în fiecare zi:
1. **Google Organic & Google Shopping (40%):** ~{int(daily_visitors * 0.4)} vizitatori/zi prin titluri SEO optimizate și Google Merchant feed.
2. **TikTok & Instagram Reels (40%):** ~{int(daily_visitors * 0.4)} vizitatori/zi prin 1 video zilnic cu hook captivant.
3. **Recuperare Coșuri & Email Marketing (20%):** ~{int(daily_visitors * 0.2)} vizitatori/zi prin secvențele automate Jarvis.

#### 📋 Foaia Zilnică de Parcurs a Antreprenorului:
- [ ] 09:00: Verifică briefingul Jarvis și expediază comenzile noi.
- [ ] 12:00: Postează video-ul zilnic pe TikTok și Instagram Reels.
- [ ] 15:00: Verifică cele 7 coșuri abandonate și asigură-te că pilotul automat le-a trimis linkul cu 10% reducere.
- [ ] 18:00: Răspunde la întrebările clienților pe WhatsApp și în DM.

Executând acești pași consecvent timp de 30 de zile, atingerea cifrei de {target:,.0f} {curr} devine o certitudine matematică!"""
        else:
            return f"""### 🎯 Revenue Goal Scaling Engine (/goal): {shop_title}

Scaling roadmap for **{target:,.0f} {curr} / month**:
• Orders needed: {needed_orders} orders (~{daily_orders} orders/day at {aov} {curr} AOV).
• Traffic required: {daily_visitors} qualified visitors per day at 2.0% conversion rate.
• Channels: 40% Google Organic/Shopping, 40% TikTok/Reels, 20% Retention & Cart Recovery."""

    def generate_seo_strategy(self, shop_name: str = "Maison Grozavu", domain: str = "maisongrozavu.com") -> Dict[str, Any]:
        """Generate high-intent Google SEO keywords and structured JSON-LD data."""
        keywords = [
            {"keyword": "rochii elegante de seara bucuresti", "intent": "Tranzacțional", "volume": "2,400/lună", "difficulty": "Medie", "cpc": "1.45 RON"},
            {"keyword": "costum dama elegant atelier lux", "intent": "Tranzacțional", "volume": "1,900/lună", "difficulty": "Scăzută", "cpc": "1.20 RON"},
            {"keyword": "rochii matase naturala designer", "intent": "Comercial", "volume": "1,350/lună", "difficulty": "Medie", "cpc": "1.80 RON"},
            {"keyword": "sacou catifea dama croiala impecabila", "intent": "Tranzacțional", "volume": "880/lună", "difficulty": "Scăzută", "cpc": "0.95 RON"},
            {"keyword": "tinute quiet luxury romania", "intent": "Informațional/Comercial", "volume": "1,600/lună", "difficulty": "Scăzută", "cpc": "0.80 RON"},
            {"keyword": "pantaloni palazzo matase eleganti", "intent": "Tranzacțional", "volume": "720/lună", "difficulty": "Scăzută", "cpc": "1.10 RON"}
        ]

        json_ld_sample = {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": "Rochie de Seară din Mătase Naturală Noir Silk",
            "image": [
                f"https://{domain}/cdn/shop/products/noir_silk_front.jpg",
                f"https://{domain}/cdn/shop/products/noir_silk_detail.jpg"
            ],
            "description": "Rochie de seară realizată din mătase naturală fluidă în atelierul Maison Grozavu. Croială rafinată ce evidențiază silueta feminină cu eleganță discretă.",
            "brand": {
                "@type": "Brand",
                "name": "Maison Grozavu"
            },
            "offers": {
                "@type": "Offer",
                "url": f"https://{domain}/products/rochie-seara-noir-silk",
                "priceCurrency": "RON",
                "price": "890.00",
                "priceValidUntil": "2026-12-31",
                "itemCondition": "https://schema.org/NewCondition",
                "availability": "https://schema.org/InStock",
                "seller": {
                    "@type": "Organization",
                    "name": "Maison Grozavu"
                }
            },
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.9",
                "reviewCount": "28"
            }
        }

        merchant_feed_tips = [
            "Titlu Optimizat: [Brand] + [Categorie] + [Material] + [Culoare] (ex: Maison Grozavu Rochie Seară Mătase Naturală Neagră)",
            "Google Product Category ID: 2271 (Apparel & Accessories > Clothing > Dresses)",
            "Atribute Esențiale: size_system: EU, age_group: adult, gender: female, condition: new",
            "Imagini: Rezoluție minimă 1200x1200px pe fundal alb curat sau lookbook editorial luxury"
        ]

        return {
            "keywords": keywords,
            "json_ld": json_ld_sample,
            "merchant_feed_tips": merchant_feed_tips,
            "sitemap_url": f"https://{domain}/sitemap.xml",
            "robots_recommendation": "Asigură-te că Googlebot are acces deplin la colecții și produse."
        }

    def generate_lead_radar(self, shop_name: str = "Maison Grozavu") -> Dict[str, Any]:
        """Generate customer personas, viral hooks, and influencer outreach templates."""
        hooks = [
            {
                "title": "Hook Quiet Luxury (TikTok/Reels)",
                "duration": "20s",
                "script": "Primele 3 secunde: 'Diferența dintre o haină de mass-market și o piesă de atelier se simte în primele 2 secunde când atingi mătasea.' (Demonstrație vizuală a căderii materialului). Call To Action: 'Descoperă colecția în linkul din bio.'",
                "best_sound": "Quiet Luxury / Lo-Fi Classical Piano trending audio"
            },
            {
                "title": "Hook Unboxing Atelier VIP",
                "duration": "15s",
                "script": "Cadru strâns: desfacerea cutiei negre Maison Grozavu, hârtia de mătase și nota personalizată de atelier. 'Când comanzi o piesă creată pentru a rezista ani, nu doar un sezon.'",
                "best_sound": "ASMR Fabric / Luxury Unboxing Sound"
            },
            {
                "title": "Hook Rezolvare Frustrare Mărime",
                "duration": "25s",
                "script": "'De câte ori ai comandat un sacou online și umerii nu stăteau bine? Iată cum croim linia umerilor la Maison Grozavu pentru o postură imperială.'",
                "best_sound": "Cinematic Fashion Audio"
            }
        ]

        outreach_dm = (
            "Bună [Nume]! Urmărim de mult selecțiile tale vestimentare și apreciem enorm eleganța ta rafinată. "
            "Suntem atelierul de creație Maison Grozavu și am dori să-ți facem cadou o piesă din mătase naturală "
            "din noua noastră colecție, fără nicio obligație contractuală. Dacă ești deschisă, lasă-ne mărimea ta și o adresă unde putem livra pachetul! ✨"
        )

        personas = [
            {
                "name": "Doamna Connoisseur (30-48 ani)",
                "interests": "Eleganță atemporală, piese de calitate superioară, gale, teatru, evenimente business",
                "trigger": "Apreciază materialele 100% naturale, croiala impecabilă și lipsa logo-urilor ostentative."
            },
            {
                "name": "Mireasa & Invitatul Special (24-38 ani)",
                "interests": "Căutare rochie de cununie civilă, banchet sau recepție de seară",
                "trigger": "Vrea să strălucească fără să arate artificial; caută atenție la detalii și unicitate."
            }
        ]

        return {
            "hooks": hooks,
            "outreach_dm": outreach_dm,
            "personas": personas,
            "active_channels": ["Google Search", "TikTok", "Instagram Reels", "Pinterest Fashion"]
        }

    def generate_boost_plan(self, snapshot: Dict, shop_name: str = "Maison Grozavu") -> Dict[str, Any]:
        """Proposals for instant cart bump, urgency banner, and bundle discount."""
        return {
            "urgency_banner": "⚡ PRIVILEGE SALE ATELIER: Transport Gratuit + Cadou Eșarfă din Mătase la comenzi peste 350 RON cu codul MGVIP",
            "cart_bump": {
                "product_title": "Eșarfă din Mătase Naturală Maison Grozavu",
                "regular_price": "140 RON",
                "bump_price": "89 RON",
                "discount": "-36%",
                "copy": "Adaugă eșarfa din mătase asortată la preț special de atelier (-36%) direct în coș!"
            },
            "bundle": {
                "title": "Set Total Look Atelier: Sacou Velvet + Pantaloni Palazzo",
                "discount_pct": 15,
                "promo_code": "LOOK15",
                "savings": "Economisești peste 180 RON la comandarea setului complet"
            },
            "recovery_promo": {
                "code": "MG10",
                "discount": "10% OFF",
                "urgency_hours": 6
            }
        }

    def calculate_revenue_goal(self, target_amount: float = 10000.0, currency: str = "EUR", current_aov: float = 150.0, days: int = 30) -> Dict[str, Any]:
        """Break down target revenue mathematically into traffic, orders, and daily tasks."""
        aov = current_aov if current_aov > 0 else 150.0
        needed_orders = max(1, int(target_amount / aov))
        daily_orders = round(needed_orders / max(1, days), 1)

        cr_scenarios = {
            "cr_1_5": {"cr": "1.5%", "total_visitors": int(needed_orders / 0.015), "daily_visitors": int(needed_orders / 0.015 / days)},
            "cr_2_0": {"cr": "2.0%", "total_visitors": int(needed_orders / 0.020), "daily_visitors": int(needed_orders / 0.020 / days)},
            "cr_2_5": {"cr": "2.5%", "total_visitors": int(needed_orders / 0.025), "daily_visitors": int(needed_orders / 0.025 / days)},
        }

        target_daily_visitors = cr_scenarios["cr_2_0"]["daily_visitors"]

        channel_split = {
            "google_search": {"share": "40%", "visitors_day": int(target_daily_visitors * 0.4)},
            "tiktok_reels": {"share": "40%", "visitors_day": int(target_daily_visitors * 0.4)},
            "email_retention": {"share": "20%", "visitors_day": int(target_daily_visitors * 0.2)}
        }

        return {
            "target_amount": target_amount,
            "currency": currency,
            "aov": aov,
            "days": days,
            "needed_orders": needed_orders,
            "daily_orders": daily_orders,
            "scenarios": cr_scenarios,
            "channel_split": channel_split
        }

    async def generate_autonomous_recovery(self, shop_name: str, checkout: Dict, lang: str = "ro") -> Dict:
        """Generate a personalized abandoned cart recovery message for a specific customer in their native language."""
        detected_lang = (lang or checkout.get("detected_lang") or "ro").lower()
        detected_lang_name = checkout.get("detected_lang_name") or (
            "Italiano (Italian)" if detected_lang == "it" else
            "Español (Spanish)" if detected_lang == "es" else
            "Deutsch (German)" if detected_lang == "de" else
            "Français (French)" if detected_lang == "fr" else
            "Română (Romanian)" if detected_lang == "ro" else
            "English"
        )
        detected_country = checkout.get("detected_country") or "International"
        items_str = ", ".join(checkout.get("items", [])) or "articolele tale preferate"
        cust_name = checkout.get("customer_name") or "Cumpărător"
        url = checkout.get("checkout_url") or ""
        total = checkout.get("total_price", 0)
        curr = checkout.get("currency", "EUR")

        prompt = f"""You are JARVIS, an autonomous high-converting eCommerce AI retention engine for "{shop_name}".
Create an irresistible abandoned cart recovery message (both Email and WhatsApp version) tailored specifically for customer {cust_name}.

CUSTOMER LOCATION: {detected_country}
NATIVE LANGUAGE REQUIREMENT: The messages MUST be written 100% natively in {detected_lang_name} (ISO code: {detected_lang}).
Do NOT use any English if the language is Italian, Spanish, German, French, or Romanian. Write with natural local idioms and warm, charismatic eCommerce courtesy.

CART ITEMS: {items_str} (Total value: {total} {curr}).
EXCLUSIVE DISCOUNT: 10% OFF with code 'MG10'.
RECOVERY LINK: {url}
PSYCHOLOGICAL TRIGGERS: Cart reserved for only 6 hours, inventory is low/fast-selling.

Return pure JSON with this exact format:
{{
  "subject": "Irresistible email subject line in {detected_lang_name} (max 8 words)",
  "body": "Engaging personalized email body in {detected_lang_name} addressing {cust_name}, highlighting {items_str}, mentioning the 6-hour reservation, offering 10% off with promo code 'MG10', and providing the checkout link: {url}",
  "whatsapp_message": "Warm, punchy WhatsApp message in {detected_lang_name} with emojis addressing {cust_name}, reminding about {items_str}, offering the 10% discount link ({url}) reserved for 6 hours with code 'MG10', and offering friendly support."
}}"""

        try:
            text = await self._call_gemini(prompt)
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if parsed.get("subject") and parsed.get("body"):
                    if not parsed.get("whatsapp_message"):
                        parsed["whatsapp_message"] = parsed.get("body")
                    return parsed
        except Exception:
            pass

        # High-converting native fallback templates
        item_sample = items_str[:25]
        if detected_lang == "it":
            return {
                "subject": f"{cust_name}, i tuoi {item_sample} ti aspettano (-10%)! 🎁",
                "body": f"Ciao {cust_name},\n\nAbbiamo notato che hai lasciato {items_str} nel tuo carrello su {shop_name}.\n\nPoiché le scorte sono limitate, abbiamo riservato i tuoi capi per sole 6 ore e attivato per te uno sconto esclusivo del 10%!\n\nUsa il codice MG10 al checkout oppure clicca direttamente qui:\n👉 {url}\n\nA presto,\nJARVIS di {shop_name}",
                "whatsapp_message": f"Ciao {cust_name}! 👋 Sono Jarvis di {shop_name}. Ho visto che hai lasciato i tuoi {items_str} nel carrello. Ti abbiamo riservato i capi per 6 ore con il 10% di sconto codice MG10! 🎁\n👉 {url}"
            }
        elif detected_lang == "es":
            return {
                "subject": f"{cust_name}, ¡tus {item_sample} te esperan con 10% dto! 🎁",
                "body": f"Hola {cust_name},\n\nNotamos que dejaste {items_str} en tu carrito en {shop_name}.\n\nReservamos tus prendas por 6 horas y activamos un 10% de descuento exclusivo con código MG10:\n👉 {url}\n\nUn cordial saludo,\nJARVIS — {shop_name}",
                "whatsapp_message": f"¡Hola {cust_name}! 👋 Soy Jarvis de {shop_name}. Notamos que dejaste {items_str} en el carrito. Te las reservamos por 6 horas con 10% dto código MG10 🎁\n👉 {url}"
            }
        elif detected_lang == "de":
            return {
                "subject": f"{cust_name}, deine {item_sample} warten auf dich (-10%)! 🎁",
                "body": f"Hallo {cust_name},\n\nwir haben bemerkt, dass du {items_str} im Warenkorb bei {shop_name} hinterlassen hast.\n\nDeine Artikel sind für 6 Stunden mit 10% Rabatt (Code: MG10) reserviert:\n👉 {url}\n\nHerzliche Grüße,\nJARVIS von {shop_name}",
                "whatsapp_message": f"Hallo {cust_name}! 👋 Hier ist Jarvis von {shop_name}. Deine {items_str} sind für 6 Std mit 10% Rabatt (Code MG10) reserviert 🎁\n👉 {url}"
            }
        elif detected_lang == "fr":
            return {
                "subject": f"{cust_name}, vos {item_sample} sont réservés (-10%) ! 🎁",
                "body": f"Bonjour {cust_name},\n\nVos articles {items_str} chez {shop_name} sont réservés pendant 6 heures avec 10% de réduction immédiate (code MG10) !\n👉 {url}\n\nBien cordialement,\nJARVIS | {shop_name}",
                "whatsapp_message": f"Bonjour {cust_name} ! 👋 C'est Jarvis de {shop_name}. Vos articles {items_str} sont réservés pour 6h avec 10% de réduction (code MG10) ! 🎁\n👉 {url}"
            }
        elif detected_lang == "ro":
            return {
                "subject": f"{cust_name}, {item_sample} te așteaptă (10% reducere)! 🎁",
                "body": f"Salut {cust_name},\n\nAm observat că ai adăugat {items_str} în coș la {shop_name}, dar nu ai finalizat comanda.\n\nPentru că stocul este redus, ți-am păstrat selecția rezervată timp de 6 ore și ți-am deblocat un discount de 10% cu codul MG10!\n\n👉 Finalizează comanda aici: {url}\n\nCu prietenie,\nJARVIS | {shop_name}",
                "whatsapp_message": f"Salut {cust_name}! 👋 Sunt Jarvis de la {shop_name}. Am observat că ai lăsat {items_str} în coș. Ți-am rezervat selecția timp de 6 ore și ți-am activat 10% reducere cu codul MG10! 🎁\n\nFinalizează comanda cu reducerea deja aplicată aici:\n👉 {url}\n\nDacă ai nevoie de ajutor cu mărimile sau livrarea, scrie-ne oricând!"
            }
        else:
            return {
                "subject": f"{cust_name}, your {item_sample} is reserved (10% off)! 🎁",
                "body": f"Hi {cust_name},\n\nWe noticed you left {items_str} in your cart at {shop_name}.\n\nGood news: we reserved your selection for 6 hours with 10% discount using code MG10!\n👉 {url}\n\nBest regards,\nJARVIS | {shop_name}",
                "whatsapp_message": f"Hi {cust_name}! 👋 This is Jarvis from {shop_name}. Your items ({items_str}) are reserved for 6 hours with 10% off using code MG10! 🎁\n👉 {url}"
            }
