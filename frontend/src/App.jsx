import React, { useState, useEffect, useRef } from 'react'
import { api, apiPost, readJson, errorText, onAuthRequired, setAdminKey, hasAdminKey, storageGet, storageSet } from './api.js'

// Multi-language dictionary (English & Romanian)
const I18N = {
  en: {
    brand_sub_pro: 'EXECUTIVE PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'SHOPIFY CONNECTED',
    telemetry_disconnected: 'SHOPIFY NOT CONNECTED',
    updated_at: 'Updated at',
    voice_active: '🎙️ VOICE: ACTIVE',
    voice_mute: '🔇 VOICE: MUTE',
    upgrade_btn: '⚡ UPGRADE PRO ($9.99/mo)',
    pro_active_badge: '💎 PRO ACTIVE • EXECUTIVE SALES ENGINE',
    tab_hud: '🧠 STORE BRAIN & DIAGNOSTICS',
    tab_radar: '🌐 TRAFFIC & GOOGLE RADAR',
    tab_actions: '⚡ 1-CLICK CAMPAIGNS & BOOST',
    tab_chat: '💬 CHAT WITH JARVIS',
    tab_autopilot: '🤖 24/7 AUTOPILOT',
    tab_plans: '💎 SUBSCRIPTIONS',
    health_score_label: 'STORE HEALTH SCORE',
    listen_briefing: '🔊 LISTEN TO VOICE BRIEFING',
    stop_voice: '⏹️ STOP VOICE',
    voice_locked_msg: '🔒 Jarvis autonomous voice is available on Pro Plan.',
    unlock_pro: 'Unlock Pro ($9.99)',
    orders_today: 'ORDERS TODAY',
    orders_sub: 'Updated at',
    revenue_today: 'REVENUE TODAY',
    revenue_30d: '30-day velocity:',
    abandoned_carts: 'ABANDONED CHECKOUTS',
    abandoned_alert: '⚠️ Immediate revenue recovery opportunity',
    abandoned_ok: '✅ Zero abandoned carts',
    new_customers: 'NEW CUSTOMERS (24H)',
    customers_sub: 'First-time customers, last 24h',
    aov_label: 'AVG ORDER VALUE (AOV)',
    aov_sub: 'Average of the last 30 days',
    retention_label: 'RETENTION RATE',
    retention_sub: 'returning customers',
    unique_buyers_label: 'UNIQUE BUYERS (30D)',
    unique_buyers_sub: 'Customer accounts',
    vip_customer_label: 'TOP VIP CLIENT',
    tactical_plan: '🎯 STRATEGIC PRIORITIES FOR TODAY',
    ai_prioritized: 'AI OPTIMIZED',
    analyzing_priorities: 'No priorities generated yet.',
    traffic_strategy: '📈 GROWTH STRATEGY & ANOMALY RADAR',
    daily_growth_tip: 'GROWTH STRATEGY OF THE DAY',
    auto_diagnostics: 'AUTONOMOUS DIAGNOSTICS:',
    store_nominal: 'No alerts right now.',
    diagnostics_unavailable: 'Diagnostics unavailable — Shopify is not connected.',
    quick_diagnosis_btn: '💡 INSTANT DIAGNOSIS: WHY ARE SALES LOW TODAY AND WHAT CAN I FIX RAPIDLY?',
    chat_welcome_title: 'Jarvis Executive Brain is Active.',
    chat_welcome_desc: 'I can read orders, abandoned checkouts and products from Shopify (when the store is connected) and turn them into AI ideas and drafts. Numbers always come from Shopify; everything else is an idea for you to verify.',
    chip_diagnosis: '💡 Why are my sales low today and what can I fix immediately?',
    chip_boost: '⚡ /boost — Quick conversion ideas (AI)',
    chip_browser: '🌐 /browser — Google & social customer ideas (AI)',
    chip_goal: '🎯 /goal — Mathematical 10,000€ Revenue Blueprint',
    chip_aov: '🛍️ How do we increase Average Order Value (AOV) for Grozavu?',
    chat_placeholder_free: 'Ask Jarvis anything about the store...',
    chat_placeholder_pro: 'Command Jarvis (/boost, /browser, /goal or any sales task)...',
    chat_send: 'SEND',
    thinking_text: 'Jarvis is formulating executive tactical advice...',
    action_tiktok_title: '🎬 Viral 30s TikTok/Reels Script',
    action_tiktok_desc: 'AI draft of a 3-step streetwear video script (3s visual hook, problem/solution and a direct CTA to the store).',
    action_email_title: '📧 Magnetic Cart Recovery Email',
    action_email_desc: 'AI draft of an abandoned-checkout email. Nothing is sent — copy it and review it first.',
    action_seo_title: '🔍 Google SEO & Conversion Catalog Audit',
    action_seo_desc: 'AI suggestions for product titles and descriptions. Nothing is changed in Shopify.',
    action_vip_title: '👑 VIP Loyalty Email',
    action_vip_desc: 'AI draft of a thank-you email for returning customers. Nothing is sent automatically.',
    action_post_title: '📦 Post-Delivery Thank-You & Review Request',
    action_post_desc: 'AI draft of a post-delivery email: thank-you, care tip and an optional, honest review request.',
    action_trigger: 'GENERATE NOW →',
    action_generating: 'GENERATING WITH AI...',
    pricing_title: 'CHOOSE THE INTELLIGENCE LEVEL FOR YOUR STORE',
    pricing_sub: 'No expensive agencies or employees. Jarvis is your 24/7 technical and marketing co-founder.',
    plan_free_title: 'Observer Mode',
    plan_free_badge: 'BASIC PLAN',
    plan_free_price: '$0',
    plan_free_period: '/ forever',
    plan_free_desc: 'Monitors orders and gives high-level visibility over store metrics.',
    plan_free_perk1: '✔ Sales & orders dashboard',
    plan_free_perk2: '✔ Manual chat with Jarvis',
    plan_free_perk3: '✔ Text-only daily briefing on demand',
    plan_free_dim1: '✖ No autonomous audio voice',
    plan_free_dim2: '✖ No 1-click viral campaign generators',
    plan_free_dim3: '✖ No proactive loss detection alerts',
    plan_free_btn_active: 'CURRENT PLAN',
    plan_free_btn_switch: 'To cancel Pro: Shopify Admin → Settings → Apps',
    plan_pro_title: 'Jarvis Autonomous Pro',
    plan_pro_badge: 'RECOMMENDED FOR SALES',
    plan_pro_price: '$9.99',
    plan_pro_period: '/ month (7-day free trial)',
    plan_pro_desc: 'AI assistant with voice briefings, abandoned-cart alerts and AI-generated sales drafts.',
    plan_pro_perk1: '⭐ Jarvis Speaks to You: Daily synthetic voice audio report',
    plan_pro_perk2: '⭐ Unlimited AI Chat: No question limits',
    plan_pro_perk3: '⭐ 1-Click Campaigns: Viral TikTok scripts & cart emails',
    plan_pro_perk4: '⭐ Proactive Loss Prevention: Instant cart alerts',
    plan_pro_perk5: '⭐ AI store health summary',
    plan_pro_perk6: '⭐ Daily AI action priorities',
    plan_pro_btn: '⚡ ACTIVATE JARVIS PRO ($9.99/mo - 7 DAYS TRIAL)',
    plan_pro_btn_active: 'PRO PLAN ACTIVE',
    copied_toast: 'Copied to clipboard!',
    autopilot_title: 'AUTONOMOUS REVENUE DISPATCH COMMAND',
    autopilot_sub: 'Jarvis checks abandoned checkouts periodically and sends recovery messages only to customers with marketing consent, respecting quiet hours and frequency limits.',
    autopilot_btn_dispatch: '▶️ RUN THE CYCLE NOW (WITH ALL RULES)',
    autopilot_dispatching: 'RUNNING THE CYCLE...',
    autopilot_stat_pending: 'CARTS IN RECOVERY QUEUE',
    autopilot_stat_revenue: 'VALUE OF QUEUED CARTS',
    autopilot_stat_actions: 'LOG ENTRIES',
    autopilot_log_title: 'EXECUTION LOG',
    autopilot_queue_title: 'ABANDONED CHECKOUTS IN QUEUE',
    autopilot_success_speech: 'Autopilot cycle finished.'
  },
  ro: {
    brand_sub_pro: 'EXECUTIVE PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'SHOPIFY CONECTAT',
    telemetry_disconnected: 'SHOPIFY NECONECTAT',
    updated_at: 'Actualizat la',
    voice_active: '🎙️ VOCE: ACTIVĂ',
    voice_mute: '🔇 VOCE: MUT',
    upgrade_btn: '⚡ ACTIVEAZĂ PRO ($9.99/lună)',
    pro_active_badge: '💎 PRO ACTIV • CREIER AUTONOM DE VÂNZĂRI',
    tab_hud: '🧠 CREIERUL MAGAZINULUI & DIAGNOSTIC',
    tab_radar: '🌐 RADAR TRAFIC & GOOGLE',
    tab_actions: '⚡ CAMPANII & BOOST CONVERSIE',
    tab_chat: '💬 DISCUTĂ CU JARVIS',
    tab_autopilot: '🤖 PILOT AUTOMAT 24/7',
    tab_plans: '💎 ABONAMENTE',
    health_score_label: 'SCOR SĂNĂTATE MAGAZIN',
    listen_briefing: '🔊 ASCULTĂ RAPORTUL VOCAL',
    stop_voice: '⏹️ OPREȘTE VOCEA',
    voice_locked_msg: '🔒 Vocea autonomă Jarvis este disponibilă în Planul Pro.',
    unlock_pro: 'Deblochează Pro ($9.99)',
    orders_today: 'COMENZI ASTĂZI',
    orders_sub: 'Actualizat la',
    revenue_today: 'VENIT ASTĂZI',
    revenue_30d: '30 de zile:',
    abandoned_carts: 'COȘURI ABANDONATE',
    abandoned_alert: '⚠️ Oportunitate de recuperare imediată',
    abandoned_ok: '✅ Niciun coș pierdut',
    new_customers: 'CLIENȚI NOI (24H)',
    customers_sub: 'Clienți noi în ultimele 24h',
    aov_label: 'VALOARE MEDIE COȘ (AOV)',
    aov_sub: 'Media ultimelor 30 de zile',
    retention_label: 'RATĂ DE RETENȚIE',
    retention_sub: 'clienți care au revenit',
    unique_buyers_label: 'CUMPĂRĂTORI UNICI (30Z)',
    unique_buyers_sub: 'Conturi unice',
    vip_customer_label: 'TOP CLIENT VIP',
    tactical_plan: '🎯 PRIORITĂȚI STRATEGICE PENTRU ASTĂZI',
    ai_prioritized: 'OPTIMIZAT AI',
    analyzing_priorities: 'Nicio prioritate generată încă.',
    traffic_strategy: '📈 STRATEGIE DE CREȘTERE & RADAR ANOMALII',
    daily_growth_tip: 'SFATUL ZILEI PENTRU VÂNZĂRI',
    auto_diagnostics: 'DIAGNOSTIC AUTOMAT:',
    store_nominal: 'Nicio alertă în acest moment.',
    diagnostics_unavailable: 'Diagnostic indisponibil — Shopify nu este conectat.',
    quick_diagnosis_btn: '💡 DIAGNOSTIC INSTANT: DE CE NU AM VÂNZĂRI AZI ȘI CE POT SCHIMBA RAPID?',
    chat_welcome_title: 'Creierul Executiv Jarvis este Activ.',
    chat_welcome_desc: 'Pot citi comenzile, coșurile abandonate și produsele din Shopify (când magazinul este conectat) și le transform în idei și ciorne generate de AI. Cifrele vin mereu din Shopify; restul sunt idei pe care le verifici tu.',
    chip_diagnosis: '💡 De ce nu am vânzări azi și ce pot schimba rapid?',
    chip_boost: '⚡ /boost — Idei rapide de conversie (AI)',
    chip_browser: '🌐 /browser — Idei de clienți Google & Social (AI)',
    chip_goal: '🎯 /goal — Plan Matematic Venit 10.000€ / lună',
    chip_aov: '🛍️ Cum mărim valoarea medie a comenzii (AOV) la Grozavu?',
    chat_placeholder_free: 'Întreabă-l pe Jarvis orice despre magazin...',
    chat_placeholder_pro: 'Ordonă-i lui Jarvis (/boost, /browser, /goal sau orice sarcină)...',
    chat_send: 'TRIMITE',
    thinking_text: 'Jarvis formulează sfatul tactic executiv...',
    action_tiktok_title: '🎬 Scenariu Video TikTok / Reels în 3 Pași',
    action_tiktok_desc: 'Ciornă AI de scenariu video streetwear (Hook vizual de 3s, Problemă/Soluție și Call To Action direct către magazin).',
    action_email_title: '📧 Email Magnetic de Recuperare Coșuri',
    action_email_desc: 'Ciornă AI de email pentru coșuri abandonate. Nu se trimite nimic — o copiezi și o verifici întâi.',
    action_seo_title: '🔍 Audit Google SEO & Conversie Catalog',
    action_seo_desc: 'Sugestii AI pentru titluri și descrieri de produs. Nu se modifică nimic în Shopify.',
    action_vip_title: '👑 Email VIP de Fidelizare',
    action_vip_desc: 'Ciornă AI de email de mulțumire pentru clienții care revin. Nu se trimite nimic automat.',
    action_post_title: '📦 Email Post-Livrare & Cerere de Recenzie',
    action_post_desc: 'Ciornă AI de email după livrare: mulțumire, sfat de îngrijire și o cerere opțională de recenzie onestă.',
    action_trigger: 'GENEREAZĂ ACUM →',
    action_generating: 'GENERARE ÎN CURS...',
    pricing_title: 'ALEGE NIVELUL DE INTELIGENȚĂ PENTRU MAGAZINUL TĂU',
    pricing_sub: 'Fără angajați scumpi. Jarvis este cofondatorul tău tehnic și de marketing disponibil 24/7.',
    plan_free_title: 'Observer Mode',
    plan_free_badge: 'PLANUL DE BAZĂ',
    plan_free_price: '$0',
    plan_free_period: '/ pentru totdeauna',
    plan_free_desc: 'Monitorizează comenzile și oferă o perspectivă generală asupra cifrelor magazinului.',
    plan_free_perk1: '✔ Dashboard cu vânzări și comenzi',
    plan_free_perk2: '✔ Chat manual cu Jarvis',
    plan_free_perk3: '✔ Raport text la cerere',
    plan_free_dim1: '✖ Fără voce audio autonomă',
    plan_free_dim2: '✖ Fără generatoare automate de campanii',
    plan_free_dim3: '✖ Fără alerte proactive de coșuri abandonate',
    plan_free_btn_active: 'PLAN ACTIV',
    plan_free_btn_switch: 'Anulare Pro: Shopify Admin → Setări → Aplicații',
    plan_pro_title: 'Jarvis Autonomous Pro',
    plan_pro_badge: 'RECOMANDAT PENTRU VÂNZĂRI',
    plan_pro_price: '$9.99',
    plan_pro_period: '/ lună (Trial 7 zile inclus)',
    plan_pro_desc: 'Asistent AI cu raport vocal, alerte pentru coșuri abandonate și ciorne de vânzare generate de AI.',
    plan_pro_perk1: '⭐ Jarvis Vorbește cu Tine: Raport vocal zilnic sintetic',
    plan_pro_perk2: '⭐ Chat AI Nelimitat: Fără limite de întrebări',
    plan_pro_perk3: '⭐ Campanii 1-Click: Scripturi TikTok virale & emailuri',
    plan_pro_perk4: '⭐ Alerte Proactive: Te anunță imediat când apar coșuri abandonate',
    plan_pro_perk5: '⭐ Rezumat AI al stării magazinului',
    plan_pro_perk6: '⭐ Prioritizare Tactică Zilnică',
    plan_pro_btn: '⚡ ACTIVEAZĂ JARVIS PRO ($9.99/lună - 7 ZILE TRIAL)',
    plan_pro_btn_active: 'PLAN PRO ACTIV',
    copied_toast: 'Copiat în clipboard!',
    autopilot_title: 'CENTRUL DE COMANDĂ PILOT AUTOMAT (JARVIS 24/7)',
    autopilot_sub: 'Jarvis verifică periodic coșurile abandonate și trimite mesaje de recuperare doar clienților cu acord de marketing, respectând orele de liniște și limitele de frecvență.',
    autopilot_btn_dispatch: '▶️ RULEAZĂ CICLUL ACUM (CU TOATE REGULILE)',
    autopilot_dispatching: 'SE RULEAZĂ CICLUL...',
    autopilot_stat_pending: 'COȘURI ÎN COADA DE RECUPERARE',
    autopilot_stat_revenue: 'VALOAREA COȘURILOR DIN COADĂ',
    autopilot_stat_actions: 'ÎNREGISTRĂRI ÎN JURNAL',
    autopilot_log_title: 'JURNAL DE EXECUȚIE',
    autopilot_queue_title: 'COȘURI ABANDONATE ÎN COADĂ',
    autopilot_success_speech: 'Ciclul pilotului automat s-a încheiat.'
  }
}

// ── Helpers: missing data always renders as "—" (never invented numbers) ──
const DASH = '—'
const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const asArray = (v) => (Array.isArray(v) ? v : [])
const fmtNum = (v, digits) => {
  if (!isNum(v)) return DASH
  if (typeof digits === 'number') return v.toFixed(digits)
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)
}

// Safari-safe date parsing: "YYYY-MM-DD HH:MM:SS" → ISO; no timezone → UTC.
function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const d = new Date(value)
    return isNaN(d.getTime()) ? null : d
  }
  let s = String(value).trim()
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) s = s.replace(' ', 'T')
  s = s.replace(/(\.\d{3})\d+/, '$1')
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s += 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? null : d
}

function fmtTime(value, locale) {
  const d = parseDate(value)
  if (!d) return DASH
  try {
    return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    return d.toISOString().slice(11, 16)
  }
}

function fmtDateTime(value, locale) {
  const d = parseDate(value)
  if (!d) return DASH
  try {
    return d.toLocaleString(locale, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    return d.toISOString().slice(0, 16).replace('T', ' ')
  }
}

function minutesSince(value) {
  const d = parseDate(value)
  if (!d) return null
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 60000))
}

function agoText(minutes, lang) {
  if (minutes === null) return null
  if (lang !== 'ro') {
    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes} min ago`
    if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`
    return `${Math.round(minutes / 1440)} days ago`
  }
  if (minutes < 1) return 'chiar acum'
  if (minutes < 60) return `acum ${minutes} min`
  if (minutes < 1440) return `acum ${Math.round(minutes / 60)} h`
  return `acum ${Math.round(minutes / 1440)} zile`
}

// DNS check status: new shape {status}, old shape {configured: bool}.
function dnsStatus(check) {
  if (!check || typeof check !== 'object') return 'unknown'
  if (typeof check.status === 'string') {
    const st = check.status.toLowerCase()
    return ['ok', 'missing', 'invalid', 'unknown'].includes(st) ? st : 'unknown'
  }
  if (typeof check.configured === 'boolean') return check.configured ? 'ok' : 'missing'
  return 'unknown'
}

const DNS_STATUS_UI = {
  ok: { label: '✅ Configurat', color: '#10b981', border: '#059669' },
  missing: { label: '❌ Lipsește', color: '#f87171', border: '#b91c1c' },
  invalid: { label: '⚠️ Invalid', color: '#f59e0b', border: '#b45309' },
  unknown: { label: '❔ Necunoscut (verificarea DNS nu a reușit)', color: '#94a3b8', border: '#44403c' }
}

function dnsRecordText(check) {
  if (!check || typeof check !== 'object') return DASH
  if (typeof check.record === 'string' && check.record) return check.record
  if (Array.isArray(check.records) && check.records.length) return check.records.map(String).join(' | ')
  if (typeof check.value === 'string' && check.value) return check.value
  if (typeof check.host === 'string' && check.host) return check.host
  return DASH
}

function dnsCheckNote(check) {
  if (!check || typeof check !== 'object') return null
  for (const k of ['error', 'message', 'detail', 'issue']) {
    if (typeof check[k] === 'string' && check[k]) return check[k]
  }
  if (Array.isArray(check.issues) && check.issues.length) return check.issues.map(String).join('; ')
  return null
}

const consentText = (v) => (v === true ? '✓' : v === false ? '✗' : 'necunoscut')
const consentColor = (v) => (v === true ? '#10b981' : v === false ? '#f87171' : '#94a3b8')

// Translate a skip reason for the owner (raw reason always kept for transparency).
function reasonText(reason) {
  if (reason === null || reason === undefined || reason === '') return DASH
  const raw = String(reason)
  const r = raw.toLowerCase()
  let ro = null
  if (r.includes('opt') || r.includes('unsub') || r.includes('suppress')) ro = 'dezabonat (opt-out)'
  else if (r.includes('consent')) ro = 'fără acord de marketing'
  else if (r.includes('quiet')) ro = 'ore de liniște'
  else if (r.includes('cap') || r.includes('limit') || r.includes('frequency') || r.includes('72h') || r.includes('30d')) ro = 'limită de frecvență'
  else if (r.includes('not_due') || r.includes('not due') || r.includes('cadence') || r.includes('too_early') || r.includes('wait')) ro = 'încă nu e momentul etapei următoare'
  else if (r.includes('no_email') || r.includes('no_phone') || r.includes('no_contact') || r.includes('missing')) ro = 'fără date de contact'
  return ro && ro !== raw ? `${ro} (${raw})` : raw
}

// Status badge for log entries: shows what the backend really recorded.
function logStatusUi(status) {
  const s = String(status || '').toLowerCase()
  if (!s) return { text: DASH, color: '#94a3b8' }
  if (['sent', 'success', 'delivered', 'ok'].includes(s)) return { text: 'trimis', color: '#10b981' }
  if (s === 'executed') return { text: 'executat', color: '#10b981' }
  if (s.includes('fail') || s.includes('error')) return { text: 'eșuat', color: '#f87171' }
  if (s.includes('skip') || s.includes('block')) return { text: 'omis', color: '#94a3b8' }
  if (s.includes('preview') || s.includes('propos') || s === 'draft') return { text: 'doar propunere (nescris în Shopify)', color: '#38bdf8' }
  return { text: s, color: '#e2d9cd' }
}

// Frequency policy (from /api/compliance/stats) → readable rows.
const FREQ_LABELS = {
  max_per_72h: 'Maxim mesaje în 72h',
  max_per_30d: 'Maxim mesaje de marketing în 30 de zile',
  global_max_per_30d: 'Maxim mesaje de marketing în 30 de zile',
  max_marketing_per_30d: 'Maxim mesaje de marketing în 30 de zile',
  cart_max_messages: 'Maxim mesaje per coș abandonat',
  cart_sequence_max: 'Maxim mesaje per coș abandonat',
  abandoned_cart_max_messages: 'Maxim mesaje per coș abandonat',
  cart_stage_delays: 'Etapele coșului abandonat',
  cart_stages: 'Etapele coșului abandonat',
  vip_max_per_order: 'Maxim mesaje VIP per comandă',
  post_delivery_max_per_order: 'Maxim mesaje post-livrare per comandă',
  new_sequence_cooldown_hours: 'Pauză înainte de o secvență nouă (ore)',
  new_sequence_block_hours: 'Pauză înainte de o secvență nouă (ore)',
  quiet_hours: 'Ore de liniște',
  timezone: 'Fus orar'
}
const humanizeKey = (k) => FREQ_LABELS[k] || String(k).replace(/_/g, ' ')
function humanizeValue(v) {
  if (v === null || v === undefined || v === '') return DASH
  if (Array.isArray(v)) return v.map(humanizeValue).join(', ')
  if (typeof v === 'boolean') return v ? 'da' : 'nu'
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${humanizeKey(k)}: ${humanizeValue(x)}`).join('; ')
  return String(v)
}
function policyEntries(fp) {
  if (!fp) return []
  if (typeof fp === 'string') return [['description', fp]]
  if (typeof fp !== 'object' || Array.isArray(fp)) return []
  return Object.entries(fp)
}

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const shop = params.get('shop') || 'maisongrozavu.myshopify.com'
  const qShop = `shop=${encodeURIComponent(shop)}`

  const [lang, setLang] = useState(() => storageGet('jarvis_lang') || 'ro')
  const t = I18N[lang] || I18N.ro
  const locale = lang === 'ro' ? 'ro-RO' : 'en-GB'

  const handleSetLang = (newLang) => {
    setLang(newLang)
    storageSet('jarvis_lang', newLang)
  }

  const [activeTab, setActiveTab] = useState('hud') // 'hud' | 'radar' | 'actions' | 'chat' | 'autopilot' | 'plans'
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [briefing, setBriefing] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [plan, setPlan] = useState(null) // 'free' | 'pro' | null (unknown)
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [isSpeaking, setIsSpeaking] = useState(false)

  // Auth (401 → "Cheie de acces Jarvis" card)
  const [authRequired, setAuthRequired] = useState(false)
  const [authKeyInput, setAuthKeyInput] = useState('')
  const [authAttempted, setAuthAttempted] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  // Chat State
  const [chatMessages, setChatMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [sendingChat, setSendingChat] = useState(false)
  const chatBottomRef = useRef(null)

  // Tactical Tasks
  const [completedTasks, setCompletedTasks] = useState({})

  // 1-Click Generator Output Modal
  const [generatedOutput, setGeneratedOutput] = useState(null)
  const [generatingAction, setGeneratingAction] = useState(null) // action type being generated
  const [subscribing, setSubscribing] = useState(false)
  const [billingFeedback, setBillingFeedback] = useState(null)

  // Autopilot State
  const [autopilotData, setAutopilotData] = useState(null)
  const [dispatchingAutopilot, setDispatchingAutopilot] = useState(false)
  const [autopilotLogs, setAutopilotLogs] = useState([])
  const [confirmDispatchOpen, setConfirmDispatchOpen] = useState(false)
  const [dispatchResult, setDispatchResult] = useState(null)

  // Growth & Radar State
  const [seoData, setSeoData] = useState(null)
  const [radarData, setRadarData] = useState(null)
  const [boostData, setBoostData] = useState(null)
  const [goalData, setGoalData] = useState(null)
  const [goalError, setGoalError] = useState(null)
  const [goalTarget, setGoalTarget] = useState('10000')
  const [calculatingGoal, setCalculatingGoal] = useState(false)
  const [activeRadarSubtab, setActiveRadarSubtab] = useState('google-merchant') // 'google-merchant' | 'deliverability' | 'seo' | 'hunter' | 'goal'
  const [toastMessage, setToastMessage] = useState(null)
  const [liveSearchQuery, setLiveSearchQuery] = useState('hanorac oversize')
  const [liveSearchResults, setLiveSearchResults] = useState([])
  const [liveSearchSource, setLiveSearchSource] = useState(null) // 'google_suggest' | 'unavailable' | null
  const [liveSearchShownQuery, setLiveSearchShownQuery] = useState('')
  const [searchingGoogle, setSearchingGoogle] = useState(false)
  const [dnsAuditData, setDnsAuditData] = useState(null)
  const [feedValidation, setFeedValidation] = useState(null)
  const [seoAuditData, setSeoAuditData] = useState(null)
  const [seoLogs, setSeoLogs] = useState([])
  const [seoProposals, setSeoProposals] = useState(null)
  const [complianceStats, setComplianceStats] = useState(null)
  const [optimizingSeo, setOptimizingSeo] = useState(false)

  // Delivery & Email Gateway State
  const [deliverySettings, setDeliverySettings] = useState({
    email_provider: 'resend',
    resend_api_key: '',
    smtp_host: 'smtp.gmail.com',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    sender_email: 'contact@maisongrozavu.com',
    sender_name: 'Grozavu',
    merchant_notify_email: 'grozavumrz@gmail.com',
    notify_merchant_on_cart: true
  })
  const [savingDelivery, setSavingDelivery] = useState(false)
  const [sendingTestEmail, setSendingTestEmail] = useState(false)
  const [deliveryFeedback, setDeliveryFeedback] = useState(null)

  // WhatsApp Settings State
  const [waSettings, setWaSettings] = useState({
    whatsapp_provider: 'auto',
    whatsapp_api_token: '',
    whatsapp_phone_number_id: '',
    twilio_account_sid: '',
    twilio_auth_token: '',
    twilio_whatsapp_number: 'whatsapp:+14155238886',
    whatsapp_webhook_url: ''
  })
  const [savingWa, setSavingWa] = useState(false)
  const [waFeedback, setWaFeedback] = useState(null)
  const [testPhone, setTestPhone] = useState('')
  const [sendingTestWa, setSendingTestWa] = useState(false)

  // Mobile Notifications Settings State
  const [notifySettings, setNotifySettings] = useState({
    telegram_bot_token: '',
    telegram_chat_id: '',
    notify_telegram: false,
    discord_webhook_url: '',
    notify_discord: false
  })
  const [savingNotify, setSavingNotify] = useState(false)
  const [notifyFeedback, setNotifyFeedback] = useState(null)
  const [testingAlert, setTestingAlert] = useState(false)

  // Post-Delivery VIP Review State
  const [vipQueue, setVipQueue] = useState([])
  const [syncingVip, setSyncingVip] = useState(false)
  const [vipFeedback, setVipFeedback] = useState(null)

  // Lazy-load registry: each tab/subtab loads its data once (refresh buttons force reload)
  const loadedRef = useRef(new Set())
  const ensureLoaded = async (key, fn) => {
    if (loadedRef.current.has(key)) return
    loadedRef.current.add(key)
    const ok = await fn()
    if (ok === false) loadedRef.current.delete(key)
  }

  // Toast with a single, cleared timer
  const toastTimer = useRef(null)
  const showToast = (msg, ms = 3500) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToastMessage(msg)
    toastTimer.current = setTimeout(() => {
      setToastMessage(null)
      toastTimer.current = null
    }, ms)
  }
  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
  }, [])

  // Any 401 from a protected route → show the access key card
  useEffect(() => {
    const unsubscribe = onAuthRequired(() => setAuthRequired(true))
    return () => { unsubscribe() }
  }, [])

  const handleSaveAuthKey = () => {
    const key = authKeyInput.trim()
    if (!key) {
      showToast(lang === 'ro' ? 'Introdu cheia de acces Jarvis.' : 'Enter the Jarvis access key.')
      return
    }
    setAdminKey(key)
    setAuthKeyInput('')
    setAuthAttempted(true)
    setAuthRequired(false)
    loadedRef.current.clear()
    setReloadToken((n) => n + 1)
  }

  const handleForgetAuthKey = () => {
    setAdminKey(null)
    setAuthAttempted(false)
    showToast(lang === 'ro' ? 'Cheia salvată a fost ștearsă din acest browser.' : 'Saved key removed from this browser.')
  }

  const handleCopy = async (text, label = 'Copiat!') => {
    const value = text === null || text === undefined ? '' : String(text)
    if (!value) {
      showToast(lang === 'ro' ? 'Nu există nimic de copiat.' : 'Nothing to copy.')
      return
    }
    let ok = false
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value)
        ok = true
      }
    } catch (e) {
      ok = false
    }
    if (!ok) {
      try {
        const ta = document.createElement('textarea')
        ta.value = value
        ta.setAttribute('readonly', '')
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        ok = document.execCommand('copy')
        document.body.removeChild(ta)
      } catch (e) {
        ok = false
      }
    }
    showToast(ok ? label : (lang === 'ro'
      ? '⚠️ Nu am putut copia automat — selectează textul și copiază-l manual.'
      : '⚠️ Could not copy automatically — select the text and copy it manually.'))
  }

  // Audio TTS Function
  const speakText = (text) => {
    if (!voiceEnabled || !text) return
    try {
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel()
        const utterance = new SpeechSynthesisUtterance(text.slice(0, 300))
        utterance.lang = lang === 'ro' ? 'ro-RO' : 'en-US'
        utterance.rate = 1.05
        utterance.pitch = 1.0
        utterance.onstart = () => setIsSpeaking(true)
        utterance.onend = () => setIsSpeaking(false)
        utterance.onerror = () => setIsSpeaking(false)
        window.speechSynthesis.speak(utterance)
      }
    } catch (e) {
      console.warn('SpeechSynthesis warning:', e)
    }
  }

  const triggerVoiceBriefing = () => {
    if (isSpeaking) {
      if (window.speechSynthesis) window.speechSynthesis.cancel()
      setIsSpeaking(false)
      return
    }
    const script = briefing?.voice_script || briefing?.summary ||
      (lang === 'ro' ? 'Nu există încă un raport de citit.' : 'There is no briefing to read yet.')
    speakText(script)
  }

  // Generic GET → setter. Returns true on success.
  const loadJsonInto = async (path, setter, onError) => {
    try {
      const res = await api(path)
      const data = await readJson(res)
      if (!res.ok) {
        if (onError && res.status !== 401) onError(errorText(data, res))
        return false
      }
      setter(data)
      return true
    } catch (e) {
      console.warn('Load failed', path, e)
      if (onError) onError(e.message || 'eroare de rețea')
      return false
    }
  }

  const loadSeoIdeas = () => loadJsonInto(`/api/growth/seo?${qShop}`, setSeoData)
  const loadRadarIdeas = () => loadJsonInto(`/api/growth/radar?${qShop}`, setRadarData)
  const loadBoost = () => loadJsonInto(`/api/growth/boost?${qShop}`, setBoostData)
  const loadFeedValidation = () => loadJsonInto(
    `/api/google/feed-validation?${qShop}`, setFeedValidation, (err) => setFeedValidation({ error: err })
  )
  const loadSeoAudit = () => loadJsonInto(`/api/seo/audit?${qShop}`, setSeoAuditData)
  const loadSeoLogs = () => loadJsonInto(`/api/seo/logs?${qShop}`, (d) => setSeoLogs(asArray(d && d.logs)))
  const loadDnsAudit = () => loadJsonInto(
    `/api/deliverability/dns-audit?domain=maisongrozavu.com`, setDnsAuditData, (err) => setDnsAuditData({ error: err })
  )
  const loadCompliance = () => loadJsonInto(`/api/compliance/stats?${qShop}`, setComplianceStats)

  const parseGoal = (v) => {
    const n = Number(String(v === null || v === undefined ? '' : v).replace(',', '.').trim())
    return String(v).trim() !== '' && Number.isFinite(n) && n > 0 ? n : null
  }

  const loadGoal = async (target) => {
    const amount = parseGoal(target)
    if (amount === null) {
      setGoalError(lang === 'ro' ? 'Introdu o țintă de venit validă (un număr mai mare ca 0).' : 'Enter a valid revenue target (a number above 0).')
      return false
    }
    setGoalError(null)
    setCalculatingGoal(true)
    try {
      const res = await apiPost('/api/growth/goal', { shop, target_amount: amount, currency: snapshot?.currency || 'EUR' })
      const data = await readJson(res)
      if (!res.ok) {
        if (res.status !== 401) setGoalError(errorText(data, res))
        return false
      }
      setGoalData(data)
      return true
    } catch (e) {
      setGoalError(e.message || 'eroare de rețea')
      return false
    } finally {
      setCalculatingGoal(false)
    }
  }

  const handleCalculateGoal = () => {
    loadGoal(goalTarget)
  }

  const handleLiveGoogleSearch = async (queryToSearch = null) => {
    const q = (typeof queryToSearch === 'string' && queryToSearch) || liveSearchQuery
    if (!q || !q.trim()) {
      showToast(lang === 'ro' ? 'Scrie o expresie de căutat.' : 'Type a search phrase.')
      return false
    }
    setSearchingGoogle(true)
    try {
      const res = await api(`/api/growth/google-suggest?q=${encodeURIComponent(q.trim())}`)
      const data = await readJson(res)
      if (!res.ok) {
        setLiveSearchResults([])
        setLiveSearchSource('unavailable')
        return false
      }
      const results = asArray(data.results).filter((r) => typeof r === 'string' && r)
      setLiveSearchResults(results)
      setLiveSearchSource(data.source === 'google_suggest' ? 'google_suggest' : 'unavailable')
      setLiveSearchShownQuery(q.trim())
      return true
    } catch (err) {
      console.warn('Google suggest search error:', err)
      setLiveSearchResults([])
      setLiveSearchSource('unavailable')
      return false
    } finally {
      setSearchingGoogle(false)
    }
  }

  const handleRunSeoOptimization = async () => {
    if (optimizingSeo) return
    setOptimizingSeo(true)
    try {
      const res = await apiPost('/api/seo/optimize-now', { shop })
      const data = await readJson(res)
      if (!res.ok || data.success === false) {
        if (res.status !== 401) showToast('⚠️ Propunerile SEO nu au putut fi generate: ' + errorText(data, res))
        return
      }
      const items = asArray(data.proposals)
      const written = isNum(data.written_to_shopify) ? data.written_to_shopify : 0
      setSeoProposals({ items, written })
      if (Array.isArray(data.recent_logs)) setSeoLogs(data.recent_logs)
      const withChanges = items.filter((p) => p && asArray(p.proposals).length > 0).length
      showToast(written > 0
        ? `⚠️ Backend-ul raportează ${written} modificări scrise în Shopify.`
        : `Propuneri generate pentru ${withChanges} produse — nimic nu a fost modificat în Shopify.`, 5000)
      loadSeoAudit()
    } catch (e) {
      showToast('⚠️ Eroare la generarea propunerilor SEO: ' + (e.message || 'eroare de rețea'))
    } finally {
      setOptimizingSeo(false)
    }
  }

  const loadAutopilotStatus = async () => {
    try {
      const res = await api(`/api/autopilot/status?${qShop}`)
      if (!res.ok) return false
      const data = await readJson(res)
      setAutopilotData(data)
      setAutopilotLogs(asArray(data.logs))
      return true
    } catch (e) {
      console.error('Failed to load autopilot status', e)
      return false
    }
  }

  // Load briefing + snapshot (+ chat history, autopilot status for the nav badge)
  useEffect(() => {
    let cancelled = false
    async function loadTelemetry() {
      setLoading(true)
      setLoadError(null)
      try {
        const res = await api(`/api/briefing?${qShop}&lang=${encodeURIComponent(lang)}`)
        const data = await readJson(res)
        if (cancelled) return
        if (res.ok) {
          setBriefing(data.briefing && typeof data.briefing === 'object' ? data.briefing : null)
          setSnapshot(data.snapshot && typeof data.snapshot === 'object' ? data.snapshot : null)
          setPlan(typeof data.plan === 'string' ? data.plan : null)
          setLastUpdated(new Date())
          setAuthRequired(false)
          setAuthAttempted(false)
        } else if (res.status !== 401) {
          setLoadError(errorText(data, res))
        }
        const histRes = await api(`/api/history?${qShop}`)
        if (!cancelled && histRes.ok) {
          const hist = await readJson(histRes)
          setChatMessages(asArray(hist).filter((m) => m && typeof m.content === 'string'))
        }
        if (!cancelled) loadAutopilotStatus()
      } catch (e) {
        console.error('Failed to load Jarvis telemetry', e)
        if (!cancelled) setLoadError(e.message || 'eroare de rețea')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadTelemetry()
    return () => { cancelled = true }
  }, [shop, lang, reloadToken])

  // Load only what the visible tab / subtab needs
  useEffect(() => {
    if (activeTab === 'radar') {
      if (activeRadarSubtab === 'google-merchant') {
        ensureLoaded('feed', loadFeedValidation)
        ensureLoaded('seoAudit', loadSeoAudit)
        ensureLoaded('seoLogs', loadSeoLogs)
      } else if (activeRadarSubtab === 'deliverability') {
        ensureLoaded('dns', loadDnsAudit)
        ensureLoaded('compliance', loadCompliance)
      } else if (activeRadarSubtab === 'seo') {
        ensureLoaded('seoIdeas', loadSeoIdeas)
        ensureLoaded('suggest', () => handleLiveGoogleSearch(liveSearchQuery))
      } else if (activeRadarSubtab === 'hunter') {
        ensureLoaded('radarIdeas', loadRadarIdeas)
      } else if (activeRadarSubtab === 'goal') {
        ensureLoaded('goal', () => loadGoal(goalTarget))
      }
    } else if (activeTab === 'actions') {
      ensureLoaded('boost', loadBoost)
    } else if (activeTab === 'autopilot') {
      ensureLoaded('delivery', loadDeliverySettings)
      ensureLoaded('compliance', loadCompliance)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, activeRadarSubtab, reloadToken])

  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chatMessages, sendingChat])

  const requestDispatch = () => {
    if (dispatchingAutopilot) return
    setConfirmDispatchOpen(true)
  }

  const handleDispatchAutopilot = async () => {
    setConfirmDispatchOpen(false)
    if (dispatchingAutopilot) return
    setDispatchingAutopilot(true)
    setDispatchResult(null)
    try {
      const res = await apiPost('/api/autopilot/dispatch', { shop, lang })
      const data = await readJson(res)
      if (!res.ok || data.ok === false) {
        if (res.status !== 401) {
          setDispatchResult({ type: 'error', text: (lang === 'ro' ? 'Ciclul nu a putut rula: ' : 'The cycle could not run: ') + errorText(data, res) })
        }
        return
      }
      const count = isNum(data.dispatched_count) ? data.dispatched_count : 0
      const skipped = asArray(data.skipped)
      if (Array.isArray(data.logs)) setAutopilotLogs(data.logs)
      setDispatchResult({ type: count > 0 ? 'success' : 'info', count, skipped })
      await loadAutopilotStatus()
      if (count > 0) {
        showToast(lang === 'ro' ? `✅ Ciclu rulat: ${count} mesaje trimise.` : `✅ Cycle finished: ${count} messages sent.`)
        speakText(t.autopilot_success_speech)
      } else {
        showToast(lang === 'ro' ? 'ℹ️ Ciclu rulat: niciun mesaj trimis (vezi motivele).' : 'ℹ️ Cycle finished: no message sent (see reasons).')
      }
    } catch (e) {
      setDispatchResult({ type: 'error', text: (lang === 'ro' ? 'Eroare de rețea: ' : 'Network error: ') + e.message })
    } finally {
      setDispatchingAutopilot(false)
    }
  }

  const loadDeliverySettings = async () => {
    try {
      const res = await api(`/api/settings/delivery?${qShop}`)
      if (!res.ok) return false
      const data = await readJson(res)
      if (data && typeof data === 'object') setDeliverySettings(prev => ({ ...prev, ...data }))
      return true
    } catch (e) {
      console.error('Failed to load delivery settings', e)
      return false
    }
  }

  const handleSaveDeliverySettings = async () => {
    setSavingDelivery(true)
    setDeliveryFeedback(null)
    try {
      const res = await apiPost('/api/settings/delivery', { shop, ...deliverySettings })
      const data = await readJson(res)
      if (res.ok) {
        setDeliveryFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Setările de email au fost salvate.' : '✅ Email gateway settings saved.'
        })
      } else {
        setDeliveryFeedback({ type: 'error', text: (lang === 'ro' ? 'Eroare la salvare: ' : 'Save failed: ') + errorText(data, res) })
      }
    } catch (e) {
      setDeliveryFeedback({ type: 'error', text: e.message })
    } finally {
      setSavingDelivery(false)
    }
  }

  const handleSendTestEmail = async () => {
    const targetEmail = deliverySettings.merchant_notify_email
    if (!targetEmail) {
      setDeliveryFeedback({ type: 'error', text: lang === 'ro' ? 'Completează „Email Notificare Comerciant”.' : 'Fill in the merchant notification email.' })
      return
    }
    setSendingTestEmail(true)
    setDeliveryFeedback(null)
    try {
      const res = await apiPost('/api/email/test', { shop, to_email: targetEmail })
      const data = await readJson(res)
      if (res.ok && data.success === true) {
        setDeliveryFeedback({
          type: 'success',
          text: lang === 'ro'
            ? `✅ Furnizorul a acceptat emailul de test către ${targetEmail}. Verifică inbox-ul (și Spam/Promotions).`
            : `✅ The provider accepted the test email to ${targetEmail}. Check your inbox (and Spam/Promotions).`
        })
      } else {
        setDeliveryFeedback({
          type: 'error',
          text: (lang === 'ro' ? '⚠️ Expediere eșuată: ' : '⚠️ Send failed: ') + errorText(data, res)
        })
      }
    } catch (e) {
      setDeliveryFeedback({ type: 'error', text: 'Eroare: ' + e.message })
    } finally {
      setSendingTestEmail(false)
    }
  }

  const loadWaSettings = async () => {
    try {
      const res = await api(`/api/settings/whatsapp?${qShop}`)
      if (!res.ok) return false
      const data = await readJson(res)
      if (data && typeof data === 'object') setWaSettings(prev => ({ ...prev, ...data }))
      return true
    } catch (e) {
      console.error('Failed to load WhatsApp settings', e)
      return false
    }
  }

  const handleSaveWaSettings = async () => {
    setSavingWa(true)
    setWaFeedback(null)
    try {
      const res = await apiPost('/api/settings/whatsapp', { shop, ...waSettings })
      const data = await readJson(res)
      if (res.ok) {
        setWaFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Setările WhatsApp au fost salvate.' : '✅ WhatsApp settings saved.'
        })
      } else {
        setWaFeedback({ type: 'error', text: errorText(data, res) })
      }
    } catch (e) {
      setWaFeedback({ type: 'error', text: e.message })
    } finally {
      setSavingWa(false)
    }
  }

  const handleSendTestWa = async () => {
    if (!testPhone) return
    setSendingTestWa(true)
    setWaFeedback(null)
    try {
      const res = await apiPost('/api/whatsapp/test', { shop, to_phone: testPhone })
      const data = await readJson(res)
      if (res.ok && data.ok === true) {
        setWaFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Furnizorul a acceptat mesajul WhatsApp de test către ${testPhone}.` : `✅ The provider accepted the test WhatsApp message to ${testPhone}.`
        })
      } else {
        setWaFeedback({
          type: 'error',
          text: errorText(data, res) + (data.wa_me_url ? ` - Link direct: ${data.wa_me_url}` : '')
        })
      }
    } catch (e) {
      setWaFeedback({ type: 'error', text: e.message })
    } finally {
      setSendingTestWa(false)
    }
  }

  const loadNotifySettings = async () => {
    try {
      const res = await api(`/api/settings/notifications?${qShop}`)
      if (!res.ok) return false
      const data = await readJson(res)
      if (data && typeof data === 'object') setNotifySettings(prev => ({ ...prev, ...data }))
      return true
    } catch (e) {
      console.error('Failed to load notification settings', e)
      return false
    }
  }

  const handleSaveNotifySettings = async () => {
    setSavingNotify(true)
    setNotifyFeedback(null)
    try {
      const res = await apiPost('/api/settings/notifications', { shop, ...notifySettings })
      const data = await readJson(res)
      if (res.ok) {
        setNotifyFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Canalele de alerte mobile au fost salvate.' : '✅ Mobile alert channels saved.'
        })
      } else {
        setNotifyFeedback({ type: 'error', text: errorText(data, res) })
      }
    } catch (e) {
      setNotifyFeedback({ type: 'error', text: e.message })
    } finally {
      setSavingNotify(false)
    }
  }

  const handleTestAlert = async (channel) => {
    setTestingAlert(true)
    setNotifyFeedback(null)
    try {
      const res = await apiPost('/api/notifications/test', { shop, channel })
      const data = await readJson(res)
      if (res.ok && data.ok === true) {
        setNotifyFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Alertă de test acceptată pe ${channel}.` : `✅ Test alert accepted on ${channel}.`
        })
      } else {
        setNotifyFeedback({ type: 'error', text: errorText(data, res) })
      }
    } catch (e) {
      setNotifyFeedback({ type: 'error', text: e.message })
    } finally {
      setTestingAlert(false)
    }
  }

  const loadVipQueue = async () => {
    try {
      const res = await api(`/api/post-delivery/queue?${qShop}&limit=10`)
      if (!res.ok) return false
      const data = await readJson(res)
      setVipQueue(asArray(data.queue))
      return true
    } catch (e) {
      console.error('Failed to load VIP queue', e)
      return false
    }
  }

  const handleSyncVip = async () => {
    setSyncingVip(true)
    setVipFeedback(null)
    try {
      const res = await apiPost('/api/post-delivery/sync', { shop, days_back: 14 })
      const data = await readJson(res)
      if (res.ok) {
        const n = isNum(data.synced_count) ? data.synced_count : 0
        setVipFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Sincronizat: ${n} comenzi livrate (ultimele 14 zile).` : `✅ Synced ${n} fulfilled orders (last 14 days).`
        })
        await loadVipQueue()
      } else {
        setVipFeedback({ type: 'error', text: errorText(data, res) })
      }
    } catch (e) {
      setVipFeedback({ type: 'error', text: e.message })
    } finally {
      setSyncingVip(false)
    }
  }

  const handleSendMessage = async (customText = null) => {
    const text = (typeof customText === 'string' && customText) ? customText : inputMessage
    if (!text || !text.trim() || sendingChat) return

    setInputMessage('')
    const updated = [...chatMessages, { role: 'user', content: text }]
    setChatMessages(updated)
    setSendingChat(true)

    // Detect language
    const roMarkers = ['salut', 'buna', 'bună', 'cum', 'ce ', 'vreau', 'magazin', 'vanzari', 'vânzări', 'stoc', 'comenzi', 'produs', 'te rog', 'multumesc', 'mulțumesc', 'azi', 'acum', 'de ce', 'trafic']
    const isRoInput = roMarkers.some(m => text.toLowerCase().includes(m))
    const effectiveLang = isRoInput ? 'ro' : lang

    try {
      const res = await apiPost('/api/chat', { shop, message: text, lang: effectiveLang })
      const data = await readJson(res)
      if (!res.ok) {
        throw new Error(res.status === 401
          ? (effectiveLang === 'ro' ? 'este necesară cheia de acces' : 'access key required')
          : errorText(data, res))
      }
      const reply = typeof data.reply === 'string' && data.reply.trim() ? data.reply : null
      if (!reply) throw new Error(effectiveLang === 'ro' ? 'răspuns gol' : 'empty reply')
      setChatMessages([...updated, { role: 'assistant', content: reply }])
      if (voiceEnabled) {
        speakText(reply.slice(0, 260))
      }
    } catch (err) {
      console.warn('Chat error:', err)
      const errMsg = effectiveLang === 'ro'
        ? `⚠️ Jarvis nu a putut răspunde acum (${err.message}). Încearcă din nou peste câteva momente.`
        : `⚠️ Jarvis could not reply right now (${err.message}). Please try again in a moment.`
      setChatMessages([...updated, { role: 'assistant', content: errMsg }])
    } finally {
      setSendingChat(false)
    }
  }

  // 1-Click AI draft generators (nothing is sent or written anywhere)
  const ACTION_TITLES = {
    tiktok: t.action_tiktok_title,
    email_cart: t.action_email_title,
    seo_audit: t.action_seo_title,
    vip_reward: t.action_vip_title,
    post_purchase: t.action_post_title
  }

  const runQuickAction = async (type) => {
    if (generatingAction) return
    setGeneratingAction(type)
    let prompt = ''
    if (type === 'tiktok') {
      prompt = lang === 'ro'
        ? `Scrie-mi un script de TikTok/Reels de 30 de secunde pentru un produs real din catalogul Grozavu (streetwear premium: hanorace, crewneck-uri, tricouri boxy, windbreaker, pantaloni, accesorii). Folosește doar produse care există în magazin; dacă nu ai lista de produse, lasă un loc liber [NUME PRODUS]. Include: un hook vizual în primele 3 secunde, problemă, soluție și un Call To Action direct către maisongrozavu.com. Nu inventa materiale, prețuri sau reduceri.`
        : `Write a 30-second TikTok/Reels script for a real product from the Grozavu catalog (premium streetwear: hoodies, crewnecks, boxy tees, windbreaker, pants, accessories). Use only products that exist in the store; if you don't have the product list, leave a [PRODUCT NAME] placeholder. Include: a visual hook in the first 3 seconds, problem, solution and a direct Call to Action to maisongrozavu.com. Do not invent materials, prices or discounts.`
    } else if (type === 'email_cart') {
      prompt = lang === 'ro'
        ? `Scrie o ciornă de email de recuperare a coșurilor abandonate pentru clienții Grozavu (streetwear premium, Designed in Spain). Include un subiect clar și un ton prietenos, fără presiune falsă: nu inventa stocuri limitate, produse rezervate sau termene. Dacă propui un cod de reducere, marchează-l ca [COD DE CREAT ÎN SHOPIFY].`
        : `Write a draft abandoned-checkout recovery email for Grozavu customers (premium streetwear, Designed in Spain). Include a clear subject line and a friendly tone without fake pressure: do not invent limited stock, reserved items or deadlines. If you suggest a discount code, mark it as [CODE TO CREATE IN SHOPIFY].`
    } else if (type === 'seo_audit') {
      prompt = lang === 'ro'
        ? `Fă un audit rapid de conversie pentru produsele mele Grozavu și sugerează 3 îmbunătățiri concrete de titlu și descriere. Bazează-te doar pe produsele reale din magazin și nu inventa materiale sau caracteristici.`
        : `Run a quick conversion audit of my Grozavu products and suggest 3 concrete title and description improvements. Base it only on the real products in the store and do not invent materials or features.`
    } else if (type === 'vip_reward') {
      prompt = lang === 'ro'
        ? `Scrie o ciornă de email VIP de mulțumire pentru clienții care au cumpărat de mai multe ori de la Grozavu. Dacă magazinul nu are încă clienți recurenți, spune asta clar la început. Poți propune un beneficiu (de exemplu 15% reducere), marcat ca [COD DE CREAT ÎN SHOPIFY].`
        : `Write a draft VIP thank-you email for customers who bought from Grozavu more than once. If the store has no repeat customers yet, say so clearly at the start. You may suggest a perk (for example 15% off), marked as [CODE TO CREATE IN SHOPIFY].`
    } else if (type === 'post_purchase') {
      prompt = lang === 'ro'
        ? `Scrie o ciornă de email post-livrare pentru clienții noi Grozavu. Include: mulțumire, un sfat de îngrijire a hainei, o cerere opțională de recenzie onestă (fără a condiționa vreo reducere de recenzie sau de numărul de stele) și o recomandare de produs complementar din catalog.`
        : `Write a draft post-delivery email for new Grozavu customers. Include: a thank-you, a garment care tip, an optional request for an honest review (never tie a discount to a review or to a star rating) and a complementary product recommendation from the catalog.`
    }

    try {
      const res = await apiPost('/api/chat', { shop, message: prompt, lang })
      const data = await readJson(res)
      if (!res.ok) throw new Error(errorText(data, res))
      if (typeof data.reply !== 'string' || !data.reply.trim()) throw new Error(lang === 'ro' ? 'răspuns gol' : 'empty reply')
      setGeneratedOutput({ title: ACTION_TITLES[type] || String(type).toUpperCase(), content: data.reply })
    } catch (e) {
      console.warn('Action generation error:', e)
      showToast((lang === 'ro' ? '⚠️ Generarea a eșuat: ' : '⚠️ Generation failed: ') + e.message)
    } finally {
      setGeneratingAction(null)
    }
  }

  const handleOfficialShopifySubscribe = async () => {
    if (subscribing || plan === 'pro') return
    setSubscribing(true)
    setBillingFeedback(null)
    try {
      const res = await apiPost('/api/billing/create', { shop, test: true })
      const data = await readJson(res)
      if (res.status === 401) return
      if (res.ok && typeof data.confirmation_url === 'string' && data.confirmation_url) {
        window.open(data.confirmation_url, '_top')
        return
      }
      let text = (lang === 'ro' ? 'Abonamentul nu a putut fi creat: ' : 'The subscription could not be created: ') + errorText(data, res)
      if (data.demo_mode) {
        text += lang === 'ro'
          ? ' (mod demo — facturarea Shopify nu este disponibilă pentru acest magazin acum).'
          : ' (demo mode — Shopify Billing is not available for this store right now).'
      }
      setBillingFeedback({ type: 'error', text })
    } catch (e) {
      setBillingFeedback({ type: 'error', text: (lang === 'ro' ? 'Eroare de rețea: ' : 'Network error: ') + e.message })
    } finally {
      setSubscribing(false)
    }
  }

  const toggleTask = (idx) => {
    setCompletedTasks(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  // ── Derived, honest display values ──
  const notConnected = !!snapshot && snapshot.connected === false
  const dataOk = !!snapshot && snapshot.connected !== false
  const currency = (snapshot && snapshot.currency) || 'EUR'
  const showNum = (v, digits) => (dataOk ? fmtNum(v, digits) : DASH)
  const healthScore = dataOk && isNum(briefing?.health_score) ? Math.round(briefing.health_score) : null
  const topTasks = asArray(briefing?.top_tasks).filter((x) => x && (typeof x === 'object' || typeof x === 'string'))
  const briefingAlerts = asArray(briefing?.alerts).filter((x) => x && (typeof x === 'object' || typeof x === 'string'))
  const vipTop = dataOk ? asArray(snapshot?.vip_customers)[0] : null
  const updatedAtText = lastUpdated ? fmtTime(lastUpdated, locale) : DASH
  const isPro = plan === 'pro'
  const planLabel = plan === 'pro' ? 'PRO' : plan === 'free' ? (lang === 'ro' ? 'GRATUIT' : 'FREE') : (plan ? String(plan).toUpperCase() : DASH)

  // Autopilot status derived from the daemon's real state
  const daemon = (autopilotData && typeof autopilotData.daemon === 'object' && autopilotData.daemon) || {}
  const intervalMin = isNum(daemon.interval_minutes) ? daemon.interval_minutes : 5
  const lastCycleMin = minutesSince(daemon.last_cycle_at)
  const autopilotConnected = autopilotData ? autopilotData.connected !== false && !notConnected : !notConnected
  let autopilotBadge
  if (!autopilotData) {
    autopilotBadge = { text: lang === 'ro' ? 'Stare pilot automat: se încarcă / indisponibilă' : 'Autopilot status: loading / unavailable', color: '#94a3b8' }
  } else if (!autopilotConnected) {
    autopilotBadge = { text: lang === 'ro' ? 'Shopify neconectat — pilotul automat nu poate citi coșurile' : 'Shopify not connected — autopilot cannot read checkouts', color: '#f87171' }
  } else if (daemon.is_running === false) {
    autopilotBadge = { text: lang === 'ro' ? 'Pilot automat oprit' : 'Autopilot stopped', color: '#f87171' }
  } else if (lastCycleMin === null) {
    autopilotBadge = { text: lang === 'ro' ? 'Pilot automat: nu a rulat încă' : 'Autopilot: has not run yet', color: '#f59e0b' }
  } else if (lastCycleMin > intervalMin * 3) {
    autopilotBadge = { text: (lang === 'ro' ? 'Ultimul ciclu: ' : 'Last cycle: ') + agoText(lastCycleMin, lang) + (lang === 'ro' ? ' (întârziat)' : ' (late)'), color: '#f59e0b' }
  } else {
    autopilotBadge = { text: (lang === 'ro' ? 'Ultimul ciclu: ' : 'Last cycle: ') + agoText(lastCycleMin, lang), color: '#10b981' }
  }
  const autopilotQueue = asArray(autopilotData?.queue).filter((it) => it && typeof it === 'object')
  const queueLangs = Array.from(new Set(autopilotQueue
    .map((it) => (it && (it.detected_flag || it.detected_lang_name || it.detected_lang)) || null)
    .filter(Boolean)))
  const frequencyPolicy = complianceStats ? (complianceStats.frequency_policy || complianceStats.frequency_caps || null) : null
  const frequencyRows = policyEntries(frequencyPolicy)
  const frequencySummary = frequencyRows.length
    ? frequencyRows.slice(0, 2).map(([k, v]) => `${humanizeKey(k)}: ${humanizeValue(v)}`).join(' • ')
    : null
  const quietLabel = complianceStats ? (complianceStats.quiet_hours_label || complianceStats.quiet_hours_schedule || null) : null
  const consentStats = complianceStats && typeof complianceStats.consent_stats === 'object' && complianceStats.consent_stats ? complianceStats.consent_stats : null

  // Feed / SEO / DNS derived values
  const feedUrl = feedValidation && typeof feedValidation.feed_url === 'string' && feedValidation.feed_url ? feedValidation.feed_url : null
  const feedErrors = asArray(feedValidation?.errors)
  const feedWarnings = asArray(feedValidation?.warnings)
  const feedSkipped = asArray(feedValidation?.skipped)
  const dnsScore = isNum(dnsAuditData?.score) ? dnsAuditData.score : null
  const dnsMissing = asArray(dnsAuditData?.missing_records)
  const seoKeywords = asArray(seoData?.keywords).filter((k) => k && (typeof k === 'object' || typeof k === 'string'))
  const kwHasVolume = seoKeywords.some((k) => k && isNum(k.volume))
  const kwHasDifficulty = seoKeywords.some((k) => k && isNum(k.difficulty))
  const kwHasCpc = seoKeywords.some((k) => k && isNum(k.cpc))

  if (loading) {
    return (
      <div className="jarvis-root loading-state">
        <div className="reactor-core pulse-fast">
          <div className="ring ring-1"></div>
          <div className="ring ring-2"></div>
          <div className="core-glow"></div>
        </div>
        <div className="loading-text">{lang === 'ro' ? 'SE ÎNCARCĂ JARVIS — GROZAVU...' : 'LOADING JARVIS — GROZAVU...'}</div>
        <div className="loading-sub">{lang === 'ro' ? 'Se citesc datele magazinului din Shopify' : 'Reading store data from Shopify'}</div>
        <style>{styles}</style>
      </div>
    )
  }

  return (
    <div className="jarvis-root">
      <style>{styles}</style>

      {/* Toast Notification */}
      {toastMessage && (
        <div className="floating-toast">
          {toastMessage}
        </div>
      )}

      {/* ── TOP HUD HEADER ── */}
      <header className="hud-header">
        <div className="hud-brand">
          <div className={`reactor-mini ${isSpeaking ? 'speaking' : ''}`}>
            <div className="core-dot"></div>
          </div>
          <div>
            <div className="brand-title">
              GROZAVU <span className="brand-badge" title={lang === 'ro' ? 'Planul Jarvis' : 'Jarvis plan'}>PLAN {planLabel}</span>
            </div>
            <div className="brand-status">
              <span className="live-indicator" style={dataOk ? undefined : { background: notConnected ? '#ef4444' : '#94a3b8', boxShadow: 'none' }}></span>
              {notConnected ? t.telemetry_disconnected : (dataOk ? t.telemetry_connected : (lang === 'ro' ? 'STARE SHOPIFY NECUNOSCUTĂ' : 'SHOPIFY STATUS UNKNOWN'))}
              {lastUpdated ? ` • ${t.updated_at} ${updatedAtText}` : ''} • maisongrozavu.com
            </div>
          </div>
        </div>

        <div className="hud-actions">
          {/* Language Switcher */}
          <div className="lang-switcher">
            <button className={`lang-btn ${lang === 'en' ? 'active' : ''}`} onClick={() => handleSetLang('en')}>
              🇺🇸 EN
            </button>
            <button className={`lang-btn ${lang === 'ro' ? 'active' : ''}`} onClick={() => handleSetLang('ro')}>
              🇷🇴 RO
            </button>
          </div>

          <button
            className={`hud-btn ${voiceEnabled ? 'active' : ''}`}
            onClick={() => {
              if (isSpeaking && window.speechSynthesis) window.speechSynthesis.cancel()
              setVoiceEnabled(!voiceEnabled)
            }}
            title="Toggle Jarvis Voice"
          >
            {voiceEnabled ? t.voice_active : t.voice_mute}
          </button>

          {plan === 'free' && (
            <button className="upgrade-glow-btn" onClick={() => setActiveTab('plans')}>
              {t.upgrade_btn}
            </button>
          )}
        </div>
      </header>

      {/* ── ACCESS KEY CARD (401 auth_required) ── */}
      {authRequired && (
        <div className="hud-card auth-card">
          <div className="card-title">
            <span>🔐 {lang === 'ro' ? 'Cheie de acces Jarvis' : 'Jarvis access key'}</span>
          </div>
          <p className="card-desc">
            {lang === 'ro'
              ? 'Serverul Jarvis cere autentificare. Dacă deschizi Jarvis din Shopify Admin, reîncarcă aplicația de acolo. Dacă îl deschizi direct, introdu cheia de acces (JARVIS_ADMIN_KEY). Cheia se păstrează doar în acest browser.'
              : 'The Jarvis server requires authentication. If you open Jarvis from Shopify Admin, reload the app there. If you open it directly, enter the access key (JARVIS_ADMIN_KEY). The key is kept only in this browser.'}
          </p>
          {authAttempted && (
            <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
              {lang === 'ro' ? 'Cheia introdusă nu a fost acceptată. Verifică-o și încearcă din nou.' : 'The key was not accepted. Check it and try again.'}
            </div>
          )}
          <div className="auth-row">
            <input
              type="password"
              className="auth-input"
              autoComplete="current-password"
              placeholder={lang === 'ro' ? 'Cheie de acces Jarvis' : 'Jarvis access key'}
              value={authKeyInput}
              onChange={(e) => setAuthKeyInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSaveAuthKey()}
            />
            <button className="save-btn" onClick={handleSaveAuthKey}>
              {lang === 'ro' ? 'Salvează' : 'Save'}
            </button>
            {hasAdminKey() && (
              <button className="test-btn" onClick={handleForgetAuthKey}>
                {lang === 'ro' ? 'Șterge cheia salvată' : 'Forget saved key'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── SHOPIFY NOT CONNECTED BANNER ── */}
      {notConnected && (
        <div className="status-banner danger">
          <strong>⚠️ {lang === 'ro'
            ? 'Shopify nu este conectat — nu afișăm cifre. Instalează/reconectează aplicația.'
            : 'Shopify is not connected — no numbers are shown. Install/reconnect the app.'}</strong>
          {snapshot?.data_error && <div className="status-banner-detail">{String(snapshot.data_error)}</div>}
        </div>
      )}

      {dataOk && snapshot?.data_error && (
        <div className="status-banner warning">
          <strong>⚠️ {lang === 'ro' ? 'Unele date Shopify nu au putut fi citite:' : 'Some Shopify data could not be read:'}</strong> {String(snapshot.data_error)}
        </div>
      )}

      {loadError && !authRequired && (
        <div className="status-banner warning">
          <strong>⚠️ {lang === 'ro' ? 'Nu am putut încărca datele magazinului:' : 'Could not load store data:'}</strong> {loadError}
          <button className="test-btn" style={{ marginLeft: '12px' }} onClick={() => { loadedRef.current.clear(); setReloadToken((n) => n + 1) }}>
            {lang === 'ro' ? 'Reîncearcă' : 'Retry'}
          </button>
        </div>
      )}

      {/* ── NAVIGATION MATRIX ── */}
      <nav className="hud-nav">
        <button
          className={`nav-item ${activeTab === 'hud' ? 'active' : ''}`}
          onClick={() => setActiveTab('hud')}
        >
          <span className="nav-icon">🧠</span> {t.tab_hud}
        </button>
        <button
          className={`nav-item ${activeTab === 'radar' ? 'active' : ''}`}
          onClick={() => setActiveTab('radar')}
        >
          <span className="nav-icon">🌐</span> {t.tab_radar}
        </button>
        <button
          className={`nav-item ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
        >
          <span className="nav-icon">⚡</span> {t.tab_actions}
        </button>
        <button
          className={`nav-item ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          <span className="nav-icon">💬</span> {t.tab_chat}
        </button>
        <button
          className={`nav-item ${activeTab === 'autopilot' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('autopilot')
            if (activeTab !== 'autopilot') loadAutopilotStatus()
          }}
        >
          <span className="nav-icon">🤖</span> {t.tab_autopilot}
          {isNum(autopilotData?.pending_carts_count) && autopilotData.pending_carts_count > 0 && (
            <span className="nav-pill pulse-badge">{autopilotData.pending_carts_count}</span>
          )}
        </button>
        <button
          className={`nav-item ${activeTab === 'plans' ? 'active' : ''}`}
          onClick={() => setActiveTab('plans')}
        >
          <span className="nav-icon">💎</span> {t.tab_plans}
        </button>
      </nav>

      {/* ── MAIN CONTENT AREA ── */}
      <main className="hud-body">

        {/* ════ TAB 1: HUD & STORE BRAIN DIAGNOSTICS ════ */}
        {activeTab === 'hud' && (
          <div className="view-grid">
            {/* Health Score & Live Voice Report Card */}
            <div className="hud-card hero-card">
              <div className="hero-flex">
                <div className="reactor-large-box">
                  <div className={`reactor-core ${isSpeaking ? 'pulse-speaking' : 'pulse-slow'}`}>
                    <div className="ring ring-1"></div>
                    <div className="ring ring-2"></div>
                    <div className="ring ring-3"></div>
                    <div className="core-glow">
                      <div className="health-number">{healthScore === null ? DASH : `${healthScore}%`}</div>
                      <div className="health-label">{t.health_score_label}</div>
                    </div>
                  </div>
                </div>

                <div className="hero-info">
                  <div className="greeting-line">{(typeof briefing?.greeting === 'string' && briefing.greeting) || (lang === 'ro' ? 'Bună ziua! Jarvis la raport.' : 'Hello! Jarvis reporting.')}</div>
                  <div className="summary-text">{typeof briefing?.summary === 'string' ? briefing.summary : ''}</div>

                  <div className="hero-buttons">
                    <button className="speak-btn" onClick={triggerVoiceBriefing}>
                      {isSpeaking ? t.stop_voice : t.listen_briefing}
                    </button>
                    <button 
                      className="instant-diag-btn"
                      onClick={() => {
                        setActiveTab('chat')
                        handleSendMessage(t.chip_diagnosis)
                      }}
                    >
                      {t.quick_diagnosis_btn}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Live Metrics Grid */}
            <div className="metrics-row">
              <div className="metric-card">
                <div className="metric-header">{t.orders_today}</div>
                <div className="metric-value">{showNum(snapshot?.orders_today)}</div>
                <div className="metric-footer">{dataOk ? `${t.orders_sub} ${updatedAtText}` : (lang === 'ro' ? 'indisponibil' : 'unavailable')}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.revenue_today}</div>
                <div className="metric-value">
                  {showNum(snapshot?.revenue_today, 2)} {dataOk && <span className="currency">{currency}</span>}
                </div>
                <div className="metric-footer">{t.revenue_30d} {showNum(snapshot?.revenue_30d, 2)}{dataOk ? ` ${currency}` : ''}</div>
              </div>

              <div className="metric-card alert-border">
                <div className="metric-header">{t.abandoned_carts}</div>
                <div className="metric-value critical">{showNum(snapshot?.abandoned_carts)}</div>
                <div className="metric-footer highlight-orange">
                  {!dataOk || !isNum(snapshot?.abandoned_carts)
                    ? (lang === 'ro' ? 'indisponibil' : 'unavailable')
                    : (snapshot.abandoned_carts > 0 ? t.abandoned_alert : t.abandoned_ok)}
                </div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.new_customers}</div>
                <div className="metric-value">{showNum(snapshot?.new_customers_24h)}</div>
                <div className="metric-footer">{t.customers_sub}</div>
              </div>
            </div>

            {/* Customer Intelligence & Retention Metrics */}
            <div className="metrics-row customer-row">
              <div className="metric-card">
                <div className="metric-header">{t.aov_label}</div>
                <div className="metric-value">
                  {showNum(snapshot?.aov, 2)} {dataOk && <span className="currency">{currency}</span>}
                </div>
                <div className="metric-footer highlight-gold">{t.aov_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.retention_label}</div>
                <div className="metric-value highlight-gold">
                  {dataOk && isNum(snapshot?.returning_rate) ? `${fmtNum(snapshot.returning_rate)}%` : DASH}
                </div>
                <div className="metric-footer">{showNum(snapshot?.repeat_customers)} {t.retention_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.unique_buyers_label}</div>
                <div className="metric-value">{showNum(snapshot?.total_unique_customers)}</div>
                <div className="metric-footer">{t.unique_buyers_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.vip_customer_label}</div>
                <div className="metric-value vip-name">
                  {vipTop && vipTop.name ? String(vipTop.name) : DASH}
                </div>
                <div className="metric-footer highlight-gold">
                  {vipTop && isNum(Number(vipTop.total_spent)) && vipTop.total_spent !== null && vipTop.total_spent !== ''
                    ? `${Number(vipTop.total_spent).toFixed(2)} ${currency}`
                    : (lang === 'ro' ? 'Niciun client VIP încă' : 'No VIP customer yet')}
                </div>
              </div>
            </div>

            {/* Strategic Briefing & Daily Action List */}
            <div className="two-columns">
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.tactical_plan}</span>
                  <span className="tag-live">{t.ai_prioritized}</span>
                </div>
                <div className="tasks-list">
                  {topTasks.length > 0 ? (
                    topTasks.map((task, i) => (
                      <div key={i} className={`task-item ${completedTasks[i] ? 'done' : ''}`} onClick={() => toggleTask(i)}>
                        <input type="checkbox" checked={!!completedTasks[i]} readOnly />
                        <div className="task-content">
                          <div className="task-title">
                            {(task && task.icon) || '📌'} {task && (isNum(task.priority) || typeof task.priority === 'string') ? `#${task.priority}: ` : ''}{typeof task === 'string' ? task : (task && task.task) || ''}
                          </div>
                          {task && task.why && <div className="task-why">{String(task.why)}</div>}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty-notice">{t.analyzing_priorities}</div>
                  )}
                </div>
              </div>

              {/* Traffic Advice & Smart Alerts */}
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.traffic_strategy}</span>
                </div>

                {typeof briefing?.traffic_tip === 'string' && briefing.traffic_tip && (
                  <div className="traffic-box">
                    <div className="traffic-tag">{t.daily_growth_tip} • {lang === 'ro' ? 'idee AI' : 'AI idea'}</div>
                    <div className="traffic-desc">{briefing.traffic_tip}</div>
                  </div>
                )}

                <div className="alerts-box">
                  <div className="box-subtitle">{t.auto_diagnostics}</div>
                  {briefingAlerts.length > 0 ? (
                    briefingAlerts.map((al, idx) => (
                      <div key={idx} className="alert-item">
                        <span className="alert-icon">⚡</span>
                        <div>
                          <strong>{typeof al === 'string' ? al : (al && al.message) || ''}</strong>
                          {al && typeof al === 'object' && al.action && <div className="alert-action">{String(al.action)}</div>}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className={`alert-item ${dataOk ? 'green' : ''}`}>
                      <span className="alert-icon">{dataOk ? '🛡️' : '⚠️'}</span>
                      <div>{dataOk ? t.store_nominal : t.diagnostics_unavailable}</div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ════ TAB 2: RADAR TRAFIC & GOOGLE LEAD HUNTER ════ */}
        {activeTab === 'radar' && (
          <div className="radar-view">
            <div className="subnav-pills">
              <button 
                className={`subnav-pill ${activeRadarSubtab === 'google-merchant' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('google-merchant')}
              >
                🛒 Google Shopping & Feed
              </button>
              <button 
                className={`subnav-pill ${activeRadarSubtab === 'deliverability' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('deliverability')}
              >
                🛡️ Livrabilitate & Anti-Spam (DNS)
              </button>
              <button 
                className={`subnav-pill ${activeRadarSubtab === 'seo' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('seo')}
              >
                🔍 Google SEO & Sugestii Căutare
              </button>
              <button 
                className={`subnav-pill ${activeRadarSubtab === 'hunter' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('hunter')}
              >
                📱 Vânător Clienți TikTok & Social
              </button>
              <button 
                className={`subnav-pill ${activeRadarSubtab === 'goal' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('goal')}
              >
                🎯 Simulator Țintă (/goal)
              </button>
            </div>

            {/* Subtab 0A: Google Merchant Center & Shopping Feed */}
            {activeRadarSubtab === 'google-merchant' && (
              <div className="radar-content-grid">
                <div className="hud-card">
                  <div className="card-title">
                    <span>🛒 Feed Google Merchant Center (listări gratuite Google Shopping)</span>
                    <span className="tag-live" style={{ background: '#065f46', color: '#6ee7b7' }}>Listări gratuite Google</span>
                  </div>
                  <p className="card-desc">
                    Google Shopping are listări gratuite (free listings) pentru produsele magazinului; reclamele Shopping sunt separate și plătite.
                    Jarvis generează acest feed XML din produsele Shopify și îl verifică după specificațiile Google.
                  </p>

                  {(feedValidation?.connected === false || notConnected) && (
                    <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
                      Shopify nu este conectat — feed-ul nu conține produse reale.
                    </div>
                  )}
                  {typeof feedValidation?.error === 'string' && feedValidation.error && (
                    <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
                      Validarea feed-ului nu a reușit: {feedValidation.error}
                    </div>
                  )}

                  <div className="feed-url-box" style={{ background: '#1c1917', padding: '16px', borderRadius: '8px', border: '1px solid #78350f', margin: '16px 0' }}>
                    <div style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600, marginBottom: '8px' }}>
                      🔗 LINK FEED XML PENTRU GOOGLE MERCHANT:
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <input
                        type="text"
                        readOnly
                        value={feedUrl || (feedValidation ? 'indisponibil' : 'se încarcă...')}
                        style={{ flex: 1, minWidth: '220px', padding: '10px 14px', background: '#0c0a09', border: '1px solid #451a03', color: '#fef3c7', borderRadius: '6px', fontFamily: 'monospace', fontSize: '13px' }}
                      />
                      <button
                        className="calculate-btn"
                        disabled={!feedUrl}
                        onClick={() => handleCopy(feedUrl, 'Link-ul feed-ului Google a fost copiat!')}
                      >
                        📋 Copiază Link
                      </button>
                      {feedUrl && (
                        <a
                          href={feedUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="calculate-btn"
                          style={{ textDecoration: 'none', textAlign: 'center', lineHeight: '22px' }}
                        >
                          👁️ Vezi XML
                        </a>
                      )}
                      <button
                        className="test-btn"
                        onClick={() => { loadFeedValidation() }}
                      >
                        🔄 Re-verifică
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginTop: '16px' }}>
                    <div style={{ background: '#292524', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                      <div style={{ fontSize: '11px', color: '#a8a29e' }}>STATUS VALIDARE SPECIFICAȚIE</div>
                      <div style={{ fontSize: '16px', fontWeight: 700, color: feedValidation?.valid === true ? '#10b981' : feedValidation?.valid === false ? '#f87171' : '#94a3b8', marginTop: '4px' }}>
                        {feedValidation?.valid === true
                          ? '✅ Conform specificației Google'
                          : feedValidation?.valid === false
                            ? `❌ Feed-ul are erori (${feedErrors.length})`
                            : `❔ ${DASH}`}
                      </div>
                    </div>
                    <div style={{ background: '#292524', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                      <div style={{ fontSize: '11px', color: '#a8a29e' }}>PRODUSE ÎN FEED</div>
                      <div style={{ fontSize: '16px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>
                        📦 {fmtNum(feedValidation?.items_count)} produse
                        {isNum(feedValidation?.product_groups) ? ` • ${feedValidation.product_groups} grupuri` : ''}
                      </div>
                    </div>
                    <div style={{ background: '#292524', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                      <div style={{ fontSize: '11px', color: '#a8a29e' }}>AVERTISMENTE / PRODUSE OMISE</div>
                      <div style={{ fontSize: '16px', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
                        ⚠️ {isNum(feedValidation?.warnings_count) ? feedValidation.warnings_count : (feedValidation ? feedWarnings.length : DASH)} • omise: {feedValidation ? feedSkipped.length : DASH}
                      </div>
                    </div>
                  </div>

                  {(feedErrors.length > 0 || feedWarnings.length > 0 || feedSkipped.length > 0) && (
                    <div className="tips-box" style={{ marginTop: '16px' }}>
                      {feedErrors.length > 0 && (
                        <>
                          <div className="box-subtitle" style={{ color: '#f87171' }}>Erori:</div>
                          <ul className="plain-list">
                            {feedErrors.slice(0, 20).map((er, i) => <li key={`e${i}`}>• {typeof er === 'string' ? er : JSON.stringify(er)}</li>)}
                          </ul>
                        </>
                      )}
                      {feedWarnings.length > 0 && (
                        <>
                          <div className="box-subtitle">Avertismente:</div>
                          <ul className="plain-list">
                            {feedWarnings.slice(0, 20).map((w, i) => <li key={`w${i}`}>• {typeof w === 'string' ? w : JSON.stringify(w)}</li>)}
                          </ul>
                        </>
                      )}
                      {feedSkipped.length > 0 && (
                        <>
                          <div className="box-subtitle">Produse omise din feed:</div>
                          <ul className="plain-list">
                            {feedSkipped.slice(0, 20).map((sk, i) => (
                              <li key={`s${i}`}>• {(sk && (sk.product || sk.title)) || DASH}: {(sk && sk.reason) || DASH}</li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}

                  <div className="tips-box" style={{ marginTop: '20px' }}>
                    <div className="box-subtitle">📖 Cum conectezi Google Merchant Center (alege O SINGURĂ variantă):</div>
                    <ol style={{ paddingLeft: '20px', lineHeight: '1.8', color: '#e7e5e4', fontSize: '14px', margin: '10px 0' }}>
                      <li><strong>Varianta recomandată:</strong> în Shopify Admin → Apps instalează aplicația oficială gratuită <strong>Google & YouTube</strong> și conectează contul Google Merchant Center. Aplicația sincronizează singură produsele.</li>
                      <li><strong>Sau</strong>, fără aplicație: în Google Merchant Center (<em>Products &gt; Feeds</em>) adaugă link-ul feed-ului de mai sus ca <strong>Primary Feed</strong> cu actualizare zilnică.</li>
                      <li>⚠️ Nu le folosi pe amândouă în același timp — produsele ar apărea dublate în Merchant Center.</li>
                      <li>După aprobarea Google, produsele pot apărea în listările gratuite din tab-ul <strong>Cumpărături</strong>. Google decide afișarea; nu există garanție de trafic.</li>
                    </ol>
                  </div>
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>🔍 Propuneri SEO Produse (previzualizare — nu modifică Shopify)</span>
                    <button
                      className="calculate-btn"
                      onClick={handleRunSeoOptimization}
                      disabled={optimizingSeo}
                    >
                      {optimizingSeo ? 'Se generează propunerile...' : '🧪 Generează propuneri SEO (previzualizare)'}
                    </button>
                  </div>
                  <p className="card-desc">
                    Jarvis analizează produsele din Shopify și propune titluri SEO, meta-descrieri și texte alternative pentru imagini.
                    Propunerile sunt doar o previzualizare: le verifici și le aplici tu manual în Shopify Admin.
                  </p>

                  {seoAuditData?.connected === false && (
                    <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
                      Shopify nu este conectat — nu există produse reale de auditat.
                    </div>
                  )}

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', margin: '16px 0' }}>
                    <div style={{ background: '#292524', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                      <div style={{ fontSize: '11px', color: '#a8a29e' }}>SCOR MEDIU SEO CATALOG</div>
                      <div style={{ fontSize: '20px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>
                        {isNum(seoAuditData?.average_seo_score) ? `${fmtNum(seoAuditData.average_seo_score)}/100` : DASH}
                      </div>
                    </div>
                    <div style={{ background: '#292524', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                      <div style={{ fontSize: '11px', color: '#a8a29e' }}>PRODUSE AUDITATE</div>
                      <div style={{ fontSize: '20px', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>
                        {fmtNum(seoAuditData?.products_audited)}
                        {isNum(seoAuditData?.needs_optimization_count) ? ` • ${seoAuditData.needs_optimization_count} de îmbunătățit` : ''}
                      </div>
                    </div>
                  </div>

                  {seoProposals && (
                    <div style={{ marginBottom: '16px' }}>
                      <div className={`delivery-alert ${seoProposals.written > 0 ? 'error' : 'success'}`} style={{ marginBottom: '10px' }}>
                        {seoProposals.written > 0
                          ? `⚠️ Backend-ul raportează ${seoProposals.written} modificări scrise în Shopify.`
                          : 'ℹ️ Nimic nu a fost modificat în Shopify. Acestea sunt doar propuneri.'}
                      </div>
                      {seoProposals.items.length === 0 ? (
                        <div className="empty-notice">Nicio propunere: nu există produse sau nu e nimic de îmbunătățit.</div>
                      ) : (
                        <div style={{ maxHeight: '420px', overflowY: 'auto', background: '#1c1917', borderRadius: '8px', border: '1px solid #44403c', padding: '10px' }}>
                          {seoProposals.items.map((prod, pi) => (
                            <div key={pi} style={{ padding: '10px 12px', borderBottom: '1px solid #292524' }}>
                              <div style={{ color: '#fef3c7', fontWeight: 700, fontSize: '13px', marginBottom: '6px' }}>
                                {(prod && prod.title) || DASH}
                              </div>
                              {asArray(prod && prod.proposals).length === 0 ? (
                                <div style={{ color: '#a8a29e', fontSize: '12px' }}>Nicio modificare propusă.</div>
                              ) : (
                                asArray(prod.proposals).map((pr, ri) => (
                                  <div key={ri} className="seo-proposal-row">
                                    <div><span style={{ color: '#f59e0b', fontWeight: 600 }}>[{(pr && pr.field) || DASH}]</span></div>
                                    <div><span className="muted-label">Acum:</span> {pr && pr.current ? String(pr.current) : DASH}</div>
                                    <div><span className="muted-label">Propus:</span> <span style={{ color: '#6ee7b7' }}>{pr && pr.proposed ? String(pr.proposed) : DASH}</span></div>
                                    {pr && pr.reason && <div><span className="muted-label">Motiv:</span> {String(pr.reason)}</div>}
                                    {pr && pr.proposed && (
                                      <button className="copy-btn-micro" onClick={() => handleCopy(String(pr.proposed), 'Propunerea a fost copiată!')}>
                                        📋 Copiază propunerea
                                      </button>
                                    )}
                                  </div>
                                ))
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="box-subtitle" style={{ color: '#fef3c7', fontSize: '14px', fontWeight: 600, marginTop: '20px', marginBottom: '8px' }}>
                    📜 Jurnal SEO (înregistrări din baza de date Jarvis):
                  </div>
                  <div style={{ maxHeight: '250px', overflowY: 'auto', background: '#1c1917', borderRadius: '8px', border: '1px solid #44403c', padding: '10px' }}>
                    {seoLogs && seoLogs.length > 0 ? (
                      seoLogs.map((logItem, idx) => {
                        const st = logStatusUi(logItem && logItem.status)
                        const newVal = logItem && typeof logItem.new_value === 'string' ? logItem.new_value : ''
                        return (
                          <div key={idx} style={{ padding: '8px 12px', borderBottom: '1px solid #292524', fontSize: '13px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <span style={{ color: '#f59e0b', fontWeight: 600 }}>[{(logItem && logItem.change_type) || DASH}]</span>{' '}
                              <span style={{ color: '#e7e5e4' }}>{(logItem && logItem.product_title) || DASH}:</span>{' '}
                              <span style={{ color: '#a8a29e' }}>{newVal.length > 70 ? `${newVal.slice(0, 70)}...` : newVal}</span>
                            </div>
                            <span style={{ color: st.color, fontSize: '11px', whiteSpace: 'nowrap', marginLeft: '12px' }}>
                              {st.text}{logItem && logItem.applied_at ? ` • ${fmtDateTime(logItem.applied_at, locale)}` : ''}
                            </span>
                          </div>
                        )
                      })
                    ) : (
                      <div style={{ padding: '12px', color: '#a8a29e', fontSize: '13px', textAlign: 'center' }}>
                        Nicio înregistrare în jurnalul SEO.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Subtab 0B: Deliverability & Anti-Spam DNS Audit */}
            {activeRadarSubtab === 'deliverability' && (
              <div className="radar-content-grid">
                <div className="hud-card">
                  <div className="card-title">
                    <span>🛡️ Verificare DNS domeniu (SPF / DKIM / DMARC)</span>
                    <span className="tag-live" style={{ background: dnsScore === null ? '#292524' : dnsScore >= 90 ? '#065f46' : '#78350f', color: '#fef3c7' }}>
                      Scor: {dnsScore === null ? DASH : `${fmtNum(dnsScore)}/100`}
                    </span>
                  </div>
                  <p className="card-desc">
                    Domeniul <strong>maisongrozavu.com</strong> trimite emailuri comerciale și de recuperare a coșurilor.
                    Gmail, Yahoo și Apple Mail cer autentificare DNS (SPF, DKIM, DMARC) pentru o livrabilitate bună.
                  </p>

                  {typeof dnsAuditData?.error === 'string' && dnsAuditData.error && (
                    <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
                      Verificarea DNS nu a reușit: {dnsAuditData.error}
                    </div>
                  )}

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px', margin: '20px 0' }}>
                    {[
                      { key: 'spf', title: 'SPF', desc: 'Autorizează serverele furnizorului de email (Resend) să trimită în numele domeniului.' },
                      { key: 'dkim', title: 'DKIM', desc: 'Semnătură criptografică ce arată că mesajul nu a fost modificat în tranzit.' },
                      { key: 'dmarc', title: 'DMARC', desc: 'Politica domeniului împotriva phishing-ului și raportare către furnizori.' }
                    ].map(({ key, title, desc }) => {
                      const check = dnsAuditData && dnsAuditData.checks ? dnsAuditData.checks[key] : null
                      const st = DNS_STATUS_UI[dnsAuditData ? dnsStatus(check) : 'unknown']
                      const note = dnsCheckNote(check)
                      return (
                        <div key={key} style={{ background: '#1c1917', padding: '16px', borderRadius: '10px', border: `1px solid ${st.border}` }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontWeight: 700, color: '#fef3c7', fontSize: '14px' }}>{title}</span>
                            <span style={{ color: st.color, fontSize: '12px', fontWeight: 600 }}>
                              {dnsAuditData ? st.label : 'se verifică...'}
                            </span>
                          </div>
                          <p style={{ fontSize: '12px', color: '#a8a29e', margin: '8px 0' }}>{desc}</p>
                          <div style={{ fontSize: '11px', fontFamily: 'monospace', background: '#0c0a09', padding: '6px 8px', borderRadius: '4px', color: '#6ee7b7', wordBreak: 'break-all' }}>
                            {dnsRecordText(check)}
                          </div>
                          {note && <p style={{ fontSize: '11px', color: '#f59e0b', margin: '6px 0 0' }}>{note}</p>}
                        </div>
                      )
                    })}
                  </div>

                  {dnsMissing.length > 0 && (
                    <div className="tips-box" style={{ marginBottom: '16px' }}>
                      <div className="box-subtitle">🧩 Înregistrări DNS de adăugat / corectat:</div>
                      {dnsMissing.map((rec, i) => (
                        <div key={i} className="dns-missing-row">
                          <div><span className="muted-label">Tip:</span> <strong>{(rec && rec.type) || DASH}</strong> • <span className="muted-label">Host:</span> <code>{(rec && rec.host) || DASH}</code></div>
                          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px' }}>
                            <code style={{ flex: 1, wordBreak: 'break-all' }}>{(rec && rec.recommended_value) || DASH}</code>
                            {rec && rec.recommended_value && (
                              <button className="copy-btn-micro" onClick={() => handleCopy(String(rec.recommended_value), 'Valoarea DNS a fost copiată!')}>📋</button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="tips-box">
                    <div className="box-subtitle">📋 Ghid configurare DNS (o singură dată, la registrarul de domeniu):</div>
                    <ul style={{ paddingLeft: '18px', lineHeight: '1.7', color: '#e7e5e4', fontSize: '13px', margin: '8px 0' }}>
                      <li>1. Deschide panoul de administrare al domeniului (Cloudflare, GoDaddy, Namecheap etc.).</li>
                      <li>2. Mergi la secțiunea <strong>DNS Management</strong> / <strong>Înregistrări DNS</strong>.</li>
                      <li>3. Adaugă sau corectează înregistrările marcate mai sus, apoi apasă „Re-verifică” după propagare.</li>
                      <li>4. Autentificarea DNS corectă îmbunătățește livrabilitatea, dar nu garantează livrarea în Inbox.</li>
                    </ul>
                    <button className="test-btn" onClick={() => { loadDnsAudit() }}>🔄 Re-verifică DNS</button>
                  </div>
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>⚖️ Reguli Anti-Spam & Consimțământ (GDPR / LSSI)</span>
                    {complianceStats && (
                      <span className="tag-live" style={complianceStats.quiet_hours_active ? { background: '#1e293b', color: '#93c5fd', borderColor: '#93c5fd' } : undefined}>
                        {complianceStats.quiet_hours_active ? '🌙 Ore de liniște active acum' : 'În afara orelor de liniște'}
                      </span>
                    )}
                  </div>
                  <p className="card-desc">
                    Regulile de mai jos sunt citite din serverul Jarvis (/api/compliance/stats).
                  </p>

                  {!complianceStats ? (
                    <div className="empty-notice">Regulile de conformitate nu sunt disponibile acum.</div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', margin: '16px 0' }}>
                      <div style={{ background: '#1c1917', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                        <div style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600 }}>🌙 ORE DE LINIȘTE</div>
                        <p style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>
                          {quietLabel ? `${quietLabel} — fără mesaje de marketing în acest interval.` : 'Interval indisponibil.'}
                        </p>
                      </div>

                      <div style={{ background: '#1c1917', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                        <div style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600 }}>⏱️ LIMITE DE FRECVENȚĂ</div>
                        {frequencyRows.length > 0 ? (
                          <ul className="plain-list" style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>
                            {frequencyRows.map(([k, v]) => (
                              <li key={k}>• {k === 'description' ? humanizeValue(v) : `${humanizeKey(k)}: ${humanizeValue(v)}`}</li>
                            ))}
                          </ul>
                        ) : (
                          <p style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>Politica de frecvență nu este disponibilă.</p>
                        )}
                      </div>

                      <div style={{ background: '#1c1917', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                        <div style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600 }}>🔘 DEZABONARE 1-CLICK</div>
                        <p style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>
                          Fiecare email include antetul <code>List-Unsubscribe: One-Click</code> și link vizibil de opt-out în footer.
                        </p>
                      </div>

                      <div style={{ background: '#1c1917', padding: '14px', borderRadius: '8px', border: '1px solid #44403c' }}>
                        <div style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600 }}>🔒 CONSIMȚĂMINTE ÎNREGISTRATE</div>
                        {consentStats ? (
                          <ul className="plain-list" style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>
                            <li>• Cu acord de marketing activ: <strong>{fmtNum(consentStats.active_subscribers)}</strong></li>
                            <li>• Dezabonați / fără acord: <strong>{fmtNum(consentStats.unsubscribed)}</strong></li>
                            <li>• Total contacte înregistrate: <strong>{fmtNum(consentStats.total_recorded)}</strong></li>
                          </ul>
                        ) : (
                          <p style={{ fontSize: '12px', color: '#a8a29e', margin: '6px 0 0' }}>Statistici de consimțământ indisponibile.</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Subtab 1: Google SEO */}
            {activeRadarSubtab === 'seo' && (
              <div className="radar-content-grid">
                {/* Live Google Search Engine Scanner */}
                <div className="hud-card live-google-card">
                  <div className="card-title">
                    <span>🌐 Sugestii de căutare Google (Google Suggest)</span>
                    <span className="tag-live" style={liveSearchSource === 'google_suggest' ? undefined : { color: '#94a3b8', borderColor: '#94a3b8', background: 'rgba(148,163,184,0.12)' }}>
                      {liveSearchSource === 'google_suggest' ? 'Sursă: Google Suggest' : liveSearchSource ? 'Google indisponibil' : DASH}
                    </span>
                  </div>
                  <p className="card-desc">
                    Tastează o piesă vestimentară sau o categorie pentru a vedea sugestiile de autocompletare Google. Acestea nu sunt volume de căutare.
                  </p>
                  <div className="live-search-bar">
                    <input 
                      type="text"
                      className="live-search-input"
                      value={liveSearchQuery}
                      onChange={(e) => setLiveSearchQuery(e.target.value)}
                      placeholder="Ex: hanorac oversize, tricou boxy, windbreaker..."
                      onKeyDown={(e) => e.key === 'Enter' && !searchingGoogle && handleLiveGoogleSearch()}
                    />
                    <button 
                      className="calculate-btn"
                      onClick={() => handleLiveGoogleSearch()}
                      disabled={searchingGoogle}
                    >
                      {searchingGoogle ? 'Se caută...' : '🔎 Caută sugestii Google'}
                    </button>
                  </div>

                  {!searchingGoogle && liveSearchSource && liveSearchSource !== 'google_suggest' && (
                    <div className="empty-notice" style={{ marginTop: '12px' }}>Sugestii Google indisponibile acum.</div>
                  )}
                  {!searchingGoogle && liveSearchSource === 'google_suggest' && liveSearchResults.length === 0 && (
                    <div className="empty-notice" style={{ marginTop: '12px' }}>Google nu a returnat sugestii pentru „{liveSearchShownQuery}”.</div>
                  )}

                  {liveSearchSource === 'google_suggest' && liveSearchResults.length > 0 && (
                    <div className="live-results-box">
                      <div className="live-results-title">
                        Sugestii Google pentru „{liveSearchShownQuery}”:
                      </div>
                      <div className="live-tags-grid">
                        {liveSearchResults.map((resItem, idx) => (
                          <div key={idx} className="live-tag-chip">
                            <span className="live-tag-text">🔍 {resItem}</span>
                            <button 
                              className="copy-btn-micro" 
                              onClick={() => handleCopy(resItem, 'Expresia a fost copiată!')}
                              title="Copiază căutarea"
                            >
                              📋
                            </button>
                            <button 
                              className="chat-btn-micro"
                              onClick={() => {
                                setActiveTab('chat')
                                handleSendMessage(`/browser ${resItem}`)
                              }}
                              title="Cere strategie Jarvis pentru această căutare"
                            >
                              💬 Strategie
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>🎯 Idei de cuvinte cheie</span>
                    <span className="tag-live">Idei generate de AI</span>
                  </div>
                  <p className="card-desc">
                    Idei generate de AI, nu date reale de căutare. Verifică volumele în Google Keyword Planner sau Search Console înainte să le folosești.
                  </p>
                  {seoKeywords.length === 0 ? (
                    <div className="empty-notice">{seoData ? 'Nicio idee de cuvinte cheie.' : 'Ideile nu sunt disponibile acum.'}</div>
                  ) : (
                  <div className="keyword-table-wrapper">
                    <table className="custom-table">
                      <thead>
                        <tr>
                          <th>Cuvânt Cheie</th>
                          <th>Intenție</th>
                          {kwHasVolume && <th>Volum Căutări</th>}
                          {kwHasDifficulty && <th>Dificultate</th>}
                          {kwHasCpc && <th>CPC</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {seoKeywords.map((kw, i) => (
                          <tr key={i}>
                            <td className="bold-cell">🔍 {(kw && kw.keyword) || (typeof kw === 'string' ? kw : DASH)}</td>
                            <td>{kw && kw.intent ? <span className="badge-intent">{String(kw.intent)}</span> : DASH}</td>
                            {kwHasVolume && <td className="highlight-gold">{fmtNum(kw && kw.volume)}</td>}
                            {kwHasDifficulty && <td>{fmtNum(kw && kw.difficulty)}</td>}
                            {kwHasCpc && <td>{fmtNum(kw && kw.cpc)}</td>}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  )}
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>💎 Exemplu Schema.org JSON-LD (Google Product) — idee AI</span>
                    <button 
                      className="copy-btn-inline"
                      onClick={() => handleCopy(JSON.stringify(seoData?.json_ld || {}, null, 2), 'Codul JSON-LD a fost copiat!')}
                    >
                      📋 Copiază Codul JSON-LD
                    </button>
                  </div>
                  <p className="card-desc">
                    Exemplu de date structurate generat de AI. Temele Shopify includ de obicei deja aceste date; verifică-l înainte de a-l folosi și nu adăuga recenzii sau evaluări care nu există.
                  </p>
                  <div className="code-block">
                    <pre>{JSON.stringify(seoData?.json_ld || {}, null, 2)}</pre>
                  </div>

                  <div className="tips-box">
                    <div className="box-subtitle">🛍️ Recomandări Google Merchant Center (idei AI):</div>
                    <ul>
                      {asArray(seoData?.merchant_feed_tips).map((tip, idx) => (
                        <li key={idx}>• {typeof tip === 'string' ? tip : JSON.stringify(tip)}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {/* Subtab 2: Social Lead Hunter */}
            {activeRadarSubtab === 'hunter' && (
              <div className="radar-content-grid">
                <div className="hud-card">
                  <div className="card-title">
                    <span>🎬 Scenarii & Cârlige TikTok / Instagram Reels</span>
                    <span className="tag-live">Idei generate de AI</span>
                  </div>
                  {!radarData && <div className="empty-notice">Ideile nu sunt disponibile acum.</div>}
                  <div className="hooks-list">
                    {asArray(radarData?.hooks).filter((h) => h && typeof h === 'object').map((h, i) => (
                      <div key={i} className="hook-card">
                        <div className="hook-header">
                          <span className="hook-title">{h.title}</span>
                          {h.duration && <span className="hook-duration">⏱️ {h.duration}</span>}
                        </div>
                        <div className="hook-script">
                          {h.script}
                        </div>
                        <div className="hook-footer">
                          {h.best_sound ? <>🎵 <strong>Sunet sugerat:</strong> {h.best_sound}</> : null}
                          <button 
                            className="copy-btn-micro" 
                            onClick={() => handleCopy(h.script, 'Scenariul video a fost copiat!')}
                          >
                            📋 Copiază
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>💌 Script Outreach Creatori de Conținut (idee AI)</span>
                    <button 
                      className="copy-btn-inline"
                      onClick={() => handleCopy(radarData?.outreach_dm || '', 'Mesajul de outreach a fost copiat!')}
                    >
                      📋 Copiază Mesajul
                    </button>
                  </div>
                  <p className="card-desc">
                    Ciornă de mesaj pentru micro-creatori din nișa streetwear / modă. Verifică și personalizează înainte de trimitere:
                  </p>
                  <div className="dm-script-box">
                    {radarData?.outreach_dm}
                  </div>

                  <div className="personas-box">
                    <div className="box-subtitle">👑 Profiluri de cumpărător (idei AI):</div>
                    {asArray(radarData?.personas).filter((p) => p && typeof p === 'object').map((p, idx) => (
                      <div key={idx} className="persona-item">
                        <strong>{p.name}</strong>
                        <div className="persona-desc">Interese: {p.interests}</div>
                        <div className="persona-trigger">🎯 Declanșator Cumpărare: {p.trigger}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Subtab 3: Revenue Goal Simulator */}
            {activeRadarSubtab === 'goal' && (
              <div className="goal-simulator-grid">
                <div className="hud-card">
                  <div className="card-title">
                    <span>🎯 Simulator Venit (calcul pe ipoteze)</span>
                  </div>
                  <div className="goal-input-box">
                    <label>Țintă Venit Lunară ({snapshot?.currency || 'EUR'}):</label>
                    <div className="input-group">
                      <input 
                        type="number" 
                        value={goalTarget} 
                        min="1"
                        onChange={(e) => setGoalTarget(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !calculatingGoal && handleCalculateGoal()}
                        placeholder="10000"
                      />
                      <button 
                        className="calculate-btn"
                        onClick={handleCalculateGoal}
                        disabled={calculatingGoal}
                      >
                        {calculatingGoal ? 'Se calculează...' : 'Calculează Planul'}
                      </button>
                    </div>
                    {goalError && <div className="delivery-alert error">{goalError}</div>}
                  </div>

                  {goalData && (
                    <div className="goal-results-cards">
                      <div className="goal-stat-item">
                        <div className="stat-label">Comenzi Necesare / Lună</div>
                        <div className="stat-val highlight-gold">{fmtNum(goalData.needed_orders)}</div>
                        <div className="stat-sub">
                          La AOV de {fmtNum(goalData.aov, 2)} {goalData.currency || currency}
                          {!(dataOk && isNum(snapshot?.aov) && snapshot.aov > 0) ? ' (valoare presupusă — magazinul nu are încă un AOV real)' : ''}
                        </div>
                      </div>
                      <div className="goal-stat-item">
                        <div className="stat-label">Comenzi Necesare / Zi</div>
                        <div className="stat-val highlight-gold">{fmtNum(goalData.daily_orders)}</div>
                        <div className="stat-sub">Comenzi pe zi</div>
                      </div>
                      <div className="goal-stat-item">
                        <div className="stat-label">Trafic Necesar / Zi</div>
                        <div className="stat-val highlight-green">{fmtNum(goalData.scenarios?.cr_2_0?.daily_visitors)}</div>
                        <div className="stat-sub">Vizitatori pe zi, presupunând o rată de conversie de 2%</div>
                      </div>
                    </div>
                  )}

                  <div className="channel-distribution-box">
                    <div className="box-subtitle">🗺️ Mix de canale propus (ipoteză, nu date):</div>
                    <div className="channel-bars">
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>🔍 Google Organic & Shopping (40%)</span>
                          <span>{isNum(goalData?.channel_split?.google_search?.visitors_day) ? `~${fmtNum(goalData.channel_split.google_search.visitors_day)}` : DASH} vizitatori/zi</span>
                        </div>
                        <div className="progress-bg"><div className="progress-fill" style={{ width: '40%' }}></div></div>
                      </div>
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>📱 TikTok & Instagram Reels (40%)</span>
                          <span>{isNum(goalData?.channel_split?.tiktok_reels?.visitors_day) ? `~${fmtNum(goalData.channel_split.tiktok_reels.visitors_day)}` : DASH} vizitatori/zi</span>
                        </div>
                        <div className="progress-bg"><div className="progress-fill" style={{ width: '40%' }}></div></div>
                      </div>
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>📧 Recuperare Coșuri & Retenție (20%)</span>
                          <span>{isNum(goalData?.channel_split?.email_retention?.visitors_day) ? `~${fmtNum(goalData.channel_split.email_retention.visitors_day)}` : DASH} vizitatori/zi</span>
                        </div>
                        <div className="progress-bg"><div className="progress-fill" style={{ width: '20%' }}></div></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════ TAB 3: 1-CLICK CAMPAIGN TOOLS & BOOST ════ */}
        {activeTab === 'actions' && (
          <div>
            {/* Boost Proposals (AI ideas) */}
            <div className="hud-card boost-banner-card">
              <div className="card-title">
                <span>⚡ Idei rapide de conversie (/boost)</span>
                <span className="tag-live">Idei generate de AI</span>
              </div>
              <p className="card-desc">
                Idei generate de AI. Codurile de reducere și ofertele trebuie create și verificate de tine în Shopify înainte de a fi folosite.
              </p>
              {!boostData ? (
                <div className="empty-notice">Ideile nu sunt disponibile acum.</div>
              ) : (
              <div className="boost-proposals-grid">
                <div className="boost-proposal-item">
                  <div className="proposal-title">🛒 Banner de anunț (Top Bar)</div>
                  <div className="proposal-text">{typeof boostData.urgency_banner === 'string' && boostData.urgency_banner ? boostData.urgency_banner : DASH}</div>
                  <button 
                    className="copy-btn-micro" 
                    disabled={!boostData.urgency_banner}
                    onClick={() => handleCopy(boostData.urgency_banner || '', 'Bannerul a fost copiat!')}
                  >
                    📋 Copiază Banner
                  </button>
                </div>

                <div className="boost-proposal-item">
                  <div className="proposal-title">🎁 Ofertă în coș (Cart Bump)</div>
                  <div className="proposal-text">
                    {boostData.cart_bump && boostData.cart_bump.product_title ? (
                      <>
                        <strong>{String(boostData.cart_bump.product_title)}</strong>
                        {boostData.cart_bump.bump_price ? ` — ${boostData.cart_bump.bump_price}` : ''}
                        {boostData.cart_bump.discount ? ` (${boostData.cart_bump.discount})` : ''}
                      </>
                    ) : DASH}
                  </div>
                  <button
                    className="copy-btn-micro"
                    disabled={!(boostData.cart_bump && boostData.cart_bump.copy)}
                    onClick={() => handleCopy((boostData.cart_bump && boostData.cart_bump.copy) || '', 'Textul de cart bump a fost copiat!')}
                  >
                    📋 Copiază Ofertă Coș
                  </button>
                </div>

                <div className="boost-proposal-item">
                  <div className="proposal-title">💎 Pachet (Bundle)</div>
                  <div className="proposal-text">
                    {boostData.bundle && boostData.bundle.title ? (
                      <>
                        <strong>{String(boostData.bundle.title)}</strong>
                        {isNum(boostData.bundle.discount_pct) ? ` cu ${boostData.bundle.discount_pct}% reducere (de configurat în Shopify)` : ''}
                      </>
                    ) : DASH}
                  </div>
                  <button
                    className="copy-btn-micro"
                    disabled={!(boostData.bundle && boostData.bundle.promo_code)}
                    onClick={() => handleCopy((boostData.bundle && boostData.bundle.promo_code) || '', 'Codul propus a fost copiat!')}
                  >
                    📋 Copiază Cod Propus
                  </button>
                </div>
              </div>
              )}
            </div>

            <div className="actions-grid">
              {[
                { type: 'tiktok', icon: '🎬', title: t.action_tiktok_title, desc: t.action_tiktok_desc },
                { type: 'email_cart', icon: '📧', title: t.action_email_title, desc: t.action_email_desc },
                { type: 'seo_audit', icon: '🔍', title: t.action_seo_title, desc: t.action_seo_desc },
                { type: 'vip_reward', icon: '👑', title: t.action_vip_title, desc: t.action_vip_desc },
                { type: 'post_purchase', icon: '📦', title: t.action_post_title, desc: t.action_post_desc }
              ].map((card) => (
                <div
                  key={card.type}
                  className={`action-card ${generatingAction && generatingAction !== card.type ? 'is-disabled' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-disabled={!!generatingAction}
                  onClick={() => runQuickAction(card.type)}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && runQuickAction(card.type)}
                >
                  <div className="action-icon">{card.icon}</div>
                  <div className="action-title">{card.title}</div>
                  <div className="action-desc">{card.desc}</div>
                  <div className="action-btn">{generatingAction === card.type ? t.action_generating : t.action_trigger}</div>
                </div>
              ))}
            </div>

            {/* Generated Output Modal */}
            {generatedOutput && (
              <div className="output-modal-overlay">
                <div className="output-modal">
                  <div className="output-modal-header">
                    <span>CIORNĂ GENERATĂ DE AI: {generatedOutput.title}</span>
                    <button className="close-btn" onClick={() => setGeneratedOutput(null)}>✕</button>
                  </div>
                  <pre className="output-content">{generatedOutput.content}</pre>
                  <div className="output-modal-footer">
                    <button className="copy-btn" onClick={() => handleCopy(generatedOutput.content, 'Conținutul a fost copiat!')}>
                      📋 Copiază în Clipboard
                    </button>
                    <button className="close-action-btn" onClick={() => setGeneratedOutput(null)}>Închide</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════ TAB 4: CHAT WITH JARVIS (SALES BEAST) ════ */}
        {activeTab === 'chat' && (
          <div className="chat-container">
            <div className="chat-stream">
              {chatMessages.length === 0 ? (
                <div className="chat-welcome">
                  <div className="reactor-mini pulse-slow"><div className="core-dot"></div></div>
                  <h3>{t.chat_welcome_title}</h3>
                  <p>{t.chat_welcome_desc}</p>
                  <div className="prompt-chips">
                    <button onClick={() => handleSendMessage(t.chip_diagnosis)}>
                      {t.chip_diagnosis}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_boost)}>
                      {t.chip_boost}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_browser)}>
                      {t.chip_browser}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_goal)}>
                      {t.chip_goal}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_aov)}>
                      {t.chip_aov}
                    </button>
                  </div>
                </div>
              ) : (
                chatMessages.map((msg, i) => (
                  <div key={i} className={`chat-bubble ${msg.role}`}>
                    <div className="bubble-header-flex">
                      <span className="bubble-header-name">{msg.role === 'user' ? (lang === 'ro' ? 'TU' : 'YOU') : '🧠 JARVIS'}</span>
                      {msg.role !== 'user' && (
                        <button 
                          className="copy-btn-bubble" 
                          onClick={() => handleCopy(msg.content, 'Răspunsul a fost copiat!')}
                          title="Copiază răspunsul"
                        >
                          📋
                        </button>
                      )}
                    </div>
                    <div className="bubble-body" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                  </div>
                ))
              )}
              {sendingChat && (
                <div className="chat-bubble assistant thinking">
                  <div className="bubble-header-name">🧠 JARVIS</div>
                  <div className="thinking-dots">
                    <span></span><span></span><span></span>
                    <em>{t.thinking_text}</em>
                  </div>
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            <div className="chat-quick-actions-bar">
              <span className="quick-label">Comenzi rapide:</span>
              <button className="chip-tag" disabled={sendingChat} onClick={() => handleSendMessage('/boost')}>⚡ /boost</button>
              <button className="chip-tag" disabled={sendingChat} onClick={() => handleSendMessage('/browser')}>🌐 /browser</button>
              <button className="chip-tag" disabled={sendingChat} onClick={() => handleSendMessage('/goal')}>🎯 /goal</button>
              <button className="chip-tag" disabled={sendingChat} onClick={() => handleSendMessage(t.chip_diagnosis)}>💡 Diagnostic Vânzări</button>
            </div>

            <div className="chat-input-bar">
              <input
                type="text"
                placeholder={plan === 'free' ? t.chat_placeholder_free : t.chat_placeholder_pro}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              />
              <button className="send-btn" onClick={() => handleSendMessage()} disabled={sendingChat}>
                {t.chat_send}
              </button>
            </div>
          </div>
        )}

        {/* ════ TAB 5: AUTOPILOT & NOTIFICATIONS ════ */}
        {activeTab === 'autopilot' && (
          <div className="autopilot-view">
            <div className="autopilot-hero">
              <div className="autopilot-status-badge" style={{ color: autopilotBadge.color, borderColor: autopilotBadge.color, background: 'rgba(255,255,255,0.04)' }}>
                <span className="pulse-green-dot" style={{ background: autopilotBadge.color, boxShadow: `0 0 8px ${autopilotBadge.color}` }}></span>
                {autopilotBadge.text}
              </div>
              {typeof daemon.last_error === 'string' && daemon.last_error && (
                <div className="delivery-alert error" style={{ marginBottom: '12px' }}>
                  ⚠️ {lang === 'ro' ? 'Ultima eroare a pilotului automat:' : 'Last autopilot error:'} {daemon.last_error}
                </div>
              )}
              <h2>{t.autopilot_title}</h2>
              <p>{t.autopilot_sub}</p>

              <div className="autopilot-daemon-banner">
                <div className="daemon-banner-left">
                  <span className="daemon-pulsar"></span>
                  <div>
                    <strong>PILOT AUTOMAT (EMAIL + WHATSAPP):</strong>{' '}
                    <span>
                      Jarvis verifică coșurile abandonate la fiecare {intervalMin} minute și trimite mesaje doar clienților cu acord de marketing pe acel canal (acord necunoscut = nu se trimite), respectând orele de liniște și limitele de frecvență.
                      {isNum(daemon.last_recovered_count) ? ` Ultimul ciclu: ${daemon.last_recovered_count} mesaje.` : ''}
                      {isNum(daemon.total_auto_recovered) ? ` Total de la pornire: ${daemon.total_auto_recovered}.` : ''}
                    </span>
                  </div>
                </div>
                <div className="daemon-banner-right">
                  <span className="daemon-badge">💬 WhatsApp + Email (doar cu acord)</span>
                  {quietLabel && <span className="daemon-badge">🌙 Liniște: {quietLabel}</span>}
                  {frequencySummary && <span className="daemon-badge" title={frequencyRows.map(([k, v]) => `${humanizeKey(k)}: ${humanizeValue(v)}`).join('\n')}>🛡️ {frequencySummary}</span>}
                </div>
              </div>

              <div className="autopilot-stats-row">
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_pending}</div>
                  <div className="stat-value critical">{fmtNum(autopilotData?.pending_carts_count)}</div>
                  <div className="stat-hint">🛒 Checkout-uri nefinalizate</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_revenue}</div>
                  <div className="stat-value highlight-gold">
                    {fmtNum(autopilotData?.potential_revenue, 2)} {isNum(autopilotData?.potential_revenue) && <span className="currency">{(autopilotQueue[0] && autopilotQueue[0].currency) || currency}</span>}
                  </div>
                  <div className="stat-hint">💰 Valoare totală, nu venit încasat</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_actions}</div>
                  <div className="stat-value highlight-gold">{autopilotData ? autopilotLogs.length : DASH}</div>
                  <div className="stat-hint">📜 Ultimele înregistrări din jurnal</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">LIMBI DETECTATE ÎN COADĂ</div>
                  <div className="stat-value highlight-gold">{queueLangs.length ? queueLangs.join(' ') : DASH}</div>
                  <div className="stat-hint">🌐 {queueLangs.length ? 'Din coșurile aflate acum în coadă' : 'Coada este goală'}</div>
                </div>
              </div>

              <div className="autopilot-action-box">
                <button
                  className="autopilot-dispatch-btn"
                  onClick={requestDispatch}
                  disabled={dispatchingAutopilot || !autopilotData}
                >
                  {dispatchingAutopilot ? (
                    <span className="btn-loading-flex">
                      <span className="spinner-mini"></span>
                      {t.autopilot_dispatching}
                    </span>
                  ) : (
                    <span>{t.autopilot_btn_dispatch}</span>
                  )}
                </button>
              </div>

              {dispatchResult && (
                <div className={`delivery-alert ${dispatchResult.type === 'error' ? 'error' : 'success'}`} style={{ marginTop: '14px', textAlign: 'left' }}>
                  {dispatchResult.type === 'error' ? (
                    dispatchResult.text
                  ) : (
                    <>
                      <strong>
                        {dispatchResult.count > 0
                          ? `✅ Ciclu rulat: ${dispatchResult.count} mesaje trimise.`
                          : 'ℹ️ Ciclu rulat: niciun mesaj trimis.'}
                      </strong>
                      {dispatchResult.skipped.length > 0 ? (
                        <>
                          <div style={{ marginTop: '6px' }}>Omise ({dispatchResult.skipped.length}):</div>
                          <ul className="plain-list">
                            {dispatchResult.skipped.slice(0, 30).map((sk, i) => (
                              <li key={i}>• {(sk && (sk.target || sk.email || sk.name)) || DASH} — {reasonText(sk && sk.reason)}</li>
                            ))}
                          </ul>
                        </>
                      ) : (
                        dispatchResult.count === 0 && <div style={{ marginTop: '6px' }}>Nu au existat coșuri eligibile în acest ciclu.</div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Confirm dialog for running the cycle (in-app: native dialogs can be blocked inside the Shopify Admin iframe) */}
            {confirmDispatchOpen && (
              <div className="output-modal-overlay" onClick={() => setConfirmDispatchOpen(false)}>
                <div className="output-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
                  <div className="output-modal-header">
                    <span>{lang === 'ro' ? 'Rulezi ciclul pilotului automat acum?' : 'Run the autopilot cycle now?'}</span>
                    <button className="close-btn" onClick={() => setConfirmDispatchOpen(false)}>✕</button>
                  </div>
                  <div className="output-content">
                    {lang === 'ro'
                      ? 'Se rulează imediat un ciclu normal, cu toate regulile: mesaje doar către clienții cu acord de marketing, fără dezabonați, cu respectarea orelor de liniște, a limitelor de frecvență și a etapelor (30 min / 4 h / 24 h). Mesajele trimise nu pot fi anulate.'
                      : 'One normal cycle runs immediately with all rules: messages only to customers with marketing consent, never to opted-out customers, respecting quiet hours, frequency limits and stage timing (30 min / 4 h / 24 h). Sent messages cannot be undone.'}
                  </div>
                  <div className="output-modal-footer">
                    <button className="close-action-btn" onClick={() => setConfirmDispatchOpen(false)}>{lang === 'ro' ? 'Anulează' : 'Cancel'}</button>
                    <button className="copy-btn" onClick={handleDispatchAutopilot}>{lang === 'ro' ? 'Da, rulează ciclul' : 'Yes, run the cycle'}</button>
                  </div>
                </div>
              </div>
            )}

            {/* Split Grid: Queue & Execution Log */}
            <div className="autopilot-split-grid">
              {/* Active Queue */}
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.autopilot_queue_title}</span>
                  <span className="tag-live">{autopilotQueue.length} în coadă</span>
                </div>
                <div className="queue-list">
                  {autopilotQueue.length > 0 ? (
                    autopilotQueue.map((item, idx) => {
                      const stage = isNum(item.stage) ? item.stage : null
                      const stageText = stage === null
                        ? 'Etapă necunoscută'
                        : stage <= 0
                          ? 'Niciun mesaj trimis încă'
                          : stage >= 3
                            ? 'Etapa 3 din 3 trimisă (ultima)'
                            : `Etapa ${stage} din 3 trimisă`
                      const langName = item.detected_lang_name || item.detected_lang
                      const priceNum = item.total_price === null || item.total_price === undefined || item.total_price === '' ? NaN : Number(item.total_price)
                      return (
                        <div key={item.id || idx} className="queue-item">
                          <div className="queue-item-header">
                            <div className="queue-name-group">
                              {item.detected_flag && <span className="queue-flag">{item.detected_flag}</span>}
                              <span className="queue-name">{item.customer_name || item.email || DASH}</span>
                              {(item.detected_country || langName) && (
                                <span className="queue-country-tag">{[item.detected_country, langName].filter(Boolean).join(' • ')}</span>
                              )}
                            </div>
                            <span className="queue-price">{Number.isFinite(priceNum) ? `${priceNum.toFixed(2)} ${item.currency || currency}` : DASH}</span>
                          </div>
                          <div className="queue-details">
                            📦 {asArray(item.items).length ? asArray(item.items).map((x) => (typeof x === 'string' ? x : (x && (x.title || x.name)) || '')).filter(Boolean).join(', ') : DASH}
                          </div>
                          <div className="queue-footer">
                            <div className="queue-tags-row">
                              <span className="fomo-badge">{stageText}</span>
                              {item.drip_status && <span className="queue-lang-note">Stare: <strong>{String(item.drip_status)}</strong></span>}
                              <span className="queue-lang-note">
                                📧 Email: <strong style={{ color: consentColor(item.email_marketing_consent) }}>{consentText(item.email_marketing_consent)}</strong>
                              </span>
                              <span className="queue-lang-note">
                                💬 WhatsApp: <strong style={{ color: consentColor(item.sms_marketing_consent) }}>{consentText(item.sms_marketing_consent)}</strong>
                              </span>
                              {item.created_at && <span className="queue-lang-note">🕒 {fmtDateTime(item.created_at, locale)}</span>}
                            </div>
                            <div className="queue-actions-row">
                              {item.wa_link && item.sms_marketing_consent === true && (
                                <a href={item.wa_link} target="_blank" rel="noreferrer" className="wa-btn-badge">
                                  💬 WhatsApp Direct
                                </a>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })
                  ) : (
                    <div className="empty-notice">
                      {autopilotData ? 'Niciun coș abandonat în coadă acum.' : 'Coada nu este disponibilă acum.'}
                    </div>
                  )}
                </div>
              </div>

              {/* Execution Log */}
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.autopilot_log_title}</span>
                  <button className="copy-btn-inline" onClick={() => { loadAutopilotStatus() }}>🔄 Reîmprospătează</button>
                </div>
                <div className="audit-logs-list">
                  {autopilotLogs && autopilotLogs.length > 0 ? (
                    autopilotLogs.filter((l) => l && typeof l === 'object').map((log, idx) => {
                      const st = logStatusUi(log.status)
                      const rev = Number(log.revenue)
                      return (
                        <div key={log.id || idx} className="log-item">
                          <div className="log-badge-type">{log.action_type || DASH}</div>
                          <div className="log-details">
                            <div className="log-title">
                              Către: <strong>{log.target_name || log.target_email || DASH}</strong>{log.country ? ` (${log.country})` : ''}
                              {' '}<span style={{ color: st.color, fontSize: '11px', fontWeight: 700 }}>• {st.text}</span>
                            </div>
                            <div className="log-sub">{log.subject || (typeof log.message === 'string' ? log.message.slice(0, 80) : '')}</div>
                          </div>
                          <div className="log-meta">
                            {Number.isFinite(rev) && rev > 0 && <div className="log-rev">Coș: {rev.toFixed(2)} {currency}</div>}
                            <div className="log-date">{fmtDateTime(log.created_at, locale)}</div>
                          </div>
                        </div>
                      )
                    })
                  ) : (
                    <div className="empty-notice">Nicio înregistrare încă. Jurnalul afișează doar acțiunile reale ale pilotului automat.</div>
                  )}
                </div>
              </div>
            </div>

            {/* Email Gateway & Delivery Settings */}
            <div className="hud-card" style={{ marginTop: '20px' }}>
              <div className="card-title">
                <span>📧 Gateway Expediere Email & Notificări</span>
              </div>
              <div className="settings-form-grid">
                <div className="form-group">
                  <label>Furnizor Email:</label>
                  <select 
                    value={deliverySettings.email_provider} 
                    onChange={(e) => setDeliverySettings({ ...deliverySettings, email_provider: e.target.value })}
                  >
                    <option value="resend">Resend API (Recomandat)</option>
                    <option value="smtp">Custom SMTP (Gmail / Yahoo / Host)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Email Expeditor:</label>
                  <input 
                    type="text" 
                    value={deliverySettings.sender_email} 
                    onChange={(e) => setDeliverySettings({ ...deliverySettings, sender_email: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Nume Expeditor:</label>
                  <input 
                    type="text" 
                    value={deliverySettings.sender_name} 
                    onChange={(e) => setDeliverySettings({ ...deliverySettings, sender_name: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Email Notificare Comerciant:</label>
                  <input 
                    type="text" 
                    value={deliverySettings.merchant_notify_email} 
                    onChange={(e) => setDeliverySettings({ ...deliverySettings, merchant_notify_email: e.target.value })}
                  />
                </div>
              </div>
              <div className="form-actions-row">
                <button className="save-btn" onClick={handleSaveDeliverySettings} disabled={savingDelivery}>
                  {savingDelivery ? 'Se salvează...' : 'Salvează Setările Email'}
                </button>
                <button className="test-btn" onClick={handleSendTestEmail} disabled={sendingTestEmail}>
                  {sendingTestEmail ? 'Se expediază...' : 'Trimite Email de Test'}
                </button>
              </div>
              {deliveryFeedback && (
                <div className={`delivery-alert ${deliveryFeedback.type}`}>
                  {deliveryFeedback.text}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ════ TAB 6: SUBSCRIPTION PLANS ════ */}
        {activeTab === 'plans' && (
          <div className="pricing-container">
            <div className="pricing-title">
              <h2>{t.pricing_title}</h2>
              <p>{t.pricing_sub}</p>
              <p style={{ marginTop: '8px', fontSize: '13px' }}>
                {lang === 'ro' ? 'Plan curent: ' : 'Current plan: '}<strong>{planLabel}</strong>
              </p>
            </div>

            <div className="pricing-cards">
              <div className={`pricing-card ${plan === 'free' ? 'current' : ''}`}>
                <div className="plan-badge">{t.plan_free_badge}</div>
                <h3>{t.plan_free_title}</h3>
                <div className="price-tag">{t.plan_free_price} <span>{t.plan_free_period}</span></div>
                <p className="plan-desc">{t.plan_free_desc}</p>
                <ul className="plan-perks">
                  <li>{t.plan_free_perk1}</li>
                  <li>{t.plan_free_perk2}</li>
                  <li>{t.plan_free_perk3}</li>
                  <li className="dim">{t.plan_free_dim1}</li>
                  <li className="dim">{t.plan_free_dim2}</li>
                  <li className="dim">{t.plan_free_dim3}</li>
                </ul>
                <button
                  className="plan-btn secondary"
                  disabled
                  title={plan === 'free' ? undefined : t.plan_free_btn_switch}
                >
                  {plan === 'free' ? t.plan_free_btn_active : t.plan_free_btn_switch}
                </button>
              </div>

              <div className={`pricing-card pro ${plan === 'pro' ? 'current' : ''}`}>
                <div className="plan-badge hot">{t.plan_pro_badge}</div>
                <h3>{t.plan_pro_title}</h3>
                <div className="price-tag">{t.plan_pro_price} <span>{t.plan_pro_period}</span></div>
                <p className="plan-desc">{t.plan_pro_desc}</p>
                <ul className="plan-perks">
                  <li><strong>{t.plan_pro_perk1}</strong></li>
                  <li><strong>{t.plan_pro_perk2}</strong></li>
                  <li><strong>{t.plan_pro_perk3}</strong></li>
                  <li><strong>{t.plan_pro_perk4}</strong></li>
                  <li><strong>{t.plan_pro_perk5}</strong></li>
                  <li><strong>{t.plan_pro_perk6}</strong></li>
                </ul>
                <button
                  className="plan-btn primary"
                  disabled={subscribing || isPro}
                  onClick={handleOfficialShopifySubscribe}
                >
                  {subscribing ? 'CONECTARE CU SHOPIFY...' : (isPro ? t.plan_pro_btn_active : t.plan_pro_btn)}
                </button>
                {billingFeedback && (
                  <div className={`delivery-alert ${billingFeedback.type}`}>
                    {billingFeedback.text}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

      </main>
    </div>
  )
}

// ── WARM LUXURY EXECUTIVE STYLES ──
const styles = `
/* Google Fonts are loaded once, in index.html */

:root {
  --bg-deep: #0e121a;
  --bg-card: rgba(22, 28, 42, 0.92);
  --bg-card-sub: #1a2234;
  --border-warm: rgba(245, 158, 11, 0.22);
  --border-sub: rgba(255, 255, 255, 0.08);
  --amber-gold: #f59e0b;
  --gold-deep: #d97706;
  --gold-glow: rgba(245, 158, 11, 0.25);
  --bronze: #e06c55;
  --terracotta: #ea580c;
  --cream: #faf8f5;
  --text-main: #f8fafc;
  --text-dim: #94a3b8;
  --text-warm: #e2d9cd;
  --green-warm: #10b981;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

.jarvis-root {
  background: var(--bg-deep);
  color: var(--text-main);
  min-height: 100vh;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  letter-spacing: 0.2px;
  background-image: 
    radial-gradient(circle at 10% 20%, rgba(245, 158, 11, 0.05) 0%, transparent 45%),
    radial-gradient(circle at 90% 80%, rgba(224, 108, 85, 0.04) 0%, transparent 45%),
    linear-gradient(rgba(255, 255, 255, 0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.015) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 36px 36px, 36px 36px;
  padding: 24px 32px;
}

.floating-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: linear-gradient(135deg, #d97706, #f59e0b);
  color: #0e121a;
  font-weight: 700;
  font-size: 14px;
  padding: 12px 20px;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(245, 158, 11, 0.35);
  z-index: 9999;
  animation: slide-up 0.3s ease-out;
}

@keyframes slide-up {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.hud-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 28px;
  background: var(--bg-card);
  backdrop-filter: blur(14px);
  border: 1px solid var(--border-warm);
  border-radius: 16px;
  margin-bottom: 20px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.45);
}

.hud-brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-title {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-badge {
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 10px;
  padding: 3px 10px;
  border-radius: 20px;
  background: rgba(245, 158, 11, 0.15);
  color: var(--amber-gold);
  border: 1px solid var(--amber-gold);
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-status {
  font-size: 13px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.live-indicator {
  width: 8px;
  height: 8px;
  background: var(--green-warm);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--green-warm);
}

.hud-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.lang-switcher {
  display: flex;
  background: rgba(14, 18, 26, 0.85);
  border: 1px solid var(--border-warm);
  border-radius: 10px;
  overflow: hidden;
}

.lang-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.lang-btn.active {
  background: rgba(245, 158, 11, 0.2);
  color: #fff;
}

.hud-btn {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid var(--amber-gold);
  color: var(--amber-gold);
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.hud-btn.active {
  background: rgba(245, 158, 11, 0.25);
  box-shadow: 0 0 12px var(--gold-glow);
}

.upgrade-glow-btn {
  background: linear-gradient(135deg, #d97706, #f59e0b);
  border: none;
  color: #0e121a;
  padding: 9px 18px;
  border-radius: 10px;
  font-weight: 800;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 4px 18px var(--gold-glow);
  transition: all 0.2s;
}

.pro-active-badge {
  font-size: 11px;
  font-weight: 800;
  color: var(--amber-gold);
  padding: 7px 14px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid var(--amber-gold);
  letter-spacing: 0.5px;
}

.hud-nav {
  display: flex;
  gap: 10px;
  margin-bottom: 24px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.nav-item {
  background: rgba(22, 28, 42, 0.7);
  border: 1px solid var(--border-sub);
  color: var(--text-dim);
  padding: 12px 20px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: all 0.2s;
  white-space: nowrap;
}

.nav-item:hover {
  background: rgba(30, 40, 58, 0.85);
  color: var(--text-main);
  border-color: rgba(245, 158, 11, 0.3);
}

.nav-item.active {
  background: rgba(245, 158, 11, 0.15);
  border-color: var(--amber-gold);
  color: var(--amber-gold);
  box-shadow: 0 4px 16px var(--gold-glow);
}

.nav-pill {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 12px;
  background: var(--amber-gold);
  color: #0e121a;
  font-weight: 800;
}

.hud-body {
  width: 100%;
}

.hud-card {
  background: var(--bg-card);
  backdrop-filter: blur(14px);
  border: 1px solid var(--border-warm);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 20px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.35);
}

.hero-card {
  border-left: 4px solid var(--amber-gold);
}

.hero-flex {
  display: flex;
  align-items: center;
  gap: 32px;
}

.reactor-large-box {
  flex-shrink: 0;
}

.reactor-core {
  width: 120px;
  height: 120px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(245, 158, 11, 0.18) 0%, transparent 70%);
}

.core-glow {
  text-align: center;
  z-index: 2;
}

.health-number {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 32px;
  font-weight: 700;
  color: var(--amber-gold);
  line-height: 1;
}

.health-label {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--text-dim);
  margin-top: 4px;
}

.hero-info {
  flex: 1;
}

.greeting-line {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}

.summary-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-warm);
  margin-bottom: 16px;
}

.hero-buttons {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.speak-btn {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid var(--amber-gold);
  color: var(--amber-gold);
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.speak-btn:hover {
  background: rgba(245, 158, 11, 0.25);
}

.instant-diag-btn {
  background: linear-gradient(135deg, #ea580c, #d97706);
  border: none;
  color: #fff;
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(234, 88, 12, 0.35);
  transition: all 0.2s;
}

.instant-diag-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(234, 88, 12, 0.45);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-sub);
  border-radius: 14px;
  padding: 20px;
  transition: all 0.2s;
}

.metric-card:hover {
  border-color: rgba(245, 158, 11, 0.3);
  transform: translateY(-2px);
}

.metric-card.alert-border {
  border-color: rgba(234, 88, 12, 0.4);
}

.metric-header {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--text-dim);
  margin-bottom: 10px;
}

.metric-value {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}

.metric-value.critical {
  color: #f87171;
}

.metric-value.highlight-green {
  color: var(--green-warm);
}

.metric-value.highlight-gold {
  color: var(--amber-gold);
}

.metric-footer {
  font-size: 12px;
  color: var(--text-dim);
}

.highlight-green { color: var(--green-warm); font-weight: 600; }
.highlight-orange { color: #fb923c; font-weight: 600; }
.highlight-gold { color: var(--amber-gold); font-weight: 600; }

.two-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 900px) {
  .two-columns { grid-template-columns: 1fr; }
  .hero-flex { flex-direction: column; align-items: flex-start; }
}

.card-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-sub);
}

.card-desc {
  font-size: 13px;
  color: var(--text-warm);
  margin-bottom: 16px;
  line-height: 1.5;
}

.tag-live {
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 12px;
  background: rgba(245, 158, 11, 0.15);
  color: var(--amber-gold);
  border: 1px solid var(--amber-gold);
  font-weight: 700;
}

.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.task-item:hover {
  border-color: rgba(245, 158, 11, 0.3);
}

.task-item.done {
  opacity: 0.6;
  text-decoration: line-through;
}

.task-title {
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 4px;
}

.task-why {
  font-size: 12px;
  color: var(--text-warm);
  line-height: 1.4;
}

.traffic-box {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid var(--border-warm);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}

.traffic-tag {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--amber-gold);
  margin-bottom: 6px;
}

.traffic-desc {
  font-size: 13px;
  color: var(--text-main);
  line-height: 1.5;
}

.alerts-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.box-subtitle {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.alert-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  background: rgba(234, 88, 12, 0.08);
  border: 1px solid rgba(234, 88, 12, 0.25);
  border-radius: 10px;
  font-size: 13px;
}

.alert-item.green {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.25);
}

.alert-action {
  font-size: 12px;
  color: var(--text-warm);
  margin-top: 4px;
}

/* Radar & Growth Tab */
.subnav-pills {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.subnav-pill {
  background: var(--bg-card);
  border: 1px solid var(--border-sub);
  color: var(--text-dim);
  padding: 10px 18px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.subnav-pill.active {
  background: rgba(245, 158, 11, 0.18);
  border-color: var(--amber-gold);
  color: var(--amber-gold);
}

.radar-content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 1000px) {
  .radar-content-grid { grid-template-columns: 1fr; }
}

.custom-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.custom-table th {
  text-align: left;
  padding: 10px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border-sub);
  font-weight: 700;
  font-size: 11px;
}

.custom-table td {
  padding: 12px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.badge-intent {
  padding: 3px 8px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(245, 158, 11, 0.15);
  color: var(--amber-gold);
}

.code-block {
  background: #090c12;
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 16px;
  font-family: monospace;
  font-size: 12px;
  max-height: 240px;
  overflow-y: auto;
  color: #fbbf24;
  margin-bottom: 16px;
}

.tips-box ul {
  list-style: none;
  font-size: 13px;
  color: var(--text-warm);
  line-height: 1.6;
}

.copy-btn-inline {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid var(--amber-gold);
  color: var(--amber-gold);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.copy-btn-inline:hover {
  background: rgba(245, 158, 11, 0.3);
}

.live-google-card {
  grid-column: 1 / -1;
  background: linear-gradient(135deg, rgba(22, 28, 42, 0.95), rgba(30, 38, 58, 0.95));
  border: 1px solid var(--border-warm);
}

.live-search-bar {
  display: flex;
  gap: 12px;
  margin-top: 14px;
}

.live-search-input {
  flex: 1;
  background: #090c12;
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.live-search-input:focus {
  border-color: var(--amber-gold);
}

.live-results-box {
  margin-top: 18px;
  padding: 16px;
  background: var(--bg-card-sub);
  border: 1px solid var(--border-warm);
  border-radius: 12px;
}

.live-results-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--amber-gold);
  margin-bottom: 12px;
  letter-spacing: 0.5px;
}

.live-tags-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.live-tag-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.25);
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
  color: var(--cream);
}

.chat-btn-micro {
  background: var(--amber-gold);
  border: none;
  color: #0e121a;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.chat-btn-micro:hover {
  background: #fbbf24;
  transform: translateY(-1px);
}

.hooks-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hook-card {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 16px;
}

.hook-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.hook-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--amber-gold);
}

.hook-duration {
  font-size: 11px;
  color: var(--text-dim);
}

.hook-script {
  font-size: 13px;
  line-height: 1.5;
  color: #fff;
  margin-bottom: 12px;
}

.hook-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--text-dim);
}

.copy-btn-micro {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}

.copy-btn-micro:hover {
  border-color: var(--amber-gold);
  color: var(--amber-gold);
}

.dm-script-box {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-warm);
  border-radius: 12px;
  padding: 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-warm);
  margin-bottom: 20px;
}

.personas-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.persona-item {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-sub);
  border-radius: 10px;
  padding: 12px;
  font-size: 13px;
}

.persona-desc {
  color: var(--text-warm);
  margin: 4px 0;
}

.persona-trigger {
  color: var(--amber-gold);
  font-weight: 600;
}

/* Goal Simulator */
.goal-input-box {
  margin-bottom: 20px;
}

.goal-input-box label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 8px;
}

.input-group {
  display: flex;
  gap: 12px;
}

.input-group input {
  flex: 1;
  background: #090c12;
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 700;
}

.calculate-btn {
  background: linear-gradient(135deg, #d97706, #f59e0b);
  border: none;
  color: #0e121a;
  padding: 12px 24px;
  border-radius: 10px;
  font-weight: 800;
  cursor: pointer;
}

.goal-results-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.goal-stat-item {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}

.stat-val {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 28px;
  font-weight: 700;
  margin: 6px 0;
}

.stat-sub {
  font-size: 11px;
  color: var(--text-dim);
}

.channel-bars {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 12px;
}

.channel-header {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}

.progress-bg {
  width: 100%;
  height: 8px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #d97706, #f59e0b);
  border-radius: 4px;
}

/* Boost Banner */
.boost-banner-card {
  border-left: 4px solid var(--amber-gold);
}

.boost-proposals-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-top: 16px;
}

@media (max-width: 900px) {
  .boost-proposals-grid { grid-template-columns: 1fr; }
}

.boost-proposal-item {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.proposal-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--amber-gold);
  margin-bottom: 8px;
}

.proposal-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-warm);
  margin-bottom: 14px;
}

/* Actions Grid */
.actions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
}

.action-card {
  background: var(--bg-card);
  border: 1px solid var(--border-sub);
  border-radius: 16px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.25s;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.action-card:hover {
  border-color: var(--amber-gold);
  transform: translateY(-3px);
  box-shadow: 0 8px 24px var(--gold-glow);
}

.action-icon {
  font-size: 28px;
  margin-bottom: 12px;
}

.action-title {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}

.action-desc {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-dim);
  margin-bottom: 20px;
  flex-grow: 1;
}

.action-btn {
  font-size: 12px;
  font-weight: 800;
  color: var(--amber-gold);
  letter-spacing: 0.5px;
}

/* Chat Styling */
.chat-container {
  background: var(--bg-card);
  border: 1px solid var(--border-warm);
  border-radius: 16px;
  height: 640px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-stream {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-welcome {
  text-align: center;
  margin: auto;
  max-width: 540px;
}

.chat-welcome h3 {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 22px;
  color: #fff;
  margin: 16px 0 8px;
}

.chat-welcome p {
  font-size: 14px;
  color: var(--text-dim);
  margin-bottom: 20px;
}

.prompt-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prompt-chips button {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  color: var(--text-warm);
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}

.prompt-chips button:hover {
  border-color: var(--amber-gold);
  color: #fff;
  background: rgba(245, 158, 11, 0.12);
}

.chat-bubble {
  max-width: 85%;
  padding: 16px 20px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.6;
}

.chat-bubble.user {
  align-self: flex-end;
  background: linear-gradient(135deg, #1e2638, #2a344d);
  color: #fff;
  border: 1px solid var(--border-sub);
  border-bottom-right-radius: 4px;
}

.chat-bubble.assistant {
  align-self: flex-start;
  background: var(--bg-card-sub);
  color: #f1f5f9;
  border: 1px solid var(--border-warm);
  border-bottom-left-radius: 4px;
}

.bubble-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.bubble-header-name {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.5px;
  color: var(--amber-gold);
}

.copy-btn-bubble {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
}

.copy-btn-bubble:hover {
  color: #fff;
}

.chat-quick-actions-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(14, 18, 26, 0.6);
  border-top: 1px solid var(--border-sub);
  overflow-x: auto;
}

.quick-label {
  font-size: 11px;
  color: var(--text-dim);
  font-weight: 700;
  white-space: nowrap;
}

.chip-tag {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-sub);
  color: var(--text-warm);
  padding: 4px 10px;
  border-radius: 14px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.chip-tag:hover {
  border-color: var(--amber-gold);
  color: var(--amber-gold);
}

.chat-input-bar {
  display: flex;
  padding: 16px;
  background: #090c12;
  border-top: 1px solid var(--border-sub);
  gap: 12px;
}

.chat-input-bar input {
  flex: 1;
  background: #141b28;
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 12px 18px;
  border-radius: 12px;
  font-size: 14px;
}

.chat-input-bar input:focus {
  outline: none;
  border-color: var(--amber-gold);
}

.send-btn {
  background: linear-gradient(135deg, #d97706, #f59e0b);
  border: none;
  color: #0e121a;
  padding: 12px 24px;
  border-radius: 12px;
  font-weight: 800;
  cursor: pointer;
}

/* Autopilot */
.autopilot-view {
  width: 100%;
}

.autopilot-hero {
  background: var(--bg-card);
  border: 1px solid var(--border-warm);
  border-radius: 16px;
  padding: 28px;
  margin-bottom: 24px;
}

.autopilot-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid var(--green-warm);
  border-radius: 20px;
  font-size: 11px;
  font-weight: 800;
  color: var(--green-warm);
  margin-bottom: 12px;
}

.pulse-green-dot {
  width: 6px;
  height: 6px;
  background: var(--green-warm);
  border-radius: 50%;
  box-shadow: 0 0 8px var(--green-warm);
}

.autopilot-hero h2 {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 24px;
  color: #fff;
  margin-bottom: 6px;
}

.autopilot-hero p {
  font-size: 14px;
  color: var(--text-dim);
  margin-bottom: 20px;
}

.autopilot-daemon-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  font-size: 13px;
  margin-bottom: 20px;
}

.daemon-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  background: rgba(245, 158, 11, 0.12);
  color: var(--amber-gold);
  border: 1px solid var(--border-warm);
  border-radius: 8px;
  margin-left: 8px;
}

.autopilot-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

@media (max-width: 900px) {
  .autopilot-stats-row { grid-template-columns: repeat(2, 1fr); }
}

.autopilot-stat-card {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 16px;
}

.stat-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.stat-value {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 4px;
}

.stat-hint {
  font-size: 11px;
  color: var(--text-dim);
}

.autopilot-dispatch-btn {
  width: 100%;
  background: linear-gradient(135deg, #d97706, #f59e0b);
  border: none;
  color: #0e121a;
  padding: 16px;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  letter-spacing: 0.5px;
}

.autopilot-split-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 900px) {
  .autopilot-split-grid { grid-template-columns: 1fr; }
}

.queue-list, .audit-logs-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 480px;
  overflow-y: auto;
}

.queue-item, .log-item {
  background: var(--bg-card-sub);
  border: 1px solid var(--border-sub);
  border-radius: 12px;
  padding: 14px;
}

.queue-item-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.queue-name { font-weight: 700; color: #fff; margin-left: 6px; }
.queue-price { font-weight: 800; color: var(--amber-gold); }
.queue-details { font-size: 12px; color: var(--text-dim); margin-bottom: 8px; }
.queue-footer { display: flex; justify-content: space-between; align-items: center; }
.wa-btn-badge {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 8px;
  background: #25D366;
  color: #fff;
  text-decoration: none;
  font-weight: 700;
}

/* Settings Form */
.settings-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.form-group input, .form-group select {
  width: 100%;
  background: #090c12;
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
}

.form-actions-row {
  display: flex;
  gap: 12px;
}

.save-btn {
  background: var(--amber-gold);
  border: none;
  color: #0e121a;
  padding: 10px 20px;
  border-radius: 10px;
  font-weight: 800;
  cursor: pointer;
}

.test-btn {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 10px 18px;
  border-radius: 10px;
  font-weight: 700;
  cursor: pointer;
}

.delivery-alert {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin-top: 12px;
}

.delivery-alert.success { background: rgba(16, 185, 129, 0.15); border: 1px solid var(--green-warm); color: var(--green-warm); }
.delivery-alert.error { background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #f87171; }

/* Pricing */
.pricing-container {
  max-width: 800px;
  margin: 0 auto;
}

.pricing-title {
  text-align: center;
  margin-bottom: 32px;
}

.pricing-title h2 {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 28px;
  color: #fff;
  margin-bottom: 8px;
}

.pricing-title p {
  color: var(--text-dim);
  font-size: 14px;
}

.pricing-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 700px) {
  .pricing-cards { grid-template-columns: 1fr; }
}

.pricing-card {
  background: var(--bg-card);
  border: 1px solid var(--border-sub);
  border-radius: 16px;
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.pricing-card.pro {
  border-color: var(--amber-gold);
  box-shadow: 0 8px 30px var(--gold-glow);
}

.plan-badge {
  font-size: 10px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-dim);
  display: inline-block;
  margin-bottom: 12px;
}

.plan-badge.hot {
  background: var(--amber-gold);
  color: #0e121a;
}

.pricing-card h3 {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 22px;
  color: #fff;
  margin-bottom: 8px;
}

.price-tag {
  font-size: 32px;
  font-weight: 800;
  color: #fff;
  margin-bottom: 12px;
}

.price-tag span {
  font-size: 13px;
  color: var(--text-dim);
  font-weight: normal;
}

.plan-desc {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 20px;
  line-height: 1.5;
}

.plan-perks {
  list-style: none;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
}

.plan-perks li.dim {
  color: #4b5563;
}

.plan-btn {
  padding: 14px;
  border-radius: 12px;
  font-weight: 800;
  font-size: 13px;
  cursor: pointer;
  border: none;
}

.plan-btn.primary {
  background: linear-gradient(135deg, #d97706, #f59e0b);
  color: #0e121a;
}

.plan-btn.secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-dim);
}

/* Modal */
.output-modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.output-modal {
  background: #141b28;
  border: 1px solid var(--border-warm);
  border-radius: 16px;
  width: 100%;
  max-width: 640px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
}

.output-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px;
  border-bottom: 1px solid var(--border-sub);
  font-weight: 800;
  color: var(--amber-gold);
}

.output-content {
  padding: 24px;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #f1f5f9;
}

.output-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--border-sub);
}

.copy-btn {
  background: var(--amber-gold);
  border: none;
  color: #0e121a;
  padding: 10px 18px;
  border-radius: 10px;
  font-weight: 800;
  cursor: pointer;
}

.close-action-btn {
  background: rgba(255, 255, 255, 0.08);
  border: none;
  color: #fff;
  padding: 10px 18px;
  border-radius: 10px;
  cursor: pointer;
}

/* ── Honesty / status additions ── */
.status-banner {
  padding: 14px 18px;
  border-radius: 12px;
  margin-bottom: 20px;
  font-size: 14px;
  line-height: 1.5;
}
.status-banner.danger { background: rgba(239, 68, 68, 0.12); border: 1px solid #ef4444; color: #fecaca; }
.status-banner.warning { background: rgba(245, 158, 11, 0.12); border: 1px solid var(--amber-gold); color: #fef3c7; }
.status-banner-detail { margin-top: 6px; font-size: 12px; color: #fca5a5; font-family: monospace; word-break: break-word; }

.auth-card { border-left: 4px solid var(--amber-gold); }
.auth-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.auth-input {
  flex: 1;
  min-width: 220px;
  background: #090c12;
  border: 1px solid var(--border-sub);
  color: #fff;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
}

.plain-list { list-style: none; padding: 0; margin: 6px 0; line-height: 1.6; }
.muted-label { color: var(--text-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.seo-proposal-row {
  font-size: 12px;
  color: #e7e5e4;
  padding: 8px 10px;
  margin: 6px 0;
  background: #0c0a09;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dns-missing-row {
  font-size: 12px;
  color: #e7e5e4;
  padding: 8px 10px;
  margin: 6px 0;
  background: #0c0a09;
  border-radius: 6px;
}
.action-card.is-disabled { opacity: 0.5; cursor: not-allowed; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.queue-tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: center;
  font-size: 12px;
  color: var(--text-dim);
  flex: 1;
}
.fomo-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid var(--border-warm);
  color: var(--amber-gold);
}
.queue-lang-note { white-space: nowrap; }
`
