import os
import json
from datetime import datetime
import google.generativeai as genai
from typing import Dict, Any, List

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)


class AIAdvisor:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-flash")

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

    async def generate_briefing(self, snapshot: Dict) -> Dict:
        """Generate the daily morning briefing."""
        context = self._snapshot_to_text(snapshot)
        prompt = f"""Ești Jarvis, asistentul personal al unui antreprenor Shopify.
Analizează datele magazinului și generează un briefing zilnic motivant și util.

DATE MAGAZIN:
{context}

Returnează un JSON cu exact această structură (fără markdown, doar JSON pur):
{{
  "greeting": "Salut scurt motivant (1 propoziție)",
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
            resp = self.model.generate_content(prompt)
            text = resp.text.strip()
            # Extract JSON
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception as e:
            pass

        # Fallback briefing
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
Răspunzi ÎNTOTDEAUNA în română, cu sfaturi concrete.

DATE MAGAZIN:
{context}

CONVERSAȚIE:
{history_str}
Tu: {message}

Jarvis:"""

        try:
            resp = self.model.generate_content(prompt)
            return resp.text.strip()
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
            "greeting": f"Bună dimineața! Să facem {snap.get('shop_name')} să crească azi! 🚀",
            "summary": f"Ieri ai avut {snap['orders_today']} comenzi și {snap['revenue_today']} {snap['currency']} venit. Hai să facem azi și mai bine!",
            "top_tasks": [
                {"priority": 1, "task": "Verifică și răspunde la toate comenzile noi", "why": "Clienții fericiți revin", "icon": "📦"},
                {"priority": 2, "task": "Postează pe Instagram/TikTok un produs top", "why": "Trafic organic gratuit", "icon": "📱"},
                {"priority": 3, "task": "Trimite email clienților cu coș abandonat", "why": f"{snap['abandoned_carts']} potențiali clienți de recuperat", "icon": "📧"},
            ],
            "alerts": alerts,
            "traffic_tip": "Postează un Reel/TikTok cu un produs best-seller + story cu testimonial de client. Cel mai ieftin trafic.",
            "motivation": "Fiecare vânzare de azi e un client fidel de mâine! 💪"
        }
