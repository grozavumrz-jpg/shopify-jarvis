# 🧠 Jarvis for Shopify — AI Growth Assistant

Asistent AI complet pentru magazine Shopify, integrat direct în Shopify Admin (Embedded App) cu abonament recurent de **$9.99/lună**.

---

## 🚀 Cum îl pui pe Shopify & Railway (Pas cu pas)

### Pasul 1: Înregistrează Aplicația în Shopify Partner Dashboard
1. Intră în [Shopify Partners](https://partners.shopify.com/) (contul tău `GrozavuShop`).
2. În meniul din stânga mergi la **Apps** (sau **App distribution**) -> **Create app** -> **Create app manually**.
3. Pune-i numele: `Jarvis AI Store Assistant`.
4. Copiază **Client ID** (API Key) și **Client Secret** (API Secret).

### Pasul 2: Conectează la Railway
1. În proiectul tău existent pe [Railway](https://railway.com/) (unde ai deja baza de date `Postgres` activă):
2. Apasă **+ New** -> **GitHub Repo** (sau încarcă acest folder `shopify-jarvis`) SAU folosește Railway CLI (`railway up`).
3. În serviciul creat pe Railway, mergi la **Variables** și adaugă:
   - `SHOPIFY_API_KEY`: Client ID-ul din Shopify Partners
   - `SHOPIFY_API_SECRET`: Client Secret-ul din Shopify Partners
   - `DATABASE_URL`: `${{Postgres.DATABASE_URL}}` (Railway îl conectează automat la baza ta Postgres!)
   - `GEMINI_API_KEY`: Cheia ta Gemini (`AQ.Ab8RN6...`)
   - `APP_URL`: URL-ul generat de Railway (ex: `https://jarvis-shopify-production.up.railway.app`)
4. În tab-ul **Settings** din Railway -> **Networking** -> Apasă **Generate Domain** dacă nu ai deja domeniu public.

### Pasul 3: Configurează URL-urile în Shopify Partner Dashboard
În ecranul aplicației din Shopify Partners:
- **App URL**: `https://<domeniul-tau-railway>.up.railway.app`
- **Allowed redirection URL(s)**:
  `https://<domeniul-tau-railway>.up.railway.app/auth/callback`

### Pasul 4: Testează pe Magazinul tău de Test
1. În Shopify Partners -> **Stores** -> Creează un **Development Store** (dacă nu ai deja).
2. Deschide aplicația din Partners -> Selectează **Test your app** -> alege magazinul de test.
3. Se deschide ecranul de permisiuni Shopify:
   - Comenzi (Orders)
   - Produse (Products)
   - Clienți (Customers)
   - Coșuri abandonate (Checkouts)
4. Apeși **Install** și gata! Jarvis apare direct în meniul admin al magazinului!

---

## 🌟 Funcționalități Incluse
- **Briefing Zilnic Inteligent**: Rezumat zilnic cu vânzări, obiective și motivație.
- **Detector Coșuri Abandonate & Stoc Critic**: Alerte instant pentru oportunități de vânzare pierdute.
- **Sfat de Trafic Recomandat**: Idei testate pentru TikTok / Instagram / Email.
- **Sarcini Prioritizate (Action Plan)**: Listă de to-do inteligentă cu checkbox-uri.
- **Chat Personalizat cu Jarvis**: AI care citește comenzile și produsele în timp real.
- **Pagină de Abonament**: Pregătit pentru Shopify Billing API ($9.99/lună, 7 zile trial).
