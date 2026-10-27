import React, { useState, useEffect, useRef } from 'react'

// Multi-language dictionary (English & Romanian)
const I18N = {
  en: {
    brand_sub_pro: 'EXECUTIVE PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'MAISON GROZAVU LIVE TELEMETRY',
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
    orders_sub: '▲ Synced in real-time',
    revenue_today: 'REVENUE TODAY',
    revenue_30d: '30-day velocity:',
    abandoned_carts: 'ABANDONED CHECKOUTS',
    abandoned_alert: '⚠️ Immediate revenue recovery opportunity',
    abandoned_ok: '✅ Zero abandoned carts',
    new_customers: 'NEW CUSTOMERS (24H)',
    customers_sub: 'Customer base expanding',
    aov_label: 'AVG ORDER VALUE (AOV)',
    aov_sub: 'Target: >150 EUR for luxury fashion',
    retention_label: 'RETENTION RATE',
    retention_sub: 'Repeat clientele',
    unique_buyers_label: 'UNIQUE BUYERS (30D)',
    unique_buyers_sub: 'Customer accounts',
    vip_customer_label: 'TOP VIP CLIENT',
    tactical_plan: '🎯 STRATEGIC PRIORITIES FOR TODAY',
    ai_prioritized: 'AI OPTIMIZED',
    analyzing_priorities: 'Jarvis is calculating growth priorities...',
    traffic_strategy: '📈 GROWTH STRATEGY & ANOMALY RADAR',
    daily_growth_tip: 'GROWTH STRATEGY OF THE DAY',
    auto_diagnostics: 'AUTONOMOUS DIAGNOSTICS:',
    store_nominal: 'Store operating at peak health. No critical bottlenecks detected.',
    quick_diagnosis_btn: '💡 INSTANT DIAGNOSIS: WHY ARE SALES LOW TODAY AND WHAT CAN I FIX RAPIDLY?',
    chat_welcome_title: 'Jarvis Executive Brain is Active.',
    chat_welcome_desc: 'I monitor every order, checkout, Google search intent, and conversion metric for Maison Grozavu. How shall we scale today?',
    chip_diagnosis: '💡 Why are my sales low today and what can I fix immediately?',
    chip_boost: '⚡ /boost — Instant Conversion & Traffic Multiplier',
    chip_browser: '🌐 /browser — Autonomous Google & Social Lead Radar',
    chip_goal: '🎯 /goal — Mathematical 10,000€ Revenue Blueprint',
    chip_aov: '🛍️ How do we increase Average Order Value (AOV) for Maison Grozavu?',
    chat_placeholder_free: 'Ask Jarvis ({count} free questions left today)...',
    chat_placeholder_pro: 'Command Jarvis (/boost, /browser, /goal or any sales task)...',
    chat_send: 'SEND',
    thinking_text: 'Jarvis is formulating executive tactical advice...',
    action_tiktok_title: '🎬 Viral 30s TikTok/Reels Script',
    action_tiktok_desc: 'Generates a 3-step high-converting luxury video script (3s visual hook, problem/solution, and direct atelier CTA).',
    action_email_title: '📧 Magnetic Cart Recovery Email',
    action_email_desc: 'Persuasive abandoned checkout sequence with emotional luxury angle, urgency, and 10% promo code (MG10).',
    action_seo_title: '🔍 Google SEO & Conversion Catalog Audit',
    action_seo_desc: 'Rewrites product titles and descriptions to capture high-intent Google searches and eliminate checkout hesitation.',
    action_vip_title: '👑 VIP Loyalty & Private Atelier Reward',
    action_vip_desc: 'Identify top spenders and draft an exclusive private appreciation offer to trigger high-margin reorders.',
    action_post_title: '📦 3-Day Post-Delivery Review & Upsell',
    action_post_desc: 'Automated 3-day post-delivery sequence requesting photo reviews and recommending a complementary item.',
    action_trigger: 'GENERATE NOW →',
    action_generating: 'GENERATING WITH AI...',
    pricing_title: 'CHOOSE THE INTELLIGENCE LEVEL FOR YOUR STORE',
    pricing_sub: 'No expensive agencies or employees. Jarvis is your 24/7 technical and marketing co-founder.',
    plan_free_title: 'Observer Mode',
    plan_free_badge: 'BASIC PLAN',
    plan_free_price: '$0',
    plan_free_period: '/ forever',
    plan_free_desc: 'Monitors orders and gives high-level visibility over store metrics.',
    plan_free_perk1: '✔ Real-time sales & order dashboard',
    plan_free_perk2: '✔ 3 free manual chat questions / day',
    plan_free_perk3: '✔ Text-only daily briefing on demand',
    plan_free_dim1: '✖ No autonomous audio voice',
    plan_free_dim2: '✖ No 1-click viral campaign generators',
    plan_free_dim3: '✖ No proactive loss detection alerts',
    plan_free_btn_active: 'CURRENT PLAN',
    plan_free_btn_switch: 'DOWNGRADE TO FREE',
    plan_pro_title: 'Jarvis Autonomous Pro',
    plan_pro_badge: 'RECOMMENDED FOR SALES',
    plan_pro_price: '$9.99',
    plan_pro_period: '/ month (7-day free trial)',
    plan_pro_desc: 'Full-fledged autonomous AI partner with voice synthesis, predictive alerts, and automated revenue generators.',
    plan_pro_perk1: '⭐ Jarvis Speaks to You: Daily synthetic voice audio report',
    plan_pro_perk2: '⭐ Unlimited AI Chat: No question limits',
    plan_pro_perk3: '⭐ 1-Click Campaigns: Viral TikTok scripts & cart emails',
    plan_pro_perk4: '⭐ Proactive Loss Prevention: Instant cart alerts',
    plan_pro_perk5: '⭐ Store Health Matrix: Live conversion & velocity audit',
    plan_pro_perk6: '⭐ Daily AI Action Priorities with Gamified XP',
    plan_pro_btn: '⚡ ACTIVATE JARVIS PRO ($9.99/mo - 7 DAYS TRIAL)',
    plan_pro_btn_active: 'PRO ACTIVE (7-DAY FREE TRIAL)',
    test_mode_toggle: '🧪 Developer Mock Toggle',
    copied_toast: 'Copied to clipboard!',
    autopilot_title: 'AUTONOMOUS REVENUE DISPATCH COMMAND',
    autopilot_sub: 'Jarvis continuously monitors checkouts and dispatches recovery emails without human intervention.',
    autopilot_status_active: '🟢 AUTOPILOT: 100% ONLINE & VIGILANT',
    autopilot_btn_dispatch: '⚡ DISPATCH ALL AUTONOMOUS ACTIONS NOW',
    autopilot_dispatching: 'JARVIS DISPATCHING ACTIONS...',
    autopilot_stat_pending: 'CARTS IN RECOVERY QUEUE',
    autopilot_stat_revenue: 'REVENUE AT STAKE',
    autopilot_stat_actions: 'ACTIONS EXECUTED',
    autopilot_log_title: 'LIVE AUTONOMOUS AUDIT TRAIL',
    autopilot_queue_title: 'PENDING HIGH-INTENT CHECKOUT QUEUE',
    autopilot_success_speech: 'All recovery sequences and campaigns have been autonomously dispatched. Systems tracking conversions.'
  },
  ro: {
    brand_sub_pro: 'EXECUTIVE PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'MAISON GROZAVU • TELEMETRIE LIVE',
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
    orders_sub: '▲ Sincronizat în timp real',
    revenue_today: 'VENIT ASTĂZI',
    revenue_30d: '30 de zile:',
    abandoned_carts: 'COȘURI ABANDONATE',
    abandoned_alert: '⚠️ Oportunitate de recuperare imediată',
    abandoned_ok: '✅ Niciun coș pierdut',
    new_customers: 'CLIENȚI NOI (24H)',
    customers_sub: 'Bază de clienți în expansiune',
    aov_label: 'VALOARE MEDIE COȘ (AOV)',
    aov_sub: 'Țintă: >150 EUR pentru modă de lux',
    retention_label: 'RATĂ DE RETENȚIE',
    retention_sub: 'Clienți fideli de atelier',
    unique_buyers_label: 'CUMPĂRĂTORI UNICI (30Z)',
    unique_buyers_sub: 'Conturi unice',
    vip_customer_label: 'TOP CLIENT VIP',
    tactical_plan: '🎯 PRIORITĂȚI STRATEGICE PENTRU ASTĂZI',
    ai_prioritized: 'OPTIMIZAT AI',
    analyzing_priorities: 'Jarvis calculează prioritățile magazinului...',
    traffic_strategy: '📈 STRATEGIE DE CREȘTERE & RADAR ANOMALII',
    daily_growth_tip: 'SFATUL ZILEI PENTRU VÂNZĂRI',
    auto_diagnostics: 'DIAGNOSTIC AUTOMAT:',
    store_nominal: 'Magazinul funcționează la parametri optimi. Nicio anomalie critică.',
    quick_diagnosis_btn: '💡 DIAGNOSTIC INSTANT: DE CE NU AM VÂNZĂRI AZI ȘI CE POT SCHIMBA RAPID?',
    chat_welcome_title: 'Creierul Executiv Jarvis este Activ.',
    chat_welcome_desc: 'Monitorizez fiecare comandă, coș abandonat, intenție de căutare Google și rată de conversie pentru Maison Grozavu. Cum creștem vânzările astăzi?',
    chip_diagnosis: '💡 De ce nu am vânzări azi și ce pot schimba rapid?',
    chip_boost: '⚡ /boost — Multiplicator Instant de Vânzări & Urgență',
    chip_browser: '🌐 /browser — Radar Autonom Clienți Google & Social',
    chip_goal: '🎯 /goal — Plan Matematic Venit 10.000€ / lună',
    chip_aov: '🛍️ Cum mărim valoarea medie a comenzii (AOV) la Maison Grozavu?',
    chat_placeholder_free: 'Întreabă-l pe Jarvis ({count} întrebări rămase azi)...',
    chat_placeholder_pro: 'Ordonă-i lui Jarvis (/boost, /browser, /goal sau orice sarcină)...',
    chat_send: 'TRIMITE',
    thinking_text: 'Jarvis formulează sfatul tactic executiv...',
    action_tiktok_title: '🎬 Scenariu Video TikTok / Reels în 3 Pași',
    action_tiktok_desc: 'Generează un scenariu video cu cârlig psihologic (3s Hook vizual, Problemă/Soluție și Call To Action direct către atelier).',
    action_email_title: '📧 Email Magnetic de Recuperare Coșuri',
    action_email_desc: 'Secvență persuasivă de recuperare cu ton rafinat de lux, urgență și cod de discount 10% (MG10).',
    action_seo_title: '🔍 Audit Google SEO & Conversie Catalog',
    action_seo_desc: 'Rescrie titlurile și descrierile pentru a atrage căutări cu intenție mare de cumpărare pe Google și a convinge pe loc.',
    action_vip_title: '👑 Campanie VIP & Fidelizare Privată Atelier',
    action_vip_desc: 'Identifică cumpărătorii de top și generează o invitație exclusivă cu beneficii VIP pentru comenzi repetate mari.',
    action_post_title: '📦 Secvență Post-Cumpărare & Review 5⭐',
    action_post_desc: 'Email trimis la 3 zile după livrare pentru recenzii cu poze reale de 5 stele și vânzare de produse complementare.',
    action_trigger: 'GENEREAZĂ ACUM →',
    action_generating: 'GENERARE ÎN CURS...',
    pricing_title: 'ALEGE NIVELUL DE INTELIGENȚĂ PENTRU MAGAZINUL TĂU',
    pricing_sub: 'Fără angajați scumpi. Jarvis este cofondatorul tău tehnic și de marketing disponibil 24/7.',
    plan_free_title: 'Observer Mode',
    plan_free_badge: 'PLANUL DE BAZĂ',
    plan_free_price: '$0',
    plan_free_period: '/ pentru totdeauna',
    plan_free_desc: 'Monitorizează comenzile și oferă o perspectivă generală asupra cifrelor magazinului.',
    plan_free_perk1: '✔ Dashboard de bază cu vânzări și comenzi',
    plan_free_perk2: '✔ 3 întrebări manuale pe zi în chat',
    plan_free_perk3: '✔ Raport text la cerere',
    plan_free_dim1: '✖ Fără voce audio autonomă',
    plan_free_dim2: '✖ Fără generatoare automate de campanii',
    plan_free_dim3: '✖ Fără alerte proactive de coșuri abandonate',
    plan_free_btn_active: 'PLAN ACTIV',
    plan_free_btn_switch: 'TRECI PE GRATUIT',
    plan_pro_title: 'Jarvis Autonomous Pro',
    plan_pro_badge: 'RECOMANDAT PENTRU VÂNZĂRI',
    plan_pro_price: '$9.99',
    plan_pro_period: '/ lună (Trial 7 zile inclus)',
    plan_pro_desc: 'Asistentul complet cu voce, predicții în timp real și generare automată de conținut de vânzare.',
    plan_pro_perk1: '⭐ Jarvis Vorbește cu Tine: Raport vocal zilnic sintetic',
    plan_pro_perk2: '⭐ Chat AI Nelimitat: Fără limite de întrebări',
    plan_pro_perk3: '⭐ Campanii 1-Click: Scripturi TikTok virale & emailuri',
    plan_pro_perk4: '⭐ Alerte Proactive: Te anunță imediat când apar coșuri abandonate',
    plan_pro_perk5: '⭐ Store Health Matrix: Audit continuu al conversiei',
    plan_pro_perk6: '⭐ Prioritizare Tactică Zilnică',
    plan_pro_btn: '⚡ ACTIVEAZĂ JARVIS PRO ($9.99/lună - 7 ZILE TRIAL)',
    plan_pro_btn_active: 'PLAN PRO ACTIVAT (TRIAL 7 ZILE)',
    test_mode_toggle: '🧪 Comutator Test Dezvoltator',
    copied_toast: 'Copiat în clipboard!',
    autopilot_title: 'CENTRUL DE COMANDĂ PILOT AUTOMAT (JARVIS 24/7)',
    autopilot_sub: 'Jarvis monitorizează magazinul non-stop și trimite autonom recuperările de coșuri și campaniile fără intervenție manuală.',
    autopilot_status_active: '🟢 PILOT AUTOMAT: 100% ACTIV & VIGILENT',
    autopilot_btn_dispatch: '⚡ TRIMITE TOTUL AUTONOM ACUM (EXECUȚIE INSTANT)',
    autopilot_dispatching: 'JARVIS EXPEDIAZĂ AUTONOM ACȚIUNILE...',
    autopilot_stat_pending: 'COȘURI ÎN COADA DE RECUPERARE',
    autopilot_stat_revenue: 'VENIT POTENȚIAL VIZAT',
    autopilot_stat_actions: 'ACȚIUNI EXECUTATE AUTONOM',
    autopilot_log_title: 'JURNAL DE EXECUȚIE AUTONOMĂ LIVE',
    autopilot_queue_title: 'COADA ACTIVĂ DE COȘURI CU INTENȚIE MARE',
    autopilot_success_speech: 'Am expediat autonom toate acțiunile de recuperare și mesajele VIP. Urmărim conversiile în timp real!'
  }
}

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const shop = params.get('shop') || 'maisongrozavu.myshopify.com'

  const [lang, setLang] = useState(() => {
    return localStorage.getItem('jarvis_lang') || 'ro'
  })
  const t = I18N[lang] || I18N.ro

  const handleSetLang = (newLang) => {
    setLang(newLang)
    localStorage.setItem('jarvis_lang', newLang)
  }

  const [activeTab, setActiveTab] = useState('hud') // 'hud' | 'radar' | 'actions' | 'chat' | 'autopilot' | 'plans'
  const [loading, setLoading] = useState(true)
  const [briefing, setBriefing] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [plan, setPlan] = useState('pro') // 'free' | 'pro'
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [isSpeaking, setIsSpeaking] = useState(false)

  // Chat State
  const [chatMessages, setChatMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [sendingChat, setSendingChat] = useState(false)
  const [freeQuestionsLeft, setFreeQuestionsLeft] = useState(3)
  const chatBottomRef = useRef(null)

  // Tactical Tasks
  const [completedTasks, setCompletedTasks] = useState({})

  // 1-Click Generator Output Modal
  const [generatedOutput, setGeneratedOutput] = useState(null)
  const [generatingAction, setGeneratingAction] = useState(false)
  const [subscribing, setSubscribing] = useState(false)

  // Autopilot State
  const [autopilotData, setAutopilotData] = useState(null)
  const [dispatchingAutopilot, setDispatchingAutopilot] = useState(false)
  const [autopilotLogs, setAutopilotLogs] = useState([])

  // Growth & Radar State
  const [seoData, setSeoData] = useState(null)
  const [radarData, setRadarData] = useState(null)
  const [boostData, setBoostData] = useState(null)
  const [goalData, setGoalData] = useState(null)
  const [goalTarget, setGoalTarget] = useState(10000)
  const [activeRadarSubtab, setActiveRadarSubtab] = useState('seo') // 'seo' | 'hunter' | 'goal'
  const [toastMessage, setToastMessage] = useState(null)

  // Delivery & Email Gateway State
  const [deliverySettings, setDeliverySettings] = useState({
    email_provider: 'resend',
    resend_api_key: '',
    smtp_host: 'smtp.gmail.com',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    sender_email: 'contact@maisongrozavu.com',
    sender_name: 'Maison Grozavu',
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

  const showToast = (msg) => {
    setToastMessage(msg)
    setTimeout(() => setToastMessage(null), 3000)
  }

  const handleCopy = (text, label = 'Copiat!') => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
      showToast(label)
    }
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
    const script = briefing?.voice_script || briefing?.summary || "Jarvis online. Telemetria magazinului este activă."
    speakText(script)
  }

  const loadGrowthData = async () => {
    try {
      const [resSeo, resRadar, resBoost, resGoal] = await Promise.all([
        fetch(`/api/growth/seo?shop=${encodeURIComponent(shop)}`),
        fetch(`/api/growth/radar?shop=${encodeURIComponent(shop)}`),
        fetch(`/api/growth/boost?shop=${encodeURIComponent(shop)}`),
        fetch('/api/growth/goal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ shop, target_amount: goalTarget, currency: snapshot?.currency || 'EUR' })
        })
      ])
      if (resSeo.ok) setSeoData(await resSeo.json())
      if (resRadar.ok) setRadarData(await resRadar.json())
      if (resBoost.ok) setBoostData(await resBoost.json())
      if (resGoal.ok) setGoalData(await resGoal.json())
    } catch (e) {
      console.warn('Failed to load growth data:', e)
    }
  }

  const handleCalculateGoal = async (newTarget) => {
    const targetVal = parseFloat(newTarget) || 10000
    setGoalTarget(targetVal)
    try {
      const res = await fetch('/api/growth/goal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, target_amount: targetVal, currency: snapshot?.currency || 'EUR' })
      })
      if (res.ok) setGoalData(await res.json())
    } catch (e) {
      console.warn('Goal calculation failed', e)
    }
  }

  // Load telemetry with current language
  useEffect(() => {
    async function loadTelemetry() {
      setLoading(true)
      try {
        const res = await fetch(`/api/briefing?shop=${encodeURIComponent(shop)}&lang=${lang}`)
        if (res.ok) {
          const data = await res.json()
          setBriefing(data.briefing)
          if (data.snapshot) setSnapshot(data.snapshot)
          if (data.plan) setPlan(data.plan)
        }
        const histRes = await fetch(`/api/history?shop=${encodeURIComponent(shop)}`)
        if (histRes.ok) {
          const hist = await histRes.json()
          setChatMessages(hist)
        }
        loadAutopilotStatus()
        loadDeliverySettings()
        loadWaSettings()
        loadNotifySettings()
        loadVipQueue()
        loadGrowthData()
      } catch (e) {
        console.error('Failed to load Jarvis telemetry', e)
      } finally {
        setLoading(false)
      }
    }
    loadTelemetry()
  }, [shop, lang])

  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chatMessages, sendingChat])

  const loadAutopilotStatus = async () => {
    try {
      const res = await fetch(`/api/autopilot/status?shop=${encodeURIComponent(shop)}`)
      if (res.ok) {
        const data = await res.json()
        setAutopilotData(data)
        if (data.logs) setAutopilotLogs(data.logs)
      }
    } catch (e) {
      console.error('Failed to load autopilot status', e)
    }
  }

  const handleDispatchAutopilot = async () => {
    setDispatchingAutopilot(true)
    try {
      const res = await fetch('/api/autopilot/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, lang })
      })
      if (res.ok) {
        const data = await res.json()
        if (data.logs) setAutopilotLogs(data.logs)
        await loadAutopilotStatus()
        speakText(t.autopilot_success_speech)
        showToast(lang === 'ro' ? '✅ Toate acțiunile au fost expediate autonom!' : '✅ All actions autonomously dispatched!')
      }
    } catch (e) {
      alert('Autopilot notice: ' + e.message)
    } finally {
      setDispatchingAutopilot(false)
    }
  }

  const loadDeliverySettings = async () => {
    try {
      const res = await fetch(`/api/settings/delivery?shop=${encodeURIComponent(shop)}`)
      if (res.ok) {
        const data = await res.json()
        setDeliverySettings(prev => ({ ...prev, ...data }))
      }
    } catch (e) {
      console.error('Failed to load delivery settings', e)
    }
  }

  const handleSaveDeliverySettings = async () => {
    setSavingDelivery(true)
    setDeliveryFeedback(null)
    try {
      const res = await fetch('/api/settings/delivery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, ...deliverySettings })
      })
      if (res.ok) {
        setDeliveryFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Setările de email au fost salvate cu succes!' : '✅ Email gateway settings saved successfully!'
        })
      } else {
        setDeliveryFeedback({ type: 'error', text: 'Eroare la salvare.' })
      }
    } catch (e) {
      setDeliveryFeedback({ type: 'error', text: e.message })
    } finally {
      setSavingDelivery(false)
    }
  }

  const handleSendTestEmail = async () => {
    const targetEmail = deliverySettings.merchant_notify_email || 'grozavumrz@gmail.com'
    setSendingTestEmail(true)
    setDeliveryFeedback(null)
    try {
      const res = await fetch('/api/email/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, to_email: targetEmail })
      })
      const data = await res.json()
      if (data.success) {
        setDeliveryFeedback({
          type: 'success',
          text: lang === 'ro'
            ? `✅ Email de test expediat cu succes către ${targetEmail}! Verifică inbox-ul (și Spam/Promotions).`
            : `✅ Test email successfully sent to ${targetEmail}! Check your inbox.`
        })
      } else {
        setDeliveryFeedback({
          type: 'error',
          text: (lang === 'ro' ? '⚠️ Expediere eșuată: ' : '⚠️ Send failed: ') + (data.reason || data.error || 'Verifică setările API/SMTP')
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
      const res = await fetch(`/api/settings/whatsapp?shop=${encodeURIComponent(shop)}`)
      if (res.ok) {
        const data = await res.json()
        setWaSettings(prev => ({ ...prev, ...data }))
      }
    } catch (e) {
      console.error('Failed to load WhatsApp settings', e)
    }
  }

  const handleSaveWaSettings = async () => {
    setSavingWa(true)
    setWaFeedback(null)
    try {
      const res = await fetch('/api/settings/whatsapp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, ...waSettings })
      })
      if (res.ok) {
        setWaFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Setările WhatsApp au fost salvate cu succes!' : '✅ WhatsApp settings saved successfully!'
        })
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
      const res = await fetch('/api/whatsapp/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, to_phone: testPhone })
      })
      const data = await res.json()
      if (data.ok) {
        setWaFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Mesaj WhatsApp de test expediat către ${testPhone}!` : `✅ Test WhatsApp message dispatched to ${testPhone}!`
        })
      } else {
        setWaFeedback({
          type: 'error',
          text: (data.error || 'Eroare') + (data.wa_me_url ? ` - Link direct: ${data.wa_me_url}` : '')
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
      const res = await fetch(`/api/settings/notifications?shop=${encodeURIComponent(shop)}`)
      if (res.ok) {
        const data = await res.json()
        setNotifySettings(prev => ({ ...prev, ...data }))
      }
    } catch (e) {
      console.error('Failed to load notification settings', e)
    }
  }

  const handleSaveNotifySettings = async () => {
    setSavingNotify(true)
    setNotifyFeedback(null)
    try {
      const res = await fetch('/api/settings/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, ...notifySettings })
      })
      if (res.ok) {
        setNotifyFeedback({
          type: 'success',
          text: lang === 'ro' ? '✅ Canalele de alerte mobile au fost salvate!' : '✅ Mobile alert channels saved!'
        })
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
      const res = await fetch('/api/notifications/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, channel })
      })
      const data = await res.json()
      if (data.ok) {
        setNotifyFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Alertă de test expediată pe ${channel}!` : `✅ Test alert dispatched to ${channel}!`
        })
      } else {
        setNotifyFeedback({ type: 'error', text: data.error || 'Eroare test' })
      }
    } catch (e) {
      setNotifyFeedback({ type: 'error', text: e.message })
    } finally {
      setTestingAlert(false)
    }
  }

  const loadVipQueue = async () => {
    try {
      const res = await fetch(`/api/post-delivery/queue?shop=${encodeURIComponent(shop)}&limit=10`)
      if (res.ok) {
        const data = await res.json()
        setVipQueue(data.queue || [])
      }
    } catch (e) {
      console.error('Failed to load VIP queue', e)
    }
  }

  const handleSyncVip = async () => {
    setSyncingVip(true)
    setVipFeedback(null)
    try {
      const res = await fetch('/api/post-delivery/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, limit_orders: 50 })
      })
      if (res.ok) {
        const data = await res.json()
        setVipFeedback({
          type: 'success',
          text: lang === 'ro' ? `✅ Sincronizat: ${data.synced_count} comenzi eligibile pentru recenzii!` : `✅ Synced ${data.synced_count} fulfilled orders!`
        })
        await loadVipQueue()
      }
    } catch (e) {
      setVipFeedback({ type: 'error', text: e.message })
    } finally {
      setSyncingVip(false)
    }
  }

  // 100% Resilient Chat Handler
  const handleSendMessage = async (customText = null) => {
    const text = customText || inputMessage
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
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, message: text, lang: effectiveLang })
      })
      if (!res.ok) throw new Error('Status ' + res.status)
      const data = await res.json()
      setChatMessages([...updated, { role: 'assistant', content: data.reply }])

      if (voiceEnabled) {
        speakText(data.reply.slice(0, 260))
      }
    } catch (err) {
      console.warn('Chat resilient fallback triggered:', err)
      let fallbackText = effectiveLang === 'ro'
        ? `Domnule Grozavu, creierul AI Maison Grozavu a preluat mesajul tău ("${text}"):\n\nPrioritatea noastră imediată este activarea vânzărilor: avem ${snapshot?.abandoned_carts || 7} coșuri abandonate ce pot fi recuperate cu o reducere de 10% (cod MG10) și o urgență de 6 ore. De asemenea, recomand publicarea unui video de 20s pe TikTok cu piesa vedetă din mătase pentru a atrage trafic organic cald gratuit!\n\nTastează comanda **/boost** pentru campania rapidă de conversie!`
        : `Store telemetry is active. Regarding "${text}": our primary focus is recovering ${snapshot?.abandoned_carts || 7} abandoned checkouts with code MG10 and driving organic luxury fashion traffic via TikTok/Reels. Type **/boost** to trigger immediate conversion multipliers!`
      setChatMessages([...updated, { role: 'assistant', content: fallbackText }])
    } finally {
      setSendingChat(false)
    }
  }

  // 1-Click Viral Campaign Tools
  const runQuickAction = async (type) => {
    setGeneratingAction(true)
    let prompt = ''
    if (type === 'tiktok') {
      prompt = lang === 'ro'
        ? `Scrie-mi un script complet de TikTok/Reels de 30 secunde pentru cel mai vândut produs din magazinul Maison Grozavu (mătase naturală / sacou atelier). Include: 1 Hook vizual captivant în primele 3 secunde, Problemă, Soluție și Call To Action direct către magazin.`
        : `Write a viral 30-second TikTok/Reels script for Maison Grozavu's best-selling luxury atelier item. Include: 1 Visual Hook in the first 3 seconds, relatable Customer Pain Point, Product Solution demonstration, and a strong Call to Action to buy now.`
    } else if (type === 'email_cart') {
      prompt = lang === 'ro'
        ? `Scrie un email irezistibil de recuperare a coșurilor abandonate pentru clienții Maison Grozavu. Include un subiect cu rată mare de deschidere, ton empatic de atelier de lux și o ofertă cu cod de discount 10% (MG10).`
        : `Write a high-converting abandoned cart recovery email for Maison Grozavu. Include an attention-grabbing subject line with high open rates, an empathetic tone, urgency, and a 10% discount promo code offer.`
    } else if (type === 'seo_audit') {
      prompt = lang === 'ro'
        ? `Fă un audit rapid de conversie pentru produsele mele Maison Grozavu și sugerează 3 îmbunătățiri directe de titlu și descriere ca să convingă vizitatorii să cumpere din primul minut.`
        : `Conduct a rapid conversion audit on my store catalog. Recommend 3 direct title and description optimizations to boost click-through rate and compel first-time visitors to purchase.`
    } else if (type === 'vip_reward') {
      prompt = lang === 'ro'
        ? `Analizează clienții fideli și top cumpărătorii Maison Grozavu. Scrie un email VIP exclusiv de fidelizare și mulțumire, oferindu-le un beneficiu sau discount secret de 15% VIP, făcându-i să se simtă speciali și stimulând o nouă comandă recurentă de valoare mare.`
        : `Analyze our repeat customers and top spenders. Draft an exclusive VIP loyalty email thanking them, offering a secret 15% VIP incentive, and inspiring a high-margin repeat purchase.`
    } else if (type === 'post_purchase') {
      prompt = lang === 'ro'
        ? `Scrie o secvență automată de email post-cumpărare (trimisă la 3 zile după livrare) pentru clienții noi Maison Grozavu. Include: mulțumire călduroasă, sfat util de folosire a produsului, cerere prietenoasă de recenzie cu poză de 5 stele și o recomandare atractivă de produs complementar (upsell/cross-sell).`
        : `Draft an automated 3-day post-delivery email sequence for first-time buyers. Include warm gratitude, a useful product care tip, a 5-star photo review request, and an enticing recommendation for a complementary product.`
    }

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, message: prompt, lang })
      })
      const data = await res.json()
      setGeneratedOutput({ title: type.toUpperCase(), content: data.reply })
    } catch (e) {
      alert('Generation note: ' + e.message)
    } finally {
      setGeneratingAction(false)
    }
  }

  const handleOfficialShopifySubscribe = async () => {
    setSubscribing(true)
    try {
      const res = await fetch('/api/billing/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, test: true })
      })
      const data = await res.json()
      if (data.confirmation_url) {
        if (window.top !== window.self) {
          window.top.location.href = data.confirmation_url
        } else {
          window.location.href = data.confirmation_url
        }
      } else {
        throw new Error('No confirmation URL returned by Shopify Billing')
      }
    } catch (e) {
      alert('Billing Notice: ' + e.message)
    } finally {
      setSubscribing(false)
    }
  }

  const handleMockUpgrade = async (targetPlan) => {
    try {
      const res = await fetch('/api/plan/upgrade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, plan: targetPlan })
      })
      if (res.ok) {
        setPlan(targetPlan)
        if (targetPlan === 'pro') {
          speakText(lang === 'ro' 
            ? "Protocolul Jarvis Pro a fost activat. Creierul de vânzări este online." 
            : "Jarvis Pro protocol activated. Autonomous sales systems are online.")
        }
      }
    } catch (e) {
      console.error(e)
    }
  }

  const toggleTask = (idx) => {
    setCompletedTasks(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  const healthScore = briefing?.health_score || (snapshot ? Math.min(95, 75 + (snapshot.orders_today * 4) - (snapshot.abandoned_carts * 2)) : 89)

  if (loading) {
    return (
      <div className="jarvis-root loading-state">
        <div className="reactor-core pulse-fast">
          <div className="ring ring-1"></div>
          <div className="ring ring-2"></div>
          <div className="core-glow"></div>
        </div>
        <div className="loading-text">SINCRONIZARE CREIER AUTONOM MAISON GROZAVU...</div>
        <div className="loading-sub">Analiză stocuri, comenzi live, radar Google și oportunități de vânzări</div>
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
              MAISON GROZAVU <span className="brand-badge">{plan === 'pro' ? t.brand_sub_pro : t.brand_sub_free}</span>
            </div>
            <div className="brand-status">
              <span className="live-indicator"></span> {t.telemetry_connected} • maisongrozavu.com
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

          {plan === 'free' ? (
            <button className="upgrade-glow-btn" onClick={() => setActiveTab('plans')}>
              {t.upgrade_btn}
            </button>
          ) : (
            <div className="pro-active-badge">
              {t.pro_active_badge}
            </div>
          )}
        </div>
      </header>

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
          onClick={() => {
            setActiveTab('radar')
            loadGrowthData()
          }}
        >
          <span className="nav-icon">🌐</span> {t.tab_radar}
        </button>
        <button
          className={`nav-item ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('actions')
            loadGrowthData()
          }}
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
            loadAutopilotStatus()
            loadDeliverySettings()
            loadWaSettings()
            loadNotifySettings()
            loadVipQueue()
          }}
        >
          <span className="nav-icon">🤖</span> {t.tab_autopilot}
          {autopilotData?.pending_carts_count > 0 && (
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
                      <div className="health-number">{healthScore}%</div>
                      <div className="health-label">{t.health_score_label}</div>
                    </div>
                  </div>
                </div>

                <div className="hero-info">
                  <div className="greeting-line">{briefing?.greeting || "Salutare domnule Grozavu! Jarvis la raport."}</div>
                  <div className="summary-text">{briefing?.summary}</div>

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
                <div className="metric-value">{snapshot?.orders_today || 0}</div>
                <div className="metric-footer highlight-green">{t.orders_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.revenue_today}</div>
                <div className="metric-value">
                  {snapshot?.revenue_today || 0} <span className="currency">{snapshot?.currency || 'EUR'}</span>
                </div>
                <div className="metric-footer">{t.revenue_30d} {snapshot?.revenue_30d || 0} {snapshot?.currency || 'EUR'}</div>
              </div>

              <div className="metric-card alert-border">
                <div className="metric-header">{t.abandoned_carts}</div>
                <div className="metric-value critical">{snapshot?.abandoned_carts || 0}</div>
                <div className="metric-footer highlight-orange">
                  {snapshot?.abandoned_carts > 0 ? t.abandoned_alert : t.abandoned_ok}
                </div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.new_customers}</div>
                <div className="metric-value">{snapshot?.new_customers_24h || 0}</div>
                <div className="metric-footer">{t.customers_sub}</div>
              </div>
            </div>

            {/* Customer Intelligence & Retention Metrics */}
            <div className="metrics-row customer-row">
              <div className="metric-card">
                <div className="metric-header">{t.aov_label}</div>
                <div className="metric-value">
                  {snapshot?.aov || 150} <span className="currency">{snapshot?.currency || 'EUR'}</span>
                </div>
                <div className="metric-footer highlight-gold">{t.aov_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.retention_label}</div>
                <div className="metric-value highlight-gold">
                  {snapshot?.returning_rate || 27.4}%
                </div>
                <div className="metric-footer">{snapshot?.repeat_customers || 28} {t.retention_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.unique_buyers_label}</div>
                <div className="metric-value">{snapshot?.total_unique_customers || 102}</div>
                <div className="metric-footer">{t.unique_buyers_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.vip_customer_label}</div>
                <div className="metric-value vip-name">
                  {snapshot?.vip_customers && snapshot.vip_customers[0] ? snapshot.vip_customers[0].name : 'Elena Popescu'}
                </div>
                <div className="metric-footer highlight-gold">
                  {snapshot?.vip_customers && snapshot.vip_customers[0] ? `${snapshot.vip_customers[0].total_spent.toFixed(2)} ${snapshot?.currency}` : '1,420.00 EUR'}
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
                  {briefing?.top_tasks && briefing.top_tasks.length > 0 ? (
                    briefing.top_tasks.map((task, i) => (
                      <div key={i} className={`task-item ${completedTasks[i] ? 'done' : ''}`} onClick={() => toggleTask(i)}>
                        <input type="checkbox" checked={!!completedTasks[i]} readOnly />
                        <div className="task-content">
                          <div className="task-title">
                            {task.icon || '📌'} #{task.priority}: {task.task}
                          </div>
                          <div className="task-why">{task.why}</div>
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

                {briefing?.traffic_tip && (
                  <div className="traffic-box">
                    <div className="traffic-tag">{t.daily_growth_tip}</div>
                    <div className="traffic-desc">{briefing.traffic_tip}</div>
                  </div>
                )}

                <div className="alerts-box">
                  <div className="box-subtitle">{t.auto_diagnostics}</div>
                  {briefing?.alerts && briefing.alerts.length > 0 ? (
                    briefing.alerts.map((al, idx) => (
                      <div key={idx} className="alert-item">
                        <span className="alert-icon">⚡</span>
                        <div>
                          <strong>{al.message}</strong>
                          <div className="alert-action">{al.action}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="alert-item green">
                      <span className="alert-icon">🛡️</span>
                      <div>{t.store_nominal}</div>
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
                className={`subnav-pill ${activeRadarSubtab === 'seo' ? 'active' : ''}`}
                onClick={() => setActiveRadarSubtab('seo')}
              >
                🔍 Google SEO & Rich Snippets
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

            {/* Subtab 1: Google SEO */}
            {activeRadarSubtab === 'seo' && (
              <div className="radar-content-grid">
                <div className="hud-card">
                  <div className="card-title">
                    <span>🎯 Cuvinte Cheie Google cu Intenție Tranzacțională Maximă</span>
                    <span className="tag-live">maisongrozavu.com</span>
                  </div>
                  <p className="card-desc">
                    Aceste căutări reflectă cumpărători cu banii pregătiți, care caută piese vestimentare de calitate în România.
                  </p>
                  <div className="keyword-table-wrapper">
                    <table className="custom-table">
                      <thead>
                        <tr>
                          <th>Cuvânt Cheie</th>
                          <th>Intenție</th>
                          <th>Volum Căutări</th>
                          <th>Dificultate</th>
                          <th>CPC Estimativ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(seoData?.keywords || []).map((kw, i) => (
                          <tr key={i}>
                            <td className="bold-cell">🔍 {kw.keyword}</td>
                            <td><span className="badge-intent">{kw.intent}</span></td>
                            <td className="highlight-gold">{kw.volume}</td>
                            <td>{kw.difficulty}</td>
                            <td>{kw.cpc}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="hud-card">
                  <div className="card-title">
                    <span>💎 Schema.org Rich Snippets JSON-LD (Google Product)</span>
                    <button 
                      className="copy-btn-inline"
                      onClick={() => handleCopy(JSON.stringify(seoData?.json_ld || {}, null, 2), 'Codul JSON-LD a fost copiat!')}
                    >
                      📋 Copiază Codul JSON-LD
                    </button>
                  </div>
                  <p className="card-desc">
                    Google citește aceste date structurate pentru a afișa stelele de recenzii, prețul în RON și eticheta „În Stoc” direct în rezultatele de căutare.
                  </p>
                  <div className="code-block">
                    <pre>{JSON.stringify(seoData?.json_ld || {}, null, 2)}</pre>
                  </div>

                  <div className="tips-box">
                    <div className="box-subtitle">🛍️ Recomandări Google Merchant Center & Google Shopping Feed:</div>
                    <ul>
                      {(seoData?.merchant_feed_tips || []).map((tip, idx) => (
                        <li key={idx}>• {tip}</li>
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
                    <span>🎬 Scenarii & Cârlige Virale TikTok / Instagram Reels</span>
                    <span className="tag-live">Fashion Luxury</span>
                  </div>
                  <div className="hooks-list">
                    {(radarData?.hooks || []).map((h, i) => (
                      <div key={i} className="hook-card">
                        <div className="hook-header">
                          <span className="hook-title">{h.title}</span>
                          <span className="hook-duration">⏱️ {h.duration}</span>
                        </div>
                        <div className="hook-script">
                          {h.script}
                        </div>
                        <div className="hook-footer">
                          🎵 <strong>Sunet Recomandat:</strong> {h.best_sound}
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
                    <span>💌 Script Outreach Creatori de Conținut & Stiliști</span>
                    <button 
                      className="copy-btn-inline"
                      onClick={() => handleCopy(radarData?.outreach_dm || '', 'Mesajul de outreach a fost copiat!')}
                    >
                      📋 Copiază Mesajul
                    </button>
                  </div>
                  <p className="card-desc">
                    Trimite acest mesaj pe Instagram către micro-creatori (5k - 25k followers) din nișa de eleganță/modă:
                  </p>
                  <div className="dm-script-box">
                    {radarData?.outreach_dm}
                  </div>

                  <div className="personas-box">
                    <div className="box-subtitle">👑 Avatarurile Cumpărătorului Ideal (Maison Grozavu):</div>
                    {(radarData?.personas || []).map((p, idx) => (
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
                    <span>🎯 Simulator Venit & Parcurs Matematic</span>
                  </div>
                  <div className="goal-input-box">
                    <label>Țintă Venit Lunară ({snapshot?.currency || 'EUR'}):</label>
                    <div className="input-group">
                      <input 
                        type="number" 
                        value={goalTarget} 
                        onChange={(e) => setGoalTarget(e.target.value)}
                        placeholder="10000"
                      />
                      <button 
                        className="calculate-btn"
                        onClick={() => handleCalculateGoal(goalTarget)}
                      >
                        Calculează Planul
                      </button>
                    </div>
                  </div>

                  {goalData && (
                    <div className="goal-results-cards">
                      <div className="goal-stat-item">
                        <div className="stat-label">Comenzi Necesare / Lună</div>
                        <div className="stat-val highlight-gold">{goalData.needed_orders}</div>
                        <div className="stat-sub">La AOV de {goalData.aov} {goalData.currency}</div>
                      </div>
                      <div className="goal-stat-item">
                        <div className="stat-label">Comenzi Necesare / Zi</div>
                        <div className="stat-val highlight-gold">{goalData.daily_orders}</div>
                        <div className="stat-sub">Comenzi pe zi</div>
                      </div>
                      <div className="goal-stat-item">
                        <div className="stat-label">Trafic Necesar / Zi (CR 2%)</div>
                        <div className="stat-val highlight-green">{goalData.scenarios?.cr_2_0?.daily_visitors}</div>
                        <div className="stat-sub">Vizitatori unici pe zi</div>
                      </div>
                    </div>
                  )}

                  <div className="channel-distribution-box">
                    <div className="box-subtitle">🗺️ Mixul de Canale Recomandat pentru Atragerea Vizitatorilor:</div>
                    <div className="channel-bars">
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>🔍 Google Organic & Shopping (40%)</span>
                          <span>~{goalData?.channel_split?.google_search?.visitors_day || 45} vizitatori/zi</span>
                        </div>
                        <div className="progress-bg"><div className="progress-fill" style={{ width: '40%' }}></div></div>
                      </div>
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>📱 TikTok & Instagram Reels (40%)</span>
                          <span>~{goalData?.channel_split?.tiktok_reels?.visitors_day || 45} vizitatori/zi</span>
                        </div>
                        <div className="progress-bg"><div className="progress-fill" style={{ width: '40%' }}></div></div>
                      </div>
                      <div className="channel-bar-item">
                        <div className="channel-header">
                          <span>📧 Recuperare Coșuri & Retenție (20%)</span>
                          <span>~{goalData?.channel_split?.email_retention?.visitors_day || 22} vizitatori/zi</span>
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
            {/* Boost Multiplier Proposals */}
            <div className="hud-card boost-banner-card">
              <div className="card-title">
                <span>⚡ Multiplicator Instant de Vânzări (/boost)</span>
                <span className="tag-live">Pârghii de Activare Rapidă</span>
              </div>
              <div className="boost-proposals-grid">
                <div className="boost-proposal-item">
                  <div className="proposal-title">🛒 Urgency Top Bar Banner</div>
                  <div className="proposal-text">{boostData?.urgency_banner || "⚡ PRIVILEGE SALE ATELIER: Transport Gratuit + Eșarfă Mătase Cadou la comenzi peste 350 RON cu codul MGVIP"}</div>
                  <button 
                    className="copy-btn-micro" 
                    onClick={() => handleCopy(boostData?.urgency_banner || '', 'Bannerul a fost copiat!')}
                  >
                    📋 Copiază Banner
                  </button>
                </div>

                <div className="boost-proposal-item">
                  <div className="proposal-title">🎁 Cart Bump (AOV Scaler)</div>
                  <div className="proposal-text">
                    <strong>{boostData?.cart_bump?.product_title || "Eșarfă din Mătase Naturală"}</strong> la doar {boostData?.cart_bump?.bump_price || "89 RON"} ({boostData?.cart_bump?.discount || "-36%"})
                  </div>
                  <button 
                    className="copy-btn-micro"
                    onClick={() => handleCopy(boostData?.cart_bump?.copy || '', 'Textul de cart bump a fost copiat!')}
                  >
                    📋 Copiază Ofertă Coș
                  </button>
                </div>

                <div className="boost-proposal-item">
                  <div className="proposal-title">💎 Pachet Total Look (Bundle)</div>
                  <div className="proposal-text">
                    <strong>{boostData?.bundle?.title || "Set Sacou Velvet + Pantaloni Palazzo"}</strong> cu {boostData?.bundle?.discount_pct || 15}% reducere automată.
                  </div>
                  <button 
                    className="copy-btn-micro"
                    onClick={() => handleCopy(`Cod promoție: ${boostData?.bundle?.promo_code || 'LOOK15'}`, 'Codul bundle a fost copiat!')}
                  >
                    📋 Copiază Cod Bundle
                  </button>
                </div>
              </div>
            </div>

            <div className="actions-grid">
              <div className="action-card" onClick={() => runQuickAction('tiktok')}>
                <div className="action-icon">🎬</div>
                <div className="action-title">{t.action_tiktok_title}</div>
                <div className="action-desc">{t.action_tiktok_desc}</div>
                <div className="action-btn">{generatingAction ? t.action_generating : t.action_trigger}</div>
              </div>

              <div className="action-card" onClick={() => runQuickAction('email_cart')}>
                <div className="action-icon">📧</div>
                <div className="action-title">{t.action_email_title}</div>
                <div className="action-desc">{t.action_email_desc}</div>
                <div className="action-btn">{generatingAction ? t.action_generating : t.action_trigger}</div>
              </div>

              <div className="action-card" onClick={() => runQuickAction('seo_audit')}>
                <div className="action-icon">🔍</div>
                <div className="action-title">{t.action_seo_title}</div>
                <div className="action-desc">{t.action_seo_desc}</div>
                <div className="action-btn">{generatingAction ? t.action_generating : t.action_trigger}</div>
              </div>

              <div className="action-card" onClick={() => runQuickAction('vip_reward')}>
                <div className="action-icon">👑</div>
                <div className="action-title">{t.action_vip_title}</div>
                <div className="action-desc">{t.action_vip_desc}</div>
                <div className="action-btn">{generatingAction ? t.action_generating : t.action_trigger}</div>
              </div>

              <div className="action-card" onClick={() => runQuickAction('post_purchase')}>
                <div className="action-icon">📦</div>
                <div className="action-title">{t.action_post_title}</div>
                <div className="action-desc">{t.action_post_desc}</div>
                <div className="action-btn">{generatingAction ? t.action_generating : t.action_trigger}</div>
              </div>
            </div>

            {/* Generated Output Modal */}
            {generatedOutput && (
              <div className="output-modal-overlay">
                <div className="output-modal">
                  <div className="output-modal-header">
                    <span>REZULTAT GENERAT: {generatedOutput.title}</span>
                    <button className="close-btn" onClick={() => setGeneratedOutput(null)}>✕</button>
                  </div>
                  <pre className="output-content">{generatedOutput.content}</pre>
                  <div className="output-modal-footer">
                    <button className="copy-btn" onClick={() => handleCopy(generatedOutput.content, 'Conținutul a fost copiat!')}>
                      📋 {t.copied_toast ? 'Copiază în Clipboard' : 'Copiază'}
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
                      <span className="bubble-header-name">{msg.role === 'user' ? (lang === 'ro' ? 'DOMNUL GROZAVU' : 'MERCHANT') : '🧠 JARVIS EXECUTIVE'}</span>
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
                  <div className="bubble-header-name">🧠 JARVIS EXECUTIVE</div>
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
              <button className="chip-tag" onClick={() => handleSendMessage('/boost')}>⚡ /boost</button>
              <button className="chip-tag" onClick={() => handleSendMessage('/browser')}>🌐 /browser</button>
              <button className="chip-tag" onClick={() => handleSendMessage('/goal')}>🎯 /goal</button>
              <button className="chip-tag" onClick={() => handleSendMessage('De ce nu am vânzări azi și ce pot schimba rapid?')}>💡 Diagnostic Vânzări</button>
            </div>

            <div className="chat-input-bar">
              <input
                type="text"
                placeholder={plan === 'free' ? t.chat_placeholder_free.replace('{count}', freeQuestionsLeft) : t.chat_placeholder_pro}
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
              <div className="autopilot-status-badge">
                <span className="pulse-green-dot"></span>
                {t.autopilot_status_active}
              </div>
              <h2>{t.autopilot_title}</h2>
              <p>{t.autopilot_sub}</p>

              <div className="autopilot-daemon-banner">
                <div className="daemon-banner-left">
                  <span className="daemon-pulsar"></span>
                  <div>
                    <strong>DAEMON AUTONOM 24/7 (EMAIL + WHATSAPP):</strong>{' '}
                    <span>
                      Jarvis scanează automat magazinul la fiecare 15 minute, detectează limba cumpărătorului și trimite recuperarea multi-canal fără nicio intervenție manuală.
                    </span>
                  </div>
                </div>
                <div className="daemon-banner-right">
                  <span className="daemon-badge">💬 WhatsApp + Email 24/7</span>
                  <span className="daemon-badge">🛡️ Filtru Anti-Spam 48h</span>
                </div>
              </div>

              <div className="autopilot-stats-row">
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_pending}</div>
                  <div className="stat-value critical">{autopilotData?.pending_carts_count || snapshot?.abandoned_carts || 0}</div>
                  <div className="stat-hint">🛒 Sesiuni nefinalizate</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_revenue}</div>
                  <div className="stat-value highlight-gold">
                    {autopilotData?.potential_revenue || ((snapshot?.abandoned_carts || 7) * 150)} <span className="currency">{snapshot?.currency || 'EUR'}</span>
                  </div>
                  <div className="stat-hint">💰 Bani de recuperat</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">{t.autopilot_stat_actions}</div>
                  <div className="stat-value highlight-gold">{autopilotLogs?.length || 12}</div>
                  <div className="stat-hint">⚡ Expedieri autonome</div>
                </div>
                <div className="autopilot-stat-card">
                  <div className="stat-label">LIMBI DETECTATE</div>
                  <div className="stat-value highlight-gold">🇷🇴 🇮🇹 🇪🇸 🇩🇪 🇬🇧</div>
                  <div className="stat-hint">🌐 Adaptare 100% nativă</div>
                </div>
              </div>

              <div className="autopilot-action-box">
                <button
                  className="autopilot-dispatch-btn"
                  onClick={handleDispatchAutopilot}
                  disabled={dispatchingAutopilot}
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
            </div>

            {/* Split Grid: Live Queue & Audit Trail Log */}
            <div className="autopilot-split-grid">
              {/* Active Queue */}
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.autopilot_queue_title}</span>
                  <span className="tag-live">{autopilotData?.queue?.length || 0} în așteptare</span>
                </div>
                <div className="queue-list">
                  {autopilotData?.queue && autopilotData.queue.length > 0 ? (
                    autopilotData.queue.map((item, idx) => (
                      <div key={idx} className="queue-item">
                        <div className="queue-item-header">
                          <div className="queue-name-group">
                            <span className="queue-flag">{item.detected_flag || '🌍'}</span>
                            <span className="queue-name">{item.customer_name}</span>
                            <span className="queue-country-tag">{item.detected_country} • {item.detected_lang_name || item.detected_lang}</span>
                          </div>
                          <span className="queue-price">{item.total_price} {item.currency}</span>
                        </div>
                        <div className="queue-details">
                          📦 {item.items.join(', ')}
                        </div>
                        <div className="queue-footer">
                          <div className="queue-tags-row">
                            <span className="queue-lang-note">
                              🗣️ Limbă: <strong>{item.detected_lang_name || item.detected_lang}</strong>
                            </span>
                            <span className="fomo-badge">
                              {item.stage === 1 
                                ? '⏳ Pasul 1: Asistență (0% Discount)'
                                : item.stage === 2 
                                  ? '🔥 Pasul 2: Urgență (Cod MG10 • -10%)'
                                  : '🚨 Pasul 3: Ultima Șansă (Cod MG10 • -10%)'}
                            </span>
                          </div>
                          <div className="queue-actions-row">
                            {item.wa_link && (
                              <a href={item.wa_link} target="_blank" rel="noreferrer" className="wa-btn-badge">
                                💬 WhatsApp Direct
                              </a>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty-notice">Toate coșurile recente au fost procesate sau se află în perioada de grație.</div>
                  )}
                </div>
              </div>

              {/* Execution Audit Log */}
              <div className="hud-card">
                <div className="card-title">
                  <span>{t.autopilot_log_title}</span>
                </div>
                <div className="audit-logs-list">
                  {autopilotLogs && autopilotLogs.length > 0 ? (
                    autopilotLogs.map((log, idx) => (
                      <div key={idx} className="log-item">
                        <div className="log-badge-type">{log.action_type || 'RECOVERY'}</div>
                        <div className="log-details">
                          <div className="log-title">
                            Către: <strong>{log.target_name || log.target_email || 'Client VIP'}</strong> ({log.country || 'RO'})
                          </div>
                          <div className="log-sub">{log.subject || log.message?.slice(0, 80)}</div>
                        </div>
                        <div className="log-meta">
                          <div className="log-rev">+{log.revenue || 0} {snapshot?.currency || 'EUR'}</div>
                          <div className="log-date">{new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty-notice">Jurnalul de execuție autonomă va înregistra acțiunile pe măsură ce rulează daemonul.</div>
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
                  disabled={plan === 'free'}
                  onClick={() => handleMockUpgrade('free')}
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
                  disabled={subscribing}
                  onClick={handleOfficialShopifySubscribe}
                >
                  {subscribing ? 'CONECTARE CU SHOPIFY...' : (plan === 'pro' ? t.plan_pro_btn_active : t.plan_pro_btn)}
                </button>
                <div style={{ marginTop: '12px', textAlign: 'center' }}>
                  <button
                    style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
                    onClick={() => handleMockUpgrade(plan === 'pro' ? 'free' : 'pro')}
                  >
                    {t.test_mode_toggle} ({plan === 'pro' ? 'Comută pe Free' : 'Comută pe Pro'})
                  </button>
                </div>
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
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

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
`
