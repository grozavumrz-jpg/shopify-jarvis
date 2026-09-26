import React, { useState, useEffect, useRef } from 'react'

// Multi-language dictionary (English & Romanian)
const I18N = {
  en: {
    brand_sub_pro: 'AUTONOMOUS PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'STORE TELEMETRY CONNECTED',
    voice_active: '🎙️ VOICE: ACTIVE',
    voice_mute: '🔇 VOICE: MUTE',
    upgrade_btn: '⚡ UPGRADE PRO ($9.99/mo)',
    pro_active_badge: '💎 PRO ACTIVE • 7-DAY TRIAL',
    tab_hud: '🪐 TELEMETRY & REPORT',
    tab_chat: '💬 CHAT WITH JARVIS',
    tab_actions: '⚡ 1-CLICK CAMPAIGNS',
    tab_plans: '💎 SUBSCRIPTIONS',
    health_score_label: 'HEALTH SCORE',
    listen_briefing: '🔊 LISTEN TO VOICE BRIEFING',
    stop_voice: '⏹️ STOP VOICE',
    voice_locked_msg: '🔒 Jarvis autonomous voice is available on Pro Plan.',
    unlock_pro: 'Unlock ($9.99)',
    orders_today: 'ORDERS TODAY',
    orders_sub: '▲ Synced in real-time',
    revenue_today: 'REVENUE TODAY',
    revenue_30d: '30 days:',
    abandoned_carts: 'ABANDONED CARTS',
    abandoned_alert: '⚠️ Immediate revenue recovery opportunity',
    abandoned_ok: '✅ Zero lost checkouts',
    new_customers: 'NEW CUSTOMERS (24H)',
    customers_sub: 'Total customer base expanding',
    tactical_plan: '🎯 TACTICAL PLAN FOR TODAY',
    ai_prioritized: 'AI PRIORITIZED',
    analyzing_priorities: 'Jarvis is analyzing store priorities...',
    traffic_strategy: '📈 TRAFFIC STRATEGY & ALERTS',
    daily_growth_tip: 'DAILY GROWTH TACTIC',
    auto_diagnostics: 'AUTOMATED DIAGNOSTICS:',
    store_nominal: 'All store parameters are optimal. No critical anomalies detected.',
    chat_welcome_title: 'Jarvis is ready.',
    chat_welcome_desc: 'I know your catalog, inventory levels, and live orders. Where shall we start accelerating growth today?',
    chip_1: '💡 Why are my sales low today and what can I fix immediately?',
    chip_2: '📱 Write a high-converting video script for my best selling product.',
    chip_3: '🛒 How do I recover the recent abandoned checkouts with a discount?',
    chat_placeholder_free: 'Ask Jarvis ({count} free questions left today)...',
    chat_placeholder_pro: 'Command Jarvis any task regarding your store...',
    chat_send: 'SEND',
    thinking_text: 'Processing store telemetry with Gemini AI...',
    action_tiktok_title: '🎬 Viral 30s TikTok/Reels Script',
    action_tiktok_desc: 'Jarvis writes a 3-step high-converting video script (Visual Hook in first 3s, Core Problem/Solution, and direct CTA) tailored to your catalog.',
    action_email_title: '📧 Magnetic Cart Recovery Email',
    action_email_desc: 'Generates a persuasive abandoned checkout email with subject line, emotional angle, and 10% discount code offer.',
    action_seo_title: '🔍 Conversion & SEO Catalog Audit',
    action_seo_desc: 'Scans your product catalog and rewrites product titles/descriptions to rank higher on Google and convert first-time visitors.',
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
    aov_label: 'AVG ORDER VALUE (AOV)',
    aov_sub: 'Target: >$50 per customer',
    retention_label: 'RETENTION RATE',
    retention_sub: 'Repeat buyers',
    unique_buyers_label: 'TOTAL BUYERS (30D)',
    unique_buyers_sub: 'Unique customer accounts',
    vip_customer_label: 'TOP VIP CUSTOMER',
    action_vip_title: '👑 VIP Loyalty & Repeat Purchase Offer',
    action_vip_desc: 'Identify top spenders and draft an exclusive VIP appreciation reward to trigger high-margin reorders.',
    action_post_title: '📦 3-Day Post-Delivery Review & Upsell',
    action_post_desc: 'Automated 3-day post-delivery sequence requesting photo reviews and recommending a complementary item.',
  },
  ro: {
    brand_sub_pro: 'AUTONOMOUS PRO',
    brand_sub_free: 'OBSERVER MODE',
    telemetry_connected: 'TELEMETRIE CONECTATĂ',
    voice_active: '🎙️ VOCE: ACTIVĂ',
    voice_mute: '🔇 VOCE: MUT',
    upgrade_btn: '⚡ UPGRADE PRO ($9.99/lună)',
    pro_active_badge: '💎 PRO ACTIV • 7 ZILE TRIAL',
    tab_hud: '🪐 TELEMETRIE & RAPORT',
    tab_chat: '💬 DISCUTĂ CU JARVIS',
    tab_actions: '⚡ CAMPANII 1-CLICK',
    tab_plans: '💎 ABONAMENTE',
    health_score_label: 'SCOR SĂNĂTATE',
    listen_briefing: '🔊 ASCULTĂ RAPORTUL VOCAL',
    stop_voice: '⏹️ OPREȘTE VOCEA',
    voice_locked_msg: '🔒 Vocea autonomă Jarvis este disponibilă în Planul Pro.',
    unlock_pro: 'Deblochează ($9.99)',
    orders_today: 'COMENZI ASTĂZI',
    orders_sub: '▲ Sincronizat în timp real',
    revenue_today: 'VENIT ASTĂZI',
    revenue_30d: '30 zile:',
    abandoned_carts: 'COȘURI ABANDONATE',
    abandoned_alert: '⚠️ Oportunitate de recuperare imediată',
    abandoned_ok: '✅ Niciun coș pierdut',
    new_customers: 'CLIENȚI NOI (24H)',
    customers_sub: 'Bază totală în creștere',
    aov_label: 'VALOARE MEDIE COMANDĂ (AOV)',
    aov_sub: 'Țintă: creștere valoare coș',
    retention_label: 'RATĂ DE RETENȚIE',
    retention_sub: 'Clienți care revin',
    unique_buyers_label: 'CUMPĂRĂTORI UNICI (30Z)',
    unique_buyers_sub: 'Conturi unice cumpărători',
    vip_customer_label: 'TOP CLIENT VIP',
    action_vip_title: '👑 Campanie VIP & Fidelizare Clienți',
    action_vip_desc: 'Identifică cumpărătorii de top și generează un email exclusiv cu discount VIP pentru comenzi repetate.',
    action_post_title: '📦 Secvență Post-Cumpărare & Review 5⭐',
    action_post_desc: 'Email trimis la 3 zile după livrare pentru recenzii de 5 stele și vânzare de produse complementare.',
    tactical_plan: '🎯 PLAN TACTIC PENTRU ASTĂZI',
    ai_prioritized: 'PRIORITIZAT AI',
    analyzing_priorities: 'Jarvis analizează prioritățile magazinului...',
    traffic_strategy: '📈 STRATEGIE DE TRAFIC & ALERTE',
    daily_growth_tip: 'SFATUL ZILEI PENTRU VÂNZĂRI',
    auto_diagnostics: 'DIAGNOSTIC AUTOMAT:',
    store_nominal: 'Magazinul funcționează la parametri normali. Nicio anomalie critică.',
    chat_welcome_title: 'Jarvis este pregătit.',
    chat_welcome_desc: 'Cunosc fiecare produs, stocul și comenzile tale. Cu ce începem optimizarea astăzi?',
    chip_1: '💡 De ce nu am vânzări azi și ce pot schimba rapid?',
    chip_2: '📱 Scrie un scenariu video captivant pentru cel mai vândut produs al meu.',
    chip_3: '🛒 Cum recuperez cele mai recente coșuri abandonate?',
    chat_placeholder_free: 'Întreabă-l pe Jarvis ({count} întrebări rămase azi)...',
    chat_placeholder_pro: 'Ordonă-i lui Jarvis orice sarcină legată de magazin...',
    chat_send: 'TRIMITE',
    thinking_text: 'Se procesează telemetria magazinului cu Gemini AI...',
    action_tiktok_title: '🎬 Script Video TikTok / Reels în 3 Pași',
    action_tiktok_desc: 'Jarvis generează un scenariu video cu cârlig psihologic (Hook vizual în primele 3s, Problemă, Soluție și Call To Action) adaptat catalogului tău.',
    action_email_title: '📧 Email Magnetic de Recuperare Coșuri',
    action_email_desc: 'Scrie automat un email cu o rată uriașă de conversie pentru vizitatorii care au părăsit coșul fără să finalizeze comanda.',
    action_seo_title: '🔍 Optimizare Titluri & Descrieri Produse',
    action_seo_desc: 'Analizează catalogul tău de produse și îți rescrie titlurile ca să atragă căutări organice pe Google și să mărească rata de click.',
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
    copied_toast: 'Copiat în clipboard!'
  }
}

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const shop = params.get('shop') || 'maisongrozavu.myshopify.com'

  const [lang, setLang] = useState('en') // 'en' | 'ro'
  const t = I18N[lang]

  const [activeTab, setActiveTab] = useState('hud') // 'hud' | 'chat' | 'actions' | 'plans'
  const [loading, setLoading] = useState(true)
  const [briefing, setBriefing] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [plan, setPlan] = useState('free') // 'free' | 'pro'
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
      } catch (e) {
        console.error('Failed to load Jarvis telemetry', e)
      } finally {
        setLoading(false)
      }
    }
    loadTelemetry()
  }, [shop, lang])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const audioRef = useRef(null)

  const stopSpeaking = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    setIsSpeaking(false)
  }

  // Text-To-Speech Voice Engine (Jarvis Voice)
  const speakText = (text) => {
    if (!voiceEnabled || !text) return
    stopSpeaking()
    setIsSpeaking(true)

    // Clean markdown and special symbols so speech flows naturally
    const cleanText = text.replace(/[*#_`~[\]()]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 320)

    // Use native server-side neural TTS for 100% natural, correct pronunciation in Romanian or English
    const audioUrl = `/api/tts?lang=${encodeURIComponent(lang)}&text=${encodeURIComponent(cleanText)}`
    const audio = new Audio(audioUrl)
    audioRef.current = audio

    audio.onended = () => {
      setIsSpeaking(false)
      audioRef.current = null
    }

    audio.onerror = () => {
      console.warn('Server TTS stream failed, fallback to Web Speech API')
      fallbackSpeechSynthesis(cleanText)
    }

    audio.play().catch(() => {
      fallbackSpeechSynthesis(cleanText)
    })
  }

  const fallbackSpeechSynthesis = (cleanText) => {
    if (!('speechSynthesis' in window)) {
      setIsSpeaking(false)
      return
    }
    const utterance = new SpeechSynthesisUtterance(cleanText)
    utterance.rate = 1.0
    utterance.pitch = 0.95
    utterance.lang = lang === 'ro' ? 'ro-RO' : 'en-US'

    const voices = window.speechSynthesis.getVoices()
    if (lang === 'en') {
      const enVoice = voices.find(v => v.lang.includes('en-GB') || v.lang.includes('en-US'))
      if (enVoice) utterance.voice = enVoice
    } else {
      const roVoice = voices.find(v => v.lang.includes('ro') || v.lang.includes('RO'))
      if (roVoice) utterance.voice = roVoice
    }

    utterance.onstart = () => setIsSpeaking(true)
    utterance.onend = () => setIsSpeaking(false)
    utterance.onerror = () => setIsSpeaking(false)
    window.speechSynthesis.speak(utterance)
  }

  const triggerVoiceBriefing = () => {
    if (plan !== 'pro') {
      setActiveTab('plans')
      return
    }
    const voiceText = briefing?.voice_script || briefing?.summary || (lang === 'ro' ? "Sistemele sunt online. Toate protocoalele funcționează optim." : "Systems are online. All protocols nominal.")
    speakText(voiceText)
  }

  // Handle Chat Submit
  const handleSendMessage = async (customPrompt = null) => {
    const text = (customPrompt || inputMessage).trim()
    if (!text || sendingChat) return

    if (plan === 'free' && freeQuestionsLeft <= 0) {
      setActiveTab('plans')
      return
    }

    if (!customPrompt) setInputMessage('')
    setSendingChat(true)

    const updated = [...chatMessages, { role: 'user', content: text }]
    setChatMessages(updated)

    if (plan === 'free') {
      setFreeQuestionsLeft(prev => Math.max(0, prev - 1))
    }

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, message: text, lang })
      })
      if (!res.ok) throw new Error('AI processing error')
      const data = await res.json()
      setChatMessages([...updated, { role: 'assistant', content: data.reply }])

      if (plan === 'pro' && voiceEnabled) {
        speakText(data.reply.slice(0, 260))
      }
    } catch (err) {
      setChatMessages([...updated, { role: 'assistant', content: `❌ Protocol Error: ${err.message}` }])
    } finally {
      setSendingChat(false)
    }
  }

  // 1-Click Viral Campaign Tools
  const runQuickAction = async (type) => {
    if (plan !== 'pro') {
      setActiveTab('plans')
      return
    }
    setGeneratingAction(true)
    let prompt = ''
    if (type === 'tiktok') {
      prompt = lang === 'ro' 
        ? `Scrie-mi un script complet de TikTok/Reels de 30 secunde pentru cel mai vândut produs din magazin. Include: 1 Hook vizual captivant în primele 3 secunde, Problemă, Soluție și Call To Action direct către magazin.`
        : `Write a viral 30-second TikTok/Reels script for our best-selling product. Include: 1 Visual Hook in the first 3 seconds, relatable Customer Pain Point, Product Solution demonstration, and a strong Call to Action to buy now.`
    } else if (type === 'email_cart') {
      prompt = lang === 'ro'
        ? `Scrie un email irezistibil de recuperare a coșurilor abandonate pentru clienții de azi. Include un subiect cu rată mare de deschidere, ton empatic și o ofertă cu cod de discount 10%.`
        : `Write a high-converting abandoned cart recovery email. Include an attention-grabbing subject line with high open rates, an empathetic tone, urgency, and a 10% discount promo code offer.`
    } else if (type === 'seo_audit') {
      prompt = lang === 'ro'
        ? `Fă un audit rapid de conversie pentru produsele mele și sugerează 3 îmbunătățiri directe de titlu și descriere ca să convingă vizitatorii să cumpere din primul minut.`
        : `Conduct a rapid conversion audit on my store catalog. Recommend 3 direct title and description optimizations to boost click-through rate and compel first-time visitors to purchase.`
    } else if (type === 'vip_reward') {
      prompt = lang === 'ro'
        ? `Analizează clienții fideli și top cumpărătorii magazinului. Scrie un email VIP exclusiv de fidelizare și mulțumire, oferindu-le un beneficiu sau discount secret de 15% VIP, făcându-i să se simtă speciali și stimulând o nouă comandă recurentă de valoare mare.`
        : `Analyze our repeat customers and top spenders. Draft an exclusive VIP loyalty email thanking them, offering a secret 15% VIP incentive, and inspiring a high-margin repeat purchase.`
    } else if (type === 'post_purchase') {
      prompt = lang === 'ro'
        ? `Scrie o secvență automată de email post-cumpărare (trimisă la 3 zile după livrare) pentru clienții noi. Include: mulțumire călduroasă, sfat util de folosire a produsului, cerere prietenoasă de recenzie cu poză de 5 stele și o recomandare atractivă de produs complementar (upsell/cross-sell).`
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
      alert('Generation error: ' + e.message)
    } finally {
      setGeneratingAction(false)
    }
  }

  // Official Shopify Billing API Subscription trigger
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

  // Developer Mock Plan Toggle (instant test)
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
            ? "Protocolul Jarvis Pro a fost activat. Toate sistemele autonome sunt online." 
            : "Jarvis Pro protocol activated. All autonomous systems are online and at your service.")
        }
      }
    } catch (e) {
      console.error(e)
    }
  }

  const toggleTask = (idx) => {
    setCompletedTasks(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  const healthScore = briefing?.health_score || (snapshot ? Math.min(95, 70 + (snapshot.orders_today * 5) - (snapshot.abandoned_carts * 2)) : 85)

  if (loading) {
    return (
      <div className="jarvis-root loading-state">
        <div className="reactor-core pulse-fast">
          <div className="ring ring-1"></div>
          <div className="ring ring-2"></div>
          <div className="core-glow"></div>
        </div>
        <div className="loading-text">INITIALIZING JARVIS TELEMETRY ENGINE...</div>
        <div className="loading-sub">Synchronizing live orders, inventory velocity, and predictive models</div>
        <style>{styles}</style>
      </div>
    )
  }

  return (
    <div className="jarvis-root">
      <style>{styles}</style>

      {/* ── TOP HUD HEADER ── */}
      <header className="hud-header">
        <div className="hud-brand">
          <div className={`reactor-mini ${isSpeaking ? 'speaking' : ''}`}>
            <div className="core-dot"></div>
          </div>
          <div>
            <div className="brand-title">
              JARVIS <span className="brand-badge">{plan === 'pro' ? t.brand_sub_pro : t.brand_sub_free}</span>
            </div>
            <div className="brand-status">
              <span className="live-indicator"></span> {t.telemetry_connected} • {shop}
            </div>
          </div>
        </div>

        <div className="hud-actions">
          {/* Language Switcher */}
          <div className="lang-switcher">
            <button className={`lang-btn ${lang === 'en' ? 'active' : ''}`} onClick={() => setLang('en')}>
              🇺🇸 EN
            </button>
            <button className={`lang-btn ${lang === 'ro' ? 'active' : ''}`} onClick={() => setLang('ro')}>
              🇷🇴 RO
            </button>
          </div>

          {plan === 'pro' && (
            <button
              className={`hud-btn ${voiceEnabled ? 'active' : ''}`}
              onClick={() => {
                if (isSpeaking) window.speechSynthesis.cancel()
                setVoiceEnabled(!voiceEnabled)
              }}
              title="Toggle Jarvis Voice"
            >
              {voiceEnabled ? t.voice_active : t.voice_mute}
            </button>
          )}

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
          <span className="nav-icon">🪐</span> {t.tab_hud}
        </button>
        <button
          className={`nav-item ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          <span className="nav-icon">💬</span> {t.tab_chat}
          {plan === 'free' && <span className="nav-pill">{freeQuestionsLeft} left</span>}
        </button>
        <button
          className={`nav-item ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
        >
          <span className="nav-icon">⚡</span> {t.tab_actions}
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

        {/* ════ TAB 1: HUD & TELEMETRY ════ */}
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
                  <div className="greeting-line">{briefing?.greeting || "Good morning! Jarvis telemetry online."}</div>
                  <div className="summary-text">{briefing?.summary}</div>

                  <div className="hero-buttons">
                    {plan === 'pro' ? (
                      <button className="speak-btn" onClick={triggerVoiceBriefing}>
                        {isSpeaking ? t.stop_voice : t.listen_briefing}
                      </button>
                    ) : (
                      <div className="voice-locked" onClick={() => setActiveTab('plans')}>
                        {t.voice_locked_msg} <span className="link-text">{t.unlock_pro}</span>
                      </div>
                    )}
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
                  {snapshot?.revenue_today || 0} <span className="currency">{snapshot?.currency || 'USD'}</span>
                </div>
                <div className="metric-footer">{t.revenue_30d} {snapshot?.revenue_30d || 0} {snapshot?.currency}</div>
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
                  {snapshot?.aov || 0} <span className="currency">{snapshot?.currency || 'USD'}</span>
                </div>
                <div className="metric-footer highlight-cyan">{t.aov_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.retention_label}</div>
                <div className="metric-value highlight-cyan">
                  {snapshot?.returning_rate || 0}%
                </div>
                <div className="metric-footer">{snapshot?.repeat_customers || 0} {t.retention_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.unique_buyers_label}</div>
                <div className="metric-value">{snapshot?.total_unique_customers || 0}</div>
                <div className="metric-footer">{t.unique_buyers_sub}</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">{t.vip_customer_label}</div>
                <div className="metric-value vip-name">
                  {snapshot?.vip_customers && snapshot.vip_customers[0] ? snapshot.vip_customers[0].name : '—'}
                </div>
                <div className="metric-footer highlight-gold">
                  {snapshot?.vip_customers && snapshot.vip_customers[0] ? `${snapshot.vip_customers[0].total_spent.toFixed(2)} ${snapshot?.currency}` : (lang === 'ro' ? 'Se acumulează date' : 'Aggregating')}
                </div>
              </div>
            </div>

            {/* Tactical Briefing & Daily Action List */}
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
                        <span className="alert-icon">🚨</span>
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

        {/* ════ TAB 2: CHAT WITH JARVIS ════ */}
        {activeTab === 'chat' && (
          <div className="chat-container">
            <div className="chat-stream">
              {chatMessages.length === 0 ? (
                <div className="chat-welcome">
                  <div className="reactor-mini pulse-slow"><div className="core-dot"></div></div>
                  <h3>{t.chat_welcome_title}</h3>
                  <p>{t.chat_welcome_desc}</p>
                  <div className="prompt-chips">
                    <button onClick={() => handleSendMessage(t.chip_1)}>
                      {t.chip_1}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_2)}>
                      {t.chip_2}
                    </button>
                    <button onClick={() => handleSendMessage(t.chip_3)}>
                      {t.chip_3}
                    </button>
                  </div>
                </div>
              ) : (
                chatMessages.map((msg, i) => (
                  <div key={i} className={`chat-bubble ${msg.role}`}>
                    <div className="bubble-header">{msg.role === 'user' ? (lang === 'ro' ? 'TU' : 'YOU') : '🤖 JARVIS'}</div>
                    <div className="bubble-body">{msg.content}</div>
                  </div>
                ))
              )}
              {sendingChat && (
                <div className="chat-bubble assistant thinking">
                  <div className="bubble-header">🤖 JARVIS</div>
                  <div className="thinking-dots">
                    <span></span><span></span><span></span>
                    <em>{t.thinking_text}</em>
                  </div>
                </div>
              )}
              <div ref={chatBottomRef} />
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

        {/* ════ TAB 3: 1-CLICK CAMPAIGN TOOLS (PRO EXCLUSIVE) ════ */}
        {activeTab === 'actions' && (
          <div className="actions-grid">
            <div className="action-card" onClick={() => runQuickAction('tiktok')}>
              <div className="action-badge">VIRAL REELS / TIKTOK</div>
              <h3>{t.action_tiktok_title}</h3>
              <p>{t.action_tiktok_desc}</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? t.action_generating : t.action_trigger}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('email_cart')}>
              <div className="action-badge">REVENUE RECOVERY</div>
              <h3>{t.action_email_title}</h3>
              <p>{t.action_email_desc}</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? t.action_generating : t.action_trigger}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('seo_audit')}>
              <div className="action-badge">CONVERSION AUDIT</div>
              <h3>{t.action_seo_title}</h3>
              <p>{t.action_seo_desc}</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? t.action_generating : t.action_trigger}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('vip_reward')}>
              <div className="action-badge highlight-gold">CUSTOMER RETENTION (VIP)</div>
              <h3>{t.action_vip_title}</h3>
              <p>{t.action_vip_desc}</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? t.action_generating : t.action_trigger}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('post_purchase')}>
              <div className="action-badge">LTV & UPSELL</div>
              <h3>{t.action_post_title}</h3>
              <p>{t.action_post_desc}</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? t.action_generating : t.action_trigger}
              </button>
            </div>

            {generatedOutput && (
              <div className="output-modal">
                <div className="output-box">
                  <div className="output-header">
                    <span>AI OUTPUT: {generatedOutput.title}</span>
                    <button className="close-btn" onClick={() => setGeneratedOutput(null)}>✕</button>
                  </div>
                  <pre className="output-content">{generatedOutput.content}</pre>
                  <button className="copy-btn" onClick={() => {
                    navigator.clipboard.writeText(generatedOutput.content)
                    alert(t.copied_toast)
                  }}>📋 COPY TEXT</button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════ TAB 4: PRICING & OFFICIAL SHOPIFY BILLING ════ */}
        {activeTab === 'plans' && (
          <div className="pricing-container">
            <div className="pricing-title">
              <h2>{t.pricing_title}</h2>
              <p>{t.pricing_sub}</p>
            </div>

            <div className="pricing-cards">
              {/* FREE PLAN */}
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

              {/* PRO PLAN */}
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

                {/* Official Shopify Subscription Button */}
                <button
                  className="plan-btn primary"
                  disabled={subscribing}
                  onClick={handleOfficialShopifySubscribe}
                >
                  {subscribing ? 'CONNECTING SHOPIFY BILLING...' : (plan === 'pro' ? t.plan_pro_btn_active : t.plan_pro_btn)}
                </button>

                {/* Instant Dev Mock Toggle */}
                <div style={{ marginTop: '12px', textAlign: 'center' }}>
                  <button
                    style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
                    onClick={() => handleMockUpgrade(plan === 'pro' ? 'free' : 'pro')}
                  >
                    {t.test_mode_toggle} ({plan === 'pro' ? 'Switch Free' : 'Switch Pro'})
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

// ── CYBERNETIC / FUTURISTIC HUD STYLES ──
const styles = `
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap');

:root {
  --bg-deep: #060911;
  --bg-card: rgba(13, 20, 36, 0.75);
  --border-cyan: rgba(0, 242, 254, 0.25);
  --cyan-glow: #00f2fe;
  --blue-bright: #4facfe;
  --purple-glow: #8b5cf6;
  --green-glow: #10b981;
  --text-main: #f1f5f9;
  --text-dim: #94a3b8;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

.jarvis-root {
  background: var(--bg-deep);
  color: var(--text-main);
  min-height: 100vh;
  font-family: 'Rajdhani', sans-serif;
  letter-spacing: 0.5px;
  background-image: 
    radial-gradient(circle at 10% 20%, rgba(0, 242, 254, 0.04) 0%, transparent 40%),
    radial-gradient(circle at 90% 80%, rgba(139, 92, 246, 0.05) 0%, transparent 40%),
    linear-gradient(rgba(255, 255, 255, 0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.015) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 30px 30px, 30px 30px;
  padding: 20px;
}

.hud-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border-cyan);
  border-radius: 12px;
  margin-bottom: 16px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}

.hud-brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 20px;
  font-weight: 900;
  letter-spacing: 2px;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 20px;
  background: rgba(0, 242, 254, 0.15);
  color: var(--cyan-glow);
  border: 1px solid var(--cyan-glow);
  font-weight: 700;
}

.brand-status {
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.live-indicator {
  width: 8px;
  height: 8px;
  background: var(--green-glow);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--green-glow);
  animation: pulse-dot 1.5s infinite;
}

.hud-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.lang-switcher {
  display: flex;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid var(--border-cyan);
  border-radius: 8px;
  overflow: hidden;
}

.lang-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.lang-btn.active {
  background: var(--cyan-glow);
  color: #000;
}

.hud-btn {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid var(--border-cyan);
  color: var(--cyan-glow);
  padding: 8px 16px;
  border-radius: 8px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.hud-btn.active {
  background: rgba(0, 242, 254, 0.15);
  border-color: var(--cyan-glow);
  box-shadow: 0 0 12px rgba(0, 242, 254, 0.3);
}

.upgrade-glow-btn {
  background: linear-gradient(135deg, #00f2fe, #4facfe);
  color: #000;
  font-family: 'Orbitron', sans-serif;
  font-weight: 900;
  font-size: 12px;
  padding: 10px 18px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 0 18px rgba(0, 242, 254, 0.5);
  transition: transform 0.2s;
}

.upgrade-glow-btn:hover { transform: scale(1.04); }

.pro-active-badge {
  font-size: 12px;
  font-weight: 700;
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 6px 12px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.1);
}

.hud-nav {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.nav-item {
  background: rgba(13, 20, 36, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-dim);
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-item:hover {
  background: rgba(0, 242, 254, 0.08);
  color: #fff;
}

.nav-item.active {
  background: rgba(0, 242, 254, 0.15);
  border-color: var(--cyan-glow);
  color: #fff;
  box-shadow: 0 0 15px rgba(0, 242, 254, 0.2);
}

.nav-pill {
  background: rgba(255, 255, 255, 0.1);
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  color: #fbbf24;
}

.view-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hud-card {
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border-cyan);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}

.hero-card {
  border-color: rgba(0, 242, 254, 0.4);
}

.hero-flex {
  display: flex;
  align-items: center;
  gap: 30px;
}

.hero-info { flex: 1; }

.greeting-line {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 6px;
}

.summary-text {
  font-size: 16px;
  color: var(--text-dim);
  line-height: 1.5;
  margin-bottom: 16px;
}

.speak-btn {
  background: linear-gradient(135deg, rgba(0, 242, 254, 0.2), rgba(79, 172, 254, 0.3));
  border: 1px solid var(--cyan-glow);
  color: var(--cyan-glow);
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 0 15px rgba(0, 242, 254, 0.25);
}

.speak-btn:hover {
  background: var(--cyan-glow);
  color: #000;
}

.voice-locked {
  font-size: 14px;
  color: #cbd5e1;
  cursor: pointer;
}

.voice-locked .link-text {
  color: var(--cyan-glow);
  text-decoration: underline;
  font-weight: 700;
}

.reactor-large-box {
  width: 130px;
  height: 130px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.reactor-core {
  position: relative;
  width: 120px;
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ring {
  position: absolute;
  border-radius: 50%;
  border: 1px dashed var(--cyan-glow);
  animation: spin 10s linear infinite;
}

.ring-1 { width: 100%; height: 100%; border-color: rgba(0, 242, 254, 0.4); }
.ring-2 { width: 80%; height: 80%; border-color: rgba(139, 92, 246, 0.6); animation-direction: reverse; animation-duration: 6s; }
.ring-3 { width: 60%; height: 60%; border-color: rgba(0, 242, 254, 0.8); animation-duration: 4s; }

.core-glow {
  width: 70px;
  height: 70px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 242, 254, 0.4) 0%, rgba(13, 20, 36, 0.9) 80%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 25px rgba(0, 242, 254, 0.6);
}

.health-number {
  font-family: 'Orbitron', sans-serif;
  font-size: 16px;
  font-weight: 900;
  color: #fff;
}

.health-label {
  font-size: 8px;
  color: var(--cyan-glow);
  font-weight: 700;
}

.reactor-mini {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px dashed var(--cyan-glow);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: spin 8s linear infinite;
}

.core-dot {
  width: 12px;
  height: 12px;
  background: var(--cyan-glow);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--cyan-glow);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 16px;
  transition: transform 0.2s, border-color 0.2s;
}

.metric-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-cyan);
}

.metric-card.alert-border {
  border-color: rgba(239, 68, 68, 0.4);
}

.metric-header {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  letter-spacing: 1px;
}

.metric-value {
  font-family: 'Orbitron', sans-serif;
  font-size: 26px;
  font-weight: 900;
  color: #fff;
  margin: 6px 0;
}

.metric-value.critical { color: #f87171; }
.metric-value .currency { font-size: 14px; color: var(--cyan-glow); }

.metric-footer {
  font-size: 12px;
  color: var(--text-dim);
}

.highlight-green { color: var(--green-glow); }
.highlight-orange { color: #fb923c; }
.highlight-cyan { color: var(--cyan-glow); }
.highlight-gold { color: #f59e0b; font-weight: 700; }
.vip-name { font-size: 16px !important; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
.customer-row { margin-top: -4px; margin-bottom: 20px; }

.two-columns {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
}

.card-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 14px;
  font-weight: 900;
  letter-spacing: 1px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.tag-live {
  font-size: 9px;
  background: rgba(0, 242, 254, 0.15);
  color: var(--cyan-glow);
  padding: 2px 6px;
  border-radius: 4px;
}

.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: rgba(15, 23, 42, 0.6);
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  transition: all 0.2s;
}

.task-item:hover { border-color: var(--border-cyan); }
.task-item.done { opacity: 0.5; text-decoration: line-through; }
.task-item input { margin-top: 4px; accent-color: var(--cyan-glow); cursor: pointer; }

.task-title { font-weight: 700; color: #fff; font-size: 15px; }
.task-why { font-size: 13px; color: var(--text-dim); margin-top: 2px; }

.traffic-box {
  background: rgba(0, 242, 254, 0.05);
  border: 1px solid rgba(0, 242, 254, 0.2);
  padding: 14px;
  border-radius: 8px;
  margin-bottom: 14px;
}

.traffic-tag {
  font-size: 11px;
  font-weight: 700;
  color: var(--cyan-glow);
  margin-bottom: 4px;
}

.traffic-desc { font-size: 14px; color: #e2e8f0; line-height: 1.4; }

.box-subtitle {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 700;
  margin-bottom: 8px;
}

.alert-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: rgba(239, 68, 68, 0.08);
  border-left: 3px solid #ef4444;
  border-radius: 4px;
  font-size: 13px;
  margin-bottom: 8px;
}

.alert-item.green {
  background: rgba(16, 185, 129, 0.08);
  border-left-color: var(--green-glow);
}

.alert-action { color: var(--text-dim); margin-top: 2px; }

.chat-container {
  display: flex;
  flex-direction: column;
  height: 600px;
  background: var(--bg-card);
  border: 1px solid var(--border-cyan);
  border-radius: 12px;
  overflow: hidden;
}

.chat-stream {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-welcome {
  text-align: center;
  margin: auto;
  max-width: 480px;
}

.chat-welcome h3 {
  font-family: 'Orbitron', sans-serif;
  font-size: 20px;
  margin: 12px 0 6px;
  color: #fff;
}

.chat-welcome p { color: var(--text-dim); font-size: 15px; margin-bottom: 20px; }

.prompt-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prompt-chips button {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(0, 242, 254, 0.2);
  color: #e2e8f0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s;
}

.prompt-chips button:hover {
  border-color: var(--cyan-glow);
  background: rgba(0, 242, 254, 0.1);
}

.chat-bubble {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 10px;
  line-height: 1.5;
}

.chat-bubble.user {
  align-self: flex-end;
  background: linear-gradient(135deg, rgba(0, 242, 254, 0.2), rgba(79, 172, 254, 0.2));
  border: 1px solid rgba(0, 242, 254, 0.4);
  color: #fff;
}

.chat-bubble.assistant {
  align-self: flex-start;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
}

.bubble-header {
  font-size: 10px;
  font-weight: 700;
  color: var(--cyan-glow);
  margin-bottom: 6px;
}

.bubble-body {
  white-space: pre-wrap;
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}

.chat-input-bar {
  display: flex;
  padding: 14px;
  background: rgba(9, 13, 22, 0.9);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  gap: 10px;
}

.chat-input-bar input {
  flex: 1;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #fff;
  padding: 12px 16px;
  border-radius: 8px;
  font-family: inherit;
  font-size: 15px;
  outline: none;
}

.chat-input-bar input:focus {
  border-color: var(--cyan-glow);
}

.send-btn {
  background: var(--cyan-glow);
  color: #000;
  font-family: 'Orbitron', sans-serif;
  font-weight: 900;
  border: none;
  border-radius: 8px;
  padding: 0 24px;
  cursor: pointer;
  transition: transform 0.2s;
}

.send-btn:hover { transform: scale(1.03); }

.actions-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.action-card {
  background: var(--bg-card);
  border: 1px solid var(--border-cyan);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 240px;
  transition: all 0.2s;
}

.action-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 6px 25px rgba(0, 242, 254, 0.2);
  border-color: var(--cyan-glow);
}

.action-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--cyan-glow);
  letter-spacing: 1px;
}

.action-card h3 {
  font-family: 'Orbitron', sans-serif;
  font-size: 18px;
  color: #fff;
  margin: 10px 0 6px;
}

.action-card p {
  font-size: 14px;
  color: var(--text-dim);
  line-height: 1.4;
  flex: 1;
}

.action-trigger-btn {
  background: rgba(0, 242, 254, 0.1);
  border: 1px solid var(--cyan-glow);
  color: var(--cyan-glow);
  font-weight: 700;
  padding: 10px;
  border-radius: 6px;
  margin-top: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-trigger-btn:hover {
  background: var(--cyan-glow);
  color: #000;
}

.output-modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.output-box {
  background: #0d1424;
  border: 1px solid var(--cyan-glow);
  width: 600px;
  max-width: 90%;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 0 40px rgba(0, 242, 254, 0.4);
}

.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'Orbitron', sans-serif;
  font-weight: 900;
  color: var(--cyan-glow);
  margin-bottom: 14px;
}

.close-btn {
  background: none;
  border: none;
  color: #fff;
  font-size: 18px;
  cursor: pointer;
}

.output-content {
  background: #060911;
  border: 1px solid rgba(255,255,255,0.08);
  padding: 16px;
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  color: #e2e8f0;
  white-space: pre-wrap;
  max-height: 350px;
  overflow-y: auto;
  line-height: 1.5;
  margin-bottom: 16px;
}

.copy-btn {
  width: 100%;
  background: var(--cyan-glow);
  color: #000;
  font-weight: 900;
  padding: 12px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}

.pricing-container {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px 0;
}

.pricing-title {
  text-align: center;
  margin-bottom: 30px;
}

.pricing-title h2 {
  font-family: 'Orbitron', sans-serif;
  font-size: 24px;
  color: #fff;
  letter-spacing: 1px;
}

.pricing-title p {
  color: var(--text-dim);
  margin-top: 6px;
  font-size: 15px;
}

.pricing-cards {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 20px;
  align-items: center;
}

.pricing-card {
  background: var(--bg-card);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 26px;
}

.pricing-card.pro {
  border-color: var(--cyan-glow);
  box-shadow: 0 0 30px rgba(0, 242, 254, 0.25);
  background: linear-gradient(180deg, rgba(13, 20, 36, 0.95), rgba(9, 13, 22, 0.95));
}

.plan-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 8px;
}

.plan-badge.hot {
  color: #fbbf24;
}

.pricing-card h3 {
  font-family: 'Orbitron', sans-serif;
  font-size: 20px;
  color: #fff;
}

.price-tag {
  font-family: 'Orbitron', sans-serif;
  font-size: 32px;
  font-weight: 900;
  color: var(--cyan-glow);
  margin: 12px 0;
}

.price-tag span {
  font-size: 13px;
  color: var(--text-dim);
  font-family: 'Rajdhani', sans-serif;
}

.plan-desc {
  font-size: 14px;
  color: var(--text-dim);
  margin-bottom: 16px;
  line-height: 1.4;
}

.plan-perks {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 14px;
  margin-bottom: 24px;
}

.plan-perks li.dim {
  color: #64748b;
}

.plan-btn {
  width: 100%;
  padding: 14px;
  border-radius: 8px;
  font-family: 'Orbitron', sans-serif;
  font-weight: 900;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.plan-btn.primary {
  background: linear-gradient(135deg, #00f2fe, #4facfe);
  color: #000;
  border: none;
  box-shadow: 0 0 20px rgba(0, 242, 254, 0.4);
}

.plan-btn.primary:hover {
  transform: scale(1.02);
}

.plan-btn.secondary {
  background: transparent;
  border: 1px solid rgba(255,255,255,0.2);
  color: #fff;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.pulse-speaking {
  animation: reactor-speak 0.8s infinite alternate;
}

@keyframes reactor-speak {
  from { transform: scale(1); filter: drop-shadow(0 0 10px var(--cyan-glow)); }
  to { transform: scale(1.08); filter: drop-shadow(0 0 30px var(--cyan-glow)); }
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 80vh;
}

.loading-text {
  font-family: 'Orbitron', sans-serif;
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 2px;
  color: var(--cyan-glow);
  margin-top: 24px;
}

.loading-sub {
  color: var(--text-dim);
  font-size: 14px;
  margin-top: 6px;
}
`
