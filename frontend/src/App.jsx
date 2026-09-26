import React, { useState, useEffect, useRef } from 'react'

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const shop = params.get('shop') || 'maisongrozavu.myshopify.com'

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

  // 1-Click Generator Output Modal/Drawer
  const [generatedOutput, setGeneratedOutput] = useState(null)
  const [generatingAction, setGeneratingAction] = useState(false)

  // Initialize and Fetch Store Telemetry
  useEffect(() => {
    async function initJarvis() {
      setLoading(true)
      try {
        const res = await fetch(`/api/briefing?shop=${encodeURIComponent(shop)}`)
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
    initJarvis()
  }, [shop])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // Text-To-Speech Voice Engine (Jarvis Voice)
  const speakText = (text) => {
    if (!('speechSynthesis' in window) || !voiceEnabled) return
    window.speechSynthesis.cancel()

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'ro-RO'
    utterance.rate = 1.05
    utterance.pitch = 0.95 // slightly deeper, confident Jarvis tone

    // Try finding a Romanian or British voice
    const voices = window.speechSynthesis.getVoices()
    const roVoice = voices.find(v => v.lang.includes('ro') || v.lang.includes('RO'))
    if (roVoice) utterance.voice = roVoice

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
    const voiceText = briefing?.voice_script || briefing?.summary || "Sistemele sunt online. Toate protocoalele funcționează optim."
    speakText(voiceText)
  }

  // Handle Chat Submit
  const handleSendMessage = async (customPrompt = null) => {
    const text = (customPrompt || inputMessage).trim()
    if (!text || sendingChat) return

    // Free plan usage limit check
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
        body: JSON.stringify({ shop, message: text })
      })
      if (!res.ok) throw new Error('Eroare de procesare neurală')
      const data = await res.json()
      setChatMessages([...updated, { role: 'assistant', content: data.reply }])

      // If user is Pro and voice is enabled, speak the answer
      if (plan === 'pro' && voiceEnabled) {
        speakText(data.reply.slice(0, 280)) // speak first 2 sentences
      }
    } catch (err) {
      setChatMessages([...updated, { role: 'assistant', content: `❌ Protocol întrerupt: ${err.message}` }])
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
      prompt = `Scrie-mi un script complet de TikTok/Reels de 30 secunde pentru cel mai vândut produs din magazin. Include: 1 Hook vizual captivant în primele 3 secunde, Problemă, Soluție și Call To Action direct către magazin.`
    } else if (type === 'email_cart') {
      prompt = `Scrie un email irezistibil de recuperare a coșurilor abandonate pentru clienții de azi. Include un subiect cu rată mare de deschidere, ton empatic și o ofertă cu cod de discount 10%.`
    } else if (type === 'seo_audit') {
      prompt = `Fă un audit rapid de conversie pentru produsele mele și sugerează 3 îmbunătățiri directe de titlu și descriere ca să convingă vizitatorii să cumpere din primul minut.`
    }

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, message: prompt })
      })
      const data = await res.json()
      setGeneratedOutput({ title: type.toUpperCase(), content: data.reply })
    } catch (e) {
      alert('Eroare la generare: ' + e.message)
    } finally {
      setGeneratingAction(false)
    }
  }

  // Upgrade or Switch Plan
  const handleUpgrade = async (targetPlan) => {
    try {
      const res = await fetch('/api/plan/upgrade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, plan: targetPlan })
      })
      if (res.ok) {
        setPlan(targetPlan)
        if (targetPlan === 'pro') {
          speakText("Protocolul Jarvis Pro a fost activat cu succes. Toate sistemele autonome sunt la dispoziția dumneavoastră.")
        }
      }
    } catch (e) {
      console.error(e)
    }
  }

  const toggleTask = (idx) => {
    setCompletedTasks(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  const healthScore = briefing?.health_score || (snapshot ? Math.min(95, 70 + (snapshot.orders_today * 5) - (snapshot.abandoned_carts * 2)) : 84)

  if (loading) {
    return (
      <div className="jarvis-root loading-state">
        <div className="reactor-core pulse-fast">
          <div className="ring ring-1"></div>
          <div className="ring ring-2"></div>
          <div className="core-glow"></div>
        </div>
        <div className="loading-text">INIȚIALIZARE PROTOCOL JARVIS TELEMETRY...</div>
        <div className="loading-sub">Sincronizare comenzi, produse și analiză predictivă</div>
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
              JARVIS <span className="brand-badge">{plan === 'pro' ? 'AUTONOMOUS PRO' : 'OBSERVER MODE'}</span>
            </div>
            <div className="brand-status">
              <span className="live-indicator"></span> TELEMETRIE CONECTATĂ • {shop}
            </div>
          </div>
        </div>

        <div className="hud-actions">
          {plan === 'pro' && (
            <button
              className={`hud-btn ${voiceEnabled ? 'active' : ''}`}
              onClick={() => {
                if (isSpeaking) window.speechSynthesis.cancel()
                setVoiceEnabled(!voiceEnabled)
              }}
              title="Comutator Voce Jarvis"
            >
              {voiceEnabled ? '🎙️ VOCE: ACTIVĂ' : '🔇 VOCE: MUT'}
            </button>
          )}

          {plan === 'free' ? (
            <button className="upgrade-glow-btn" onClick={() => setActiveTab('plans')}>
              ⚡ UPGRADE PRO ($9.99/lună)
            </button>
          ) : (
            <div className="pro-active-badge">
              💎 PRO ACTIV • 7 ZILE TRIAL
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
          <span className="nav-icon">🪐</span> TELEMETRIE & RAPORT
        </button>
        <button
          className={`nav-item ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          <span className="nav-icon">💬</span> DISCUTĂ CU JARVIS
          {plan === 'free' && <span className="nav-pill">{freeQuestionsLeft} libere</span>}
        </button>
        <button
          className={`nav-item ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
        >
          <span className="nav-icon">⚡</span> CAMPANII 1-CLICK
        </button>
        <button
          className={`nav-item ${activeTab === 'plans' ? 'active' : ''}`}
          onClick={() => setActiveTab('plans')}
        >
          <span className="nav-icon">💎</span> ABONAMENTE
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
                      <div className="health-label">SCOR SĂNĂTATE</div>
                    </div>
                  </div>
                </div>

                <div className="hero-info">
                  <div className="greeting-line">{briefing?.greeting || "Sistemele sunt online, domnule Grozavu."}</div>
                  <div className="summary-text">{briefing?.summary}</div>

                  <div className="hero-buttons">
                    {plan === 'pro' ? (
                      <button className="speak-btn" onClick={triggerVoiceBriefing}>
                        {isSpeaking ? '⏹️ OPREȘTE VOCEA' : '🔊 ASCULTĂ BRIEFINGUL VOCAL'}
                      </button>
                    ) : (
                      <div className="voice-locked" onClick={() => setActiveTab('plans')}>
                        🔒 Vocea autonomă Jarvis este disponibilă în Planul Pro. <span className="link-text">Deblochează ($9.99)</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Live Metrics Grid */}
            <div className="metrics-row">
              <div className="metric-card">
                <div className="metric-header">COMENZI ASTĂZI</div>
                <div className="metric-value">{snapshot?.orders_today || 0}</div>
                <div className="metric-footer highlight-green">▲ Sincronizat în timp real</div>
              </div>

              <div className="metric-card">
                <div className="metric-header">VENIT ASTĂZI</div>
                <div className="metric-value">
                  {snapshot?.revenue_today || 0} <span className="currency">{snapshot?.currency || 'USD'}</span>
                </div>
                <div className="metric-footer">30 zile: {snapshot?.revenue_30d || 0} {snapshot?.currency}</div>
              </div>

              <div className="metric-card alert-border">
                <div className="metric-header">COȘURI ABANDONATE</div>
                <div className="metric-value critical">{snapshot?.abandoned_carts || 0}</div>
                <div className="metric-footer highlight-orange">
                  {snapshot?.abandoned_carts > 0 ? '⚠️ Oportunitate de recuperare imediată' : '✅ Niciun coș pierdut'}
                </div>
              </div>

              <div className="metric-card">
                <div className="metric-header">CLIENȚI NOI (24H)</div>
                <div className="metric-value">{snapshot?.new_customers_24h || 0}</div>
                <div className="metric-footer">Bază totală în creștere</div>
              </div>
            </div>

            {/* Tactical Briefing & Daily Action List */}
            <div className="two-columns">
              <div className="hud-card">
                <div className="card-title">
                  <span>🎯 PLAN TACTIC PENTRU ASTĂZI</span>
                  <span className="tag-live">PRIORITIZAT AI</span>
                </div>
                <div className="tasks-list">
                  {briefing?.top_tasks && briefing.top_tasks.length > 0 ? (
                    briefing.top_tasks.map((task, i) => (
                      <div key={i} className={`task-item ${completedTasks[i] ? 'done' : ''}`} onClick={() => toggleTask(i)}>
                        <input type="checkbox" checked={!!completedTasks[i]} readOnly />
                        <div className="task-content">
                          <div className="task-title">
                            {task.icon || '📌'} Prioritate {task.priority}: {task.task}
                          </div>
                          <div className="task-why">{task.why}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty-notice">Jarvis analizează prioritățile magazinului...</div>
                  )}
                </div>
              </div>

              {/* Traffic Advice & Smart Alerts */}
              <div className="hud-card">
                <div className="card-title">
                  <span>📈 STRATEGIE DE TRAFIC & ALERTE</span>
                </div>

                {briefing?.traffic_tip && (
                  <div className="traffic-box">
                    <div className="traffic-tag">SFATUL ZILEI PENTRU VÂNZĂRI</div>
                    <div className="traffic-desc">{briefing.traffic_tip}</div>
                  </div>
                )}

                <div className="alerts-box">
                  <div className="box-subtitle">DIAGNOSTIC AUTOMAT:</div>
                  {briefing?.alerts && briefing.alerts.length > 0 ? (
                    briefing.alerts.map((al, idx) => (
                      <div key={idx} className="alert-item">
                        <span className="alert-icon">🚨</span>
                        <div>
                          <strong>{al.message}</strong>
                          <div className="alert-action">Acțiune recomandată: {al.action}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="alert-item green">
                      <span className="alert-icon">🛡️</span>
                      <div>Magazinul funcționează la parametri normali. Nicio anomalie critică.</div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ════ TAB 2: CHAT CU JARVIS ════ */}
        {activeTab === 'chat' && (
          <div className="chat-container">
            <div className="chat-stream">
              {chatMessages.length === 0 ? (
                <div className="chat-welcome">
                  <div className="reactor-mini pulse-slow"><div className="core-dot"></div></div>
                  <h3>Jarvis este pregătit.</h3>
                  <p>
                    Cunosc fiecare produs, stocul și comenzile tale. Cu ce începem optimizarea astăzi?
                  </p>
                  <div className="prompt-chips">
                    <button onClick={() => handleSendMessage("De ce nu am suficiente vânzări azi și ce pot schimba rapid?")}>
                      💡 De ce nu am vânzări azi?
                    </button>
                    <button onClick={() => handleSendMessage("Scrie un text persuasiv de reclamă pentru cel mai vândut produs al meu.")}>
                      📱 Scrie o reclamă persuasivă
                    </button>
                    <button onClick={() => handleSendMessage("Cum recuperez cele mai recente coșuri abandonate?")}>
                      🛒 Cum recuperez coșurile abandonate?
                    </button>
                  </div>
                </div>
              ) : (
                chatMessages.map((msg, i) => (
                  <div key={i} className={`chat-bubble ${msg.role}`}>
                    <div className="bubble-header">{msg.role === 'user' ? 'TU' : '🤖 JARVIS'}</div>
                    <div className="bubble-body">{msg.content}</div>
                  </div>
                ))
              )}
              {sendingChat && (
                <div className="chat-bubble assistant thinking">
                  <div className="bubble-header">🤖 JARVIS</div>
                  <div className="thinking-dots">
                    <span></span><span></span><span></span>
                    <em>Se procesează telemetria magazinului...</em>
                  </div>
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            <div className="chat-input-bar">
              <input
                type="text"
                placeholder={plan === 'free' ? `Întreabă-l pe Jarvis (${freeQuestionsLeft} întrebări rămase azi)...` : "Ordonă-i lui Jarvis orice sarcină legată de magazin..."}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              />
              <button className="send-btn" onClick={() => handleSendMessage()} disabled={sendingChat}>
                TRIMITE
              </button>
            </div>
          </div>
        )}

        {/* ════ TAB 3: 1-CLICK CAMPAIGN TOOLS (PRO EXCLUSIVE) ════ */}
        {activeTab === 'actions' && (
          <div className="actions-grid">
            <div className="action-card" onClick={() => runQuickAction('tiktok')}>
              <div className="action-badge">VIRAL REELS / TIKTOK</div>
              <h3>🎬 Script Video în 3 Pași</h3>
              <p>Jarvis generează un scenariu video cu cârlig psihologic (Hook, Demonstrație și Îndemn la cumpărare) pentru produsele tale.</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? 'GENERARE ÎN CURS...' : 'GENEREAZĂ SCRIPT ACUM →'}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('email_cart')}>
              <div className="action-badge">RECUPERARE COȘURI</div>
              <h3>📧 Email Magnetic de Recuperare</h3>
              <p>Scrie automat un email cu o rată uriașă de conversie pentru vizitatorii care au părăsit coșul de cumpărături fără să plătească.</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? 'GENERARE ÎN CURS...' : 'CREEAZĂ EMAIL COȘ →'}
              </button>
            </div>

            <div className="action-card" onClick={() => runQuickAction('seo_audit')}>
              <div className="action-badge">AUDIT CONVERSIE</div>
              <h3>🔍 Optimizare Titluri & Descrieri</h3>
              <p>Analizează catalogul tău de produse și îți rescrie titlurile ca să atragă căutări organice pe Google și să mărească rata de click.</p>
              <button className="action-trigger-btn" disabled={generatingAction}>
                {generatingAction ? 'GENERARE ÎN CURS...' : 'OPTIMIZEAZĂ CATALOGUL →'}
              </button>
            </div>

            {generatedOutput && (
              <div className="output-modal">
                <div className="output-box">
                  <div className="output-header">
                    <span>REZULTAT GENERAT: {generatedOutput.title}</span>
                    <button className="close-btn" onClick={() => setGeneratedOutput(null)}>✕</button>
                  </div>
                  <pre className="output-content">{generatedOutput.content}</pre>
                  <button className="copy-btn" onClick={() => {
                    navigator.clipboard.writeText(generatedOutput.content)
                    alert('Copiat în clipboard!')
                  }}>📋 COPIAZĂ TEXTUL</button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ════ TAB 4: PRICING & SUBSCRIPTIONS ════ */}
        {activeTab === 'plans' && (
          <div className="pricing-container">
            <div className="pricing-title">
              <h2>ALEGE NIVELUL DE INTELIGENȚĂ PENTRU MAGAZINUL TĂU</h2>
              <p>Fără angajați scumpi. Jarvis este cofondatorul tău tehnic și de marketing disponibil 24/7.</p>
            </div>

            <div className="pricing-cards">
              {/* PLAN GRATUIT */}
              <div className={`pricing-card ${plan === 'free' ? 'current' : ''}`}>
                <div className="plan-badge">PLANUL DE BAZĂ</div>
                <h3>Observer Mode</h3>
                <div className="price-tag">$0 <span>/ pentru totdeauna</span></div>
                <p className="plan-desc">Monitorizează comenzile și oferă o perspectivă generală asupra cifrelor magazinului.</p>
                <ul className="plan-perks">
                  <li>✔ Dashboard de bază cu vânzări și comenzi</li>
                  <li>✔ 3 întrebări manuale pe zi în chat</li>
                  <li>✔ Raport text la cerere</li>
                  <li className="dim">✖ Fără voce audio autonomă</li>
                  <li className="dim">✖ Fără generatoare automate de campanii</li>
                  <li className="dim">✖ Fără alerte proactive de coșuri abandonate</li>
                </ul>
                <button
                  className="plan-btn secondary"
                  disabled={plan === 'free'}
                  onClick={() => handleUpgrade('free')}
                >
                  {plan === 'free' ? 'PLAN ACTIV' : 'TRECI PE GRATUIT'}
                </button>
              </div>

              {/* PLAN PLATIT */}
              <div className={`pricing-card pro ${plan === 'pro' ? 'current' : ''}`}>
                <div className="plan-badge hot">RECOMANDAT PENTRU VÂNZĂRI</div>
                <h3>Jarvis Autonomous Pro</h3>
                <div className="price-tag">$9.99 <span>/ lună (Trial 7 zile inclus)</span></div>
                <p className="plan-desc">Asistentul complet cu voce, predicții în timp real și generare automată de conținut de vânzare.</p>
                <ul className="plan-perks">
                  <li>⭐ <strong>Jarvis Vorbește cu Tine:</strong> Raport vocal zilnic sintetic</li>
                  <li>⭐ <strong>Chat AI Nelimitat:</strong> Fără limite de întrebări</li>
                  <li>⭐ <strong>Campanii 1-Click:</strong> Scripturi TikTok virale & emailuri</li>
                  <li>⭐ <strong>Alerte Proactive:</strong> Te anunță imediat când apar coșuri abandonate</li>
                  <li>⭐ <strong>Store Health Score:</strong> Audit continuu al conversiei magazinului</li>
                  <li>⭐ <strong>Prioritizare Tactică Zilnică</strong></li>
                </ul>
                <button
                  className="plan-btn primary"
                  onClick={() => handleUpgrade('pro')}
                >
                  {plan === 'pro' ? 'PLAN PRO ACTIVAT (TRIAL 7 ZILE)' : '⚡ ACTIVEAZĂ JARVIS PRO ($9.99/lună)'}
                </button>
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

/* Header */
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

/* Nav */
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

/* Cards & Grid */
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

/* Reactor Core Graphic */
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

/* Metrics Row */
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

/* 2 Columns Section */
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

/* Chat Container */
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
  margin-bottom: 4px;
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

/* 1-Click Action Grid */
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

/* Modal Output */
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

/* Pricing Page */
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

/* Animations */
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
