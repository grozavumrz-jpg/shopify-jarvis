# Jarvis for Shopify — Grozavu (maisongrozavu.com)

Asistent pentru magazinul Shopify: urmărește coșurile abandonate (doar clienți cu acord de marketing), trimite mulțumiri după livrare, generează feed-ul Google Merchant din produsele reale, verifică DNS-ul pentru emailuri și răspunde în chat pe baza datelor reale din Shopify.

**Regula de bază:** Jarvis nu inventează nimic. Dacă nu are date de la Shopify, arată „indisponibil”, nu cifre false.

---

## Ce rulează automat (cât timp serverul e pornit)
Intervalul e de 5 minute, sau de 15 minute pe Neon. Planul gratuit Neon are 100 de ore de calcul pe lună, iar baza adoarme doar după 5 minute fără activitate. La 15 minute baza poate dormi între cicluri, cu un consum de aproximativ 70 de ore pe lună. Intervalul se poate schimba din `JARVIS_AUTOPILOT_MINUTES`.

1. Verifică comenzile noi și oprește mesajele pentru coșurile care au devenit comenzi.
2. Coșuri abandonate, maximum 3 mesaje per coș: la 30 de minute (fără reducere), la 4 ore și la 24 de ore (cu codul MG10). Se trimit **doar** dacă:
   - clientul are acord de marketing în Shopify (pentru email; separat pentru WhatsApp);
   - nu s-a dezabonat;
   - nu e între 21:00 și 09:00, ora Spaniei;
   - nu depășește limitele de frecvență.
3. După livrare: mulțumire + cod pentru următoarea comandă. Pleacă la 2 zile după ce curierul raportează „livrat”; dacă nu există tracking, la 5 zile după expediere (cu tracking care nu ajunge la „livrat”, cel târziu la 14 zile). O mulțumire întârziată cu peste 14 zile (de ex. după o pană) nu se mai trimite. Reducerea nu e condiționată de o recenzie, iar mesajul trece prin aceleași reguli de acord și e scris în limba aleasă de client în checkout.
4. Feed-ul Google Merchant: `https://<app>/feeds/google-merchant.xml`. Conține câte un articol pe fiecare variantă (culoare/mărime) și doar produse active, publicate, cu poză și preț.
5. SEO: Jarvis **doar propune** titluri, descrieri și texte alternative pentru imagini. Nu modifică nimic în Shopify fără aprobarea ta.
6. Alerte pe telefon (Telegram / Discord / email): dacă Jarvis a fost oprit peste o oră, dacă 3 cicluri la rând au erori (și când își revine) și, lunea de la 09:00, **raportul săptămânal** (mesaje trimise, comenzi după un mesaj Jarvis și valoarea lor, mulțumiri VIP, dezabonări). Aceleași cifre se văd în tabul Pilot Automat 24/7 → „Ultimele 7 zile”.
7. Adresele care dau bounce permanent sau marchează emailul ca spam sunt excluse automat (protejează reputația domeniului).

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
5. **Codul VIP.** Creează în Shopify codul `MGVIP15` (15%, o utilizare per client). Fără el, emailurile VIP trimit un cod nefuncțional.
   Verifică și `MG10` (10%), folosit în mesajele 2 și 3 pentru coșuri.
5b. **Bounce-uri și spam (Resend).** Resend → Webhooks → Add endpoint: `https://shopify-jarvis.onrender.com/webhooks/resend`, evenimentele `email.bounced` și `email.complained`. Copiază *Signing secret* (`whsec_...`) în Render → `RESEND_WEBHOOK_SECRET`. Fără acest secret, endpoint-ul refuză orice cerere.
5c. **Alerte pe telefon.** Tabul Pilot Automat 24/7 → „Alerte pe telefon”: token-ul botului Telegram (de la @BotFather) și chat ID-ul tău, sau un webhook Discord. Bifează canalul și apasă „Trimite o alertă de test”.
5d. **Telefonul tău pentru testul WhatsApp.** Tabul Pilot Automat 24/7 → WhatsApp → „Telefonul tău (comerciant)”. Testele de email și WhatsApp pleacă **doar** către contactele tale (email de notificare, adresele `@maisongrozavu.com`, telefonul tău), niciodată către clienți.
6. **Google Merchant Center.** Folosește **ori** aplicația Google & YouTube din Shopify (recomandat), **ori** feed-ul Jarvis, nu pe amândouă (produsele s-ar dubla).

## Variabile de mediu
Vezi `backend/.env.example` și `render.yaml`. Cele mai importante:
- `DATABASE_URL`, `JARVIS_ADMIN_KEY`;
- `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, opțional `SHOPIFY_ACCESS_TOKEN`;
- `RESEND_API_KEY`, `SENDER_EMAIL`, `REPLY_TO_EMAIL`, `MERCHANT_NOTIFY_EMAIL`, `RESEND_WEBHOOK_SECRET`;
- `MERCHANT_NOTIFY_PHONE` (opțional, telefonul tău pentru testul WhatsApp; se poate pune și din dashboard);
- `GEMINI_API_KEY`;
- `JARVIS_BILLING_TEST` (implicit `1` = abonamente de test, gratuite; `0` = taxare reală);
- `JARVIS_ENABLE_DOCS=1` doar local, dacă vrei documentația API la `/docs`.

## Securitate
- Toate rutele `/api/...` cu date sau acțiuni cer fie token-ul de sesiune Shopify (automat în Shopify Admin), fie `X-Jarvis-Key`. După 20 de chei greșite într-un minut, autentificarea cu cheie se oprește un minut (cea din Shopify Admin nu e afectată).
- Cheile salvate (Resend, Twilio, Telegram etc.) nu mai sunt returnate niciodată de API.
- Webhook-urile Shopify sunt acceptate doar cu semnătură HMAC validă (reluările aceluiași webhook se ignoră); cele Resend doar cu semnătură Svix validă și recentă.
- URL-urile de webhook (Discord, WhatsApp) și serverul SMTP trebuie să fie publice: localhost / rețele private sunt refuzate și la salvare, și la trimitere. SMTP verifică certificatul TLS.
- Publice rămân doar: `/health`, `/api/status` (doar „online”, fără detalii), feed-ul Google, verificarea DNS, pagina de dezabonare, politica de confidențialitate, plus rutele pe care le cheamă Shopify / Resend (instalare OAuth, confirmare abonament, webhook-uri semnate). Documentația API (`/docs`) e oprită.
- Dezabonarea: linkul din email deschide o pagină de confirmare (programele antivirus din email deschid linkurile automat, deci un simplu click nu mai dezabonează pe nimeni din greșeală). „Dezabonare” din Gmail / Outlook (one-click) funcționează direct. Un client care se răzgândește poate fi reactivat din tabul Radar Trafic & Google → Livrabilitate & Anti-Spam.
- WhatsApp: Shopify nu are un acord separat pentru WhatsApp, așa că Jarvis folosește acordul de **SMS** marketing din Shopify (niciodată pe cel de email). Dacă vrei un opt-in strict pentru WhatsApp, e o decizie juridică — spune-mi și îl adaug.

## Teste
```bash
pip install -r backend/requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```
Testele nu fac apeluri reale la rețea, folosesc o bază SQLite temporară pentru fiecare rulare (nu ating `backend/jarvis.db`) și trec pe Python 3.11 (Render) și 3.13. **Nu le rula cu `DATABASE_URL`-ul de producție setat.**
GitHub Actions (`.github/workflows/tests.yml`) rulează automat testele, `pip-audit` și build-ul frontend-ului la fiecare push.
