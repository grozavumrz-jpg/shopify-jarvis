# Jarvis for Shopify — Grozavu (maisongrozavu.com)

Asistent pentru magazinul Shopify: urmărește coșurile abandonate (doar clienți cu acord de marketing), trimite mulțumiri după livrare, generează feed-ul Google Merchant din produsele reale, verifică DNS-ul pentru emailuri și răspunde în chat pe baza datelor reale din Shopify.

**Regula de bază:** Jarvis nu inventează nimic. Dacă nu are date de la Shopify, arată „indisponibil”, nu cifre false.

---

## Ce rulează automat (la fiecare 5 minute, cât timp serverul e pornit)
1. Verifică comenzile noi și oprește mesajele pentru coșurile care au devenit comenzi.
2. Coșuri abandonate, maximum 3 mesaje per coș: la 30 de minute (fără reducere), la 4 ore și la 24 de ore (cu codul MG10). Se trimit **doar** dacă:
   - clientul are acord de marketing în Shopify (pentru email; separat pentru WhatsApp);
   - nu s-a dezabonat;
   - nu e între 21:00 și 09:00, ora Spaniei;
   - nu depășește limitele de frecvență.
3. După livrare (5 zile): mulțumire + cod pentru următoarea comandă. Reducerea nu e condiționată de o recenzie, iar mesajul trece prin aceleași reguli de acord.
4. Feed-ul Google Merchant: `https://<app>/feeds/google-merchant.xml`. Conține câte un articol pe fiecare variantă (culoare/mărime) și doar produse active, publicate, cu poză și preț.
5. SEO: Jarvis **doar propune** titluri, descrieri și texte alternative pentru imagini. Nu modifică nimic în Shopify fără aprobarea ta.

## Pași o singură dată (obligatorii)
0. **Conectează Shopify (din 2026, prin Dev Dashboard).**
   - Domeniul intern al magazinului este `grozavushop.myshopify.com` (nu `maisongrozavu.myshopify.com`). Pune-l în Render → `SHOP_DOMAIN`.
   - Aplicația „Jarvis” există deja în Dev Dashboard (dev.shopify.com) și e instalată pe `grozavushop`.
   - Scopuri necesare: `read_orders`, `read_products`, `read_customers`, `read_inventory`, plus acces la datele protejate ale clienților (nume, email, telefon).
   - Dacă schimbi scopurile, fă release la o versiune nouă și acceptă noile permisiuni în magazin.
   - Pune *Client ID* în Render → `SHOPIFY_API_KEY` și *Client secret* → `SHOPIFY_API_SECRET`.
   - Jarvis cere singur tokenul și îl reînnoiește înainte să expire (24h). Starea se vede în `/health` → `shopify_connection`.
1. **Bază de date permanentă.** Pe Render free, SQLite se șterge la fiecare restart. Odată cu el se pierd dezabonările, istoricul și setările. Creează un Postgres gratuit (Neon sau Supabase) și pune link-ul în Render → Environment → `DATABASE_URL`. Până atunci, pe Render Jarvis **nu trimite mesaje de marketing**, ca să nu scrie cuiva care s-a dezabonat (`/health` → `marketing_paused_reason`).
2. **Parola dashboard-ului.** Setează în Render → Environment `JARVIS_ADMIN_KEY` (minimum 12 caractere). Ți-o cere dashboard-ul când îl deschizi direct, nu din Shopify Admin.
3. **Server treaz.** Render free adoarme serverul după 15 minute fără trafic, iar automatizările se opresc. Workflow-ul GitHub `.github/workflows/keepalive.yml` accesează `/health` la fiecare 10 minute, dar GitHub poate întârzia rulările. Pentru siguranță, adaugă și un monitor gratuit (UptimeRobot / cron-job.org) pe `https://shopify-jarvis.onrender.com/health` la fiecare 5 minute.
4. **Email (Resend).** În Resend → Domains → maisongrozavu.com, copiază înregistrările pentru `send.maisongrozavu.com` (MX + TXT SPF `include:amazonses.com`) în Google Cloud DNS. Cheia DKIM `resend._domainkey` există deja. Opțional, mai târziu: DMARC de la `p=none` la `p=quarantine`.
5. **Codul VIP.** Creează în Shopify codul `MGVIP15` (15%, o utilizare per client). Momentan nu există, deci emailurile VIP ar trimite un cod nefuncțional.
6. **Google Merchant Center.** Folosește **ori** aplicația Google & YouTube din Shopify (recomandat), **ori** feed-ul Jarvis, nu pe amândouă (produsele s-ar dubla).

## Variabile de mediu
Vezi `backend/.env.example` și `render.yaml`. Cele mai importante:
- `DATABASE_URL`, `JARVIS_ADMIN_KEY`;
- `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, opțional `SHOPIFY_ACCESS_TOKEN`;
- `RESEND_API_KEY`, `SENDER_EMAIL`, `REPLY_TO_EMAIL`, `MERCHANT_NOTIFY_EMAIL`;
- `GEMINI_API_KEY`.

## Securitate
- Toate rutele `/api/...` cu date sau acțiuni cer fie token-ul de sesiune Shopify (automat în Shopify Admin), fie `X-Jarvis-Key`.
- Cheile salvate (Resend, Twilio, Telegram etc.) nu mai sunt returnate niciodată de API.
- Webhook-urile Shopify sunt acceptate doar cu semnătură HMAC validă.
- Publice rămân doar: `/health`, feed-ul Google, verificarea DNS, pagina de dezabonare și politica de confidențialitate.

## Teste
```bash
python -m unittest discover -s tests -p "test_*.py"
```
Testele nu fac apeluri reale la rețea și trec pe Python 3.11 (Render) și 3.14 (local).
