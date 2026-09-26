import os
import json
from datetime import datetime
import httpx
from typing import Dict, Any, List

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"


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

        return f"""
Magazin: {snap.get('shop_name')}
Data: {datetime.now().strftime('%d %B %Y, %H:%M')}

CIFRE CHEIE:
• Comenzi azi: {snap.get('orders_today', 0)}
• Comenzi (30 zile): {snap.get('orders_30d', 0)}
• Venit azi: {snap.get('revenue_today', 0)} {snap.get('currency')}
• Venit (30 zile): {snap.get('revenue_30d', 0)} {snap.get('currency')}
• Coșuri abandonate (7 zile): {snap.get('abandoned_carts', 0)}
• Clienți noi (24h): {snap.get('new_customers_24h', 0)}
{top_str}
{low_stock_str}
""".strip()

    async def _call_gemini(self, prompt: str) -> str:
        key = self._get_api_key()
        url = f"{API_URL}?key={key}"
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                raise Exception(f"Google AI Status {res.status_code}: {res.text}")
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
            return ""

    async def generate_briefing(self, snapshot: Dict) -> Dict:
        """Generate the daily morning briefing."""
        context = self._snapshot_to_text(snapshot)
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

        try:
            text = await self._call_gemini(prompt)
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass

        return self._fallback_briefing(snapshot)

    async def chat(self, shop_name: str, snapshot: Dict, history: List[Dict], message: str) -> str:
        """Answer a question about the store."""
        context = self._snapshot_to_text(snapshot)

        history_str = ""
        for h in history[-8:]:
            role = "Tu" if h["role"] == "user" else "Jarvis"
            history_str += f"{role}: {h['content']}\n"

        prompt = f"""Ești Jarvis, asistentul personal al magazinului Shopify "{shop_name}".
Ai acces la datele reale ale magazinului. Ești direct, prietenos, practic.
Răspunzi ÎNTOTDEAUNA în română, cu sfaturi concrete de creștere a vânzărilor.

DATE MAGAZIN:
{context}

CONVERSAȚIE:
{history_str}
Tu: {message}

Jarvis:"""

        try:
            return await self._call_gemini(prompt)
        except Exception as e:
            return f"❌ Eroare AI: {str(e)}"

    def _fallback_briefing(self, snap: Dict) -> Dict:
        alerts = []
        if snap.get("abandoned_carts", 0) > 0:
            alerts.append({
                "type": "warning",
                "message": f"{snap['abandoned_carts']} coșuri abandonate",
                "action": "Trimite email cu discount 10%"
            })
        if snap.get("low_stock_items"):
            alerts.append({
                "type": "danger",
                "message": f"{len(snap['low_stock_items'])} produse cu stoc mic",
                "action": "Reaprovizionează urgent"
            })

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
