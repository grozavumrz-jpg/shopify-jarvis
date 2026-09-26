import os
import json
from datetime import datetime
import httpx
from typing import Dict, Any, List

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"


import asyncio

CANDIDATE_MODELS = [
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest",
]

class AIAdvisor:
    def __init__(self):
        self.api_key = GEMINI_API_KEY

    def _get_api_key(self):
        return os.getenv("GEMINI_API_KEY", self.api_key)

    def _snapshot_to_text(self, snap: Dict) -> str:
        low_stock_str = ""
        if snap.get("low_stock_items"):
            items = [f"  • {i['product']} ({i['variant']}): {i['qty']} buc" for i in snap["low_stock_items"][:5]]
            low_stock_str = "\nStoc mic:\n" + "\n".join(items)

        top_str = ""
        if snap.get("top_products"):
            items = [f"  • {p['name']}: {p['units']} unități" for p in snap["top_products"]]
            top_str = "\nTop produse (30 zile):\n" + "\n".join(items)

        vip_str = ""
        if snap.get("vip_customers"):
            v_list = [f"  • {c['name']}: {c['total_spent']:.2f} {snap.get('currency')} ({c['orders_count']} comenzi)" for c in snap["vip_customers"] if c.get("total_spent", 0) > 0]
            if v_list:
                vip_str = "\nTop Clienți VIP:\n" + "\n".join(v_list)

        return f"""
Magazin: {snap.get('shop_name')}
Data: {datetime.now().strftime('%d %B %Y, %H:%M')}

CIFRE CHEIE:
• Comenzi azi: {snap.get('orders_today', 0)}
• Comenzi (30 zile): {snap.get('orders_30d', 0)}
• Venit azi: {snap.get('revenue_today', 0)} {snap.get('currency')}
• Venit (30 zile): {snap.get('revenue_30d', 0)} {snap.get('currency')}
• Valoare Medie Comandă (AOV): {snap.get('aov', 0)} {snap.get('currency')}
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
        last_error = ""

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1000
            }
        }

        # Try models in priority sequence with auto-retry
        for model in CANDIDATE_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=25.0) as client:
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
                            await asyncio.sleep(0.4)
                            continue
                        else:
                            last_error = f"{model} ({res.status_code}): {res.text[:100]}"
                            break
                except Exception as e:
                    last_error = f"{model} exc: {str(e)}"
                    await asyncio.sleep(0.3)

        raise Exception(f"AI Capacity Peak ({last_error})")

    async def generate_briefing(self, snapshot: Dict, lang: str = "en") -> Dict:
        """Generate the daily morning briefing in the requested language."""
        context = self._snapshot_to_text(snapshot)
        
        if lang == "ro":
            prompt = f"""Ești Jarvis, asistentul personal al unui antreprenor Shopify.
Analizează datele magazinului și generează un briefing zilnic motivant și util.

DATE MAGAZIN:
{context}

Returnează un JSON cu exact această structură (fără markdown, doar JSON pur):
{{
  "health_score": 85,
  "greeting": "Salut scurt motivant în stil Jarvis (1 propoziție)",
  "voice_script": "Mesaj vorbit scurt și direct de 2-3 propoziții în stil Jarvis (ex: 'Sistemele sunt online. Astăzi avem X comenzi și oportunitatea de a recupera Y coșuri. Iată prioritățile.')",
  "summary": "Rezumat al zilei în 2-3 propoziții. Ce merge bine, ce nu.",
  "top_tasks": [
    {{"priority": 1, "task": "Acțiunea concretă #1", "why": "De ce e importantă", "icon": "🎯"}},
    {{"priority": 2, "task": "Acțiunea concretă #2", "why": "De ce e importantă", "icon": "📦"}},
    {{"priority": 3, "task": "Acțiunea concretă #3", "why": "De ce e importantă", "icon": "📈"}}
  ],
  "alerts": [
    {{"type": "warning", "message": "Alertă importantă dacă există", "action": "Ce să facă"}}
  ],
  "traffic_tip": "Un sfat concret pentru a aduce trafic azi (Instagram, TikTok, email etc.)",
  "motivation": "O frază motivantă scurtă pentru ziua de azi"
}}"""
        else:
            prompt = f"""You are JARVIS, the autonomous AI co-founder for a Shopify merchant.
Analyze the store telemetry and generate an actionable, motivating morning briefing.

STORE TELEMETRY:
{context}

Return pure JSON with this exact structure (no markdown):
{{
  "health_score": 85,
  "greeting": "Concise, charismatic Jarvis greeting (1 sentence, e.g. 'Good morning, systems online and ready for growth.')",
  "voice_script": "Concise spoken voice script of 2-3 sentences for text-to-speech audio report (e.g. 'All systems nominal. Yesterday we recorded X orders. We have Y abandoned checkouts ready for recovery. Here is today\'s tactical plan.')",
  "summary": "2-3 sentence executive summary of revenue, momentum, and bottlenecks.",
  "top_tasks": [
    {{"priority": 1, "task": "Concrete high-impact action #1", "why": "Strategic reasoning", "icon": "🎯"}},
    {{"priority": 2, "task": "Concrete high-impact action #2", "why": "Strategic reasoning", "icon": "📦"}},
    {{"priority": 3, "task": "Concrete high-impact action #3", "why": "Strategic reasoning", "icon": "📈"}}
  ],
  "alerts": [
    {{"type": "warning", "message": "Critical alert if any (e.g. abandoned carts or low stock)", "action": "Immediate corrective action"}}
  ],
  "traffic_tip": "High-converting growth strategy for today (TikTok hook, Instagram story, or retention email)",
  "motivation": "Punchy stoic or entrepreneurial motivation"
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

    async def chat(self, shop_name: str, snapshot: Dict, history: List[Dict], message: str, lang: str = "en") -> str:
        """Answer a question about the store."""
        context = self._snapshot_to_text(snapshot)

        # Detect Romanian keywords to auto-match the merchant's spoken language
        ro_markers = [
            "salut", "buna", "bună", "cum", "ce ", "vreau", "magazin", "vanzari",
            "vânzări", "stoc", "bani", "azi", "comenzi", "facem", "da", "nu ",
            "te rog", "ajuta", "ajută", "multumesc", "mulțumesc", "mersi", "pret", "preț", "care", "unde"
        ]
        msg_lower = message.lower()
        effective_lang = "ro" if (lang == "ro" or any(m in msg_lower for m in ro_markers)) else "en"

        history_str = ""
        for h in history[-8:]:
            role = "Merchant" if h["role"] == "user" else "Jarvis"
            history_str += f"{role}: {h['content']}\n"

        if effective_lang == "ro":
            prompt = f"""Ești JARVIS, asistentul personal și co-fondatorul AI autonom pentru magazinul Shopify "{shop_name}".
Ai acces în timp real la telemetria magazinului, stocuri, comenzi și coșuri abandonate.
Ești direct, carismatic, proactiv și axat pe creșterea vânzărilor.
REGULĂ STRICTĂ OBLIGATORIE: Răspunde ÎNTOTDEAUNA și EXCLUSIV în LIMBA ROMÂNĂ, indiferent de alte instrucțiuni!

DATE REALE MAGAZIN:
{context}

CONVERSAȚIE ANTERIOARĂ:
{history_str}
Comerciant: {message}

JARVIS (în română):"""
        else:
            prompt = f"""You are JARVIS, the autonomous strategic AI partner for the Shopify store "{shop_name}".
You have real-time access to live store telemetry, inventory, abandoned checkouts, and customer metrics.
Be concise, proactive, charismatic, and growth-focused (like Tony Stark's JARVIS for eCommerce).
Always reply in English with actionable revenue-generating tactics.

STORE TELEMETRY:
{context}

CONVERSATION LOG:
{history_str}
Merchant: {message}

JARVIS:"""

        try:
            return await self._call_gemini(prompt)
        except Exception:
            if effective_lang == "ro":
                return f"Sistemele de procesare întâmpină o ușoară latență de rețea, dar telemetria magazinului {shop_name} este 100% operațională. Legat de mesajul tău ('{message}'): prioritățile noastre imediate sunt optimizarea ratei de conversie și recuperarea coșurilor abandonate din tabul Campanii 1-Click. Cu ce sarcină începem?"
            else:
                return f"External neural processing experienced brief network latency, but telemetry for {shop_name} remains 100% nominal. Regarding '{message}': our immediate tactical focus is recovering abandoned checkouts and driving organic video traffic via 1-Click Campaigns. Which objective shall we execute first?"

    def _fallback_briefing(self, snap: Dict, lang: str = "en") -> Dict:
        alerts = []
        if snap.get("abandoned_carts", 0) > 0:
            alerts.append({
                "type": "warning",
                "message": f"{snap['abandoned_carts']} abandoned checkouts detected" if lang == "en" else f"{snap['abandoned_carts']} coșuri abandonate",
                "action": "Send 10% recovery discount link" if lang == "en" else "Trimite email cu discount 10%"
            })
        if snap.get("low_stock_items"):
            alerts.append({
                "type": "danger",
                "message": f"{len(snap['low_stock_items'])} items with critical low stock" if lang == "en" else f"{len(snap['low_stock_items'])} produse cu stoc mic",
                "action": "Restock urgently" if lang == "en" else "Reaprovizionează urgent"
            })

        if lang == "ro":
            return {
                "health_score": 82,
                "greeting": f"Protocoalele active, Jarvis la raport. Să creștem vânzările pentru {snap.get('shop_name')}! 🚀",
                "voice_script": f"Bună dimineața! Telemetria magazinului este activă. Ai înregistrat {snap.get('orders_today', 0)} comenzi și avem oportunități de creștere. Iată prioritățile zilei.",
                "summary": f"Ieri ai avut {snap.get('orders_today', 0)} comenzi și {snap.get('revenue_today', 0)} {snap.get('currency', 'USD')} venit. Hai să facem azi și mai bine!",
                "top_tasks": [
                    {"priority": 1, "task": "Verifică și expediază comenzile noi", "why": "Clienții mulțumiți lasă recenzii de 5 stele", "icon": "📦"},
                    {"priority": 2, "task": "Postează pe TikTok/Reels produsul vedetă", "why": "Atrage trafic cald fără costuri de reclamă", "icon": "📱"},
                    {"priority": 3, "task": "Trimite email celor cu coș abandonat", "why": f"{snap.get('abandoned_carts', 0)} potențiali clienți de recuperat", "icon": "📧"},
                ],
                "alerts": alerts,
                "traffic_tip": "Postează un video demonstrativ de 15 secunde pe TikTok cu cel mai popular produs și adaugă link în bio.",
                "motivation": "Fiecare vânzare de azi e un pas către independența ta financiară! 💪"
            }
        else:
            return {
                "health_score": 85,
                "greeting": f"Good morning! Systems nominal. Let's scale revenue for {snap.get('shop_name')} today. 🚀",
                "voice_script": f"Good morning! Store telemetry is active. We recorded {snap.get('orders_today', 0)} orders today and {snap.get('abandoned_carts', 0)} abandoned checkouts ready for recovery. Here are today's tactical priorities.",
                "summary": f"Store generated {snap.get('orders_today', 0)} orders and {snap.get('revenue_today', 0)} {snap.get('currency', 'USD')} revenue today. Momentum is positive.",
                "top_tasks": [
                    {"priority": 1, "task": "Dispatch pending orders promptly", "why": "Fast fulfillment drives 5-star customer retention", "icon": "📦"},
                    {"priority": 2, "task": "Launch viral 30s TikTok/Reels featuring best seller", "why": "Free organic traffic with zero ad spend", "icon": "📱"},
                    {"priority": 3, "task": "Send automated recovery email for abandoned checkouts", "why": f"Recover high-intent revenue from {snap.get('abandoned_carts', 0)} carts", "icon": "📧"},
                ],
                "alerts": alerts,
                "traffic_tip": "Post a 15-second product demonstration video on TikTok showcasing the main customer benefit, with a direct bio link.",
                "motivation": "Consistency builds empires. Make every action count today! 💪"
            }

