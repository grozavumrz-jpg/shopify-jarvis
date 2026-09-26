import React, { useState, useEffect, useRef } from 'react'
import {
  Page,
  Layout,
  Card,
  Text,
  Badge,
  Button,
  TextField,
  Banner,
  BlockStack,
  InlineStack,
  Divider,
  Tabs,
  Box,
  Spinner,
  List,
  Checkbox
} from '@shopify/polaris'

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const shop = params.get('shop') || 'demo.myshopify.com'

  const [selectedTab, setSelectedTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [briefingData, setBriefingData] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState(null)

  // Chat state
  const [chatMessages, setChatMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [sendingChat, setSendingChat] = useState(false)
  const chatBottomRef = useRef(null)

  // Tasks state
  const [completedTasks, setCompletedTasks] = useState({})

  const tabs = [
    { id: 'dashboard', content: '📊 Briefing & Cifre' },
    { id: 'chat', content: '💬 Discută cu Jarvis' },
    { id: 'tasks', content: '🎯 Sarcini Recomandate' },
    { id: 'subscription', content: '💎 Abonament ($9.99/lună)' }
  ]

  // Load initial store data and briefing
  useEffect(() => {
    async function loadData() {
      setLoading(true)
      try {
        const res = await fetch(`/api/briefing?shop=${encodeURIComponent(shop)}`)
        if (!res.ok) {
          throw new Error('Eroare la obținerea datelor de la server.')
        }
        const data = await res.json()
        setBriefingData(data.briefing)
        if (data.snapshot) setSnapshot(data.snapshot)

        // Load chat history
        const histRes = await fetch(`/api/history?shop=${encodeURIComponent(shop)}`)
        if (histRes.ok) {
          const hist = await histRes.json()
          setChatMessages(hist)
        }
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [shop])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || sendingChat) return
    const msg = inputMessage.trim()
    setInputMessage('')
    setSendingChat(true)

    // Optimistic user message
    const newHistory = [...chatMessages, { role: 'user', content: msg }]
    setChatMessages(newHistory)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, message: msg })
      })
      if (!res.ok) throw new Error('Eroare la comunicarea cu Jarvis.')
      const data = await res.json()
      setChatMessages([...newHistory, { role: 'assistant', content: data.reply }])
    } catch (err) {
      setChatMessages([
        ...newHistory,
        { role: 'assistant', content: `❌ Nu am putut genera răspunsul: ${err.message}` }
      ])
    } finally {
      setSendingChat(false)
    }
  }

  const toggleTask = (index) => {
    setCompletedTasks((prev) => ({
      ...prev,
      [index]: !prev[index]
    }))
  }

  if (loading) {
    return (
      <Page title="Jarvis - Asistentul tău Shopify">
        <Box padding="800">
          <BlockStack align="center" inlineAlign="center" gap="400">
            <Spinner accessibilityLabel="Se încarcă datele magazinului" size="large" />
            <Text variant="bodyLg" as="p">
              Jarvis analizează comenzile, produsele și traficul din magazinul tău...
            </Text>
          </BlockStack>
        </Box>
      </Page>
    )
  }

  return (
    <Page
      title="🧠 Jarvis — Partenerul Tău de Creștere"
      subtitle={`Conectat la: ${shop}`}
      compactTitle
      primaryAction={{
        content: 'Reîmprospătează datele',
        onAction: () => window.location.reload()
      }}
    >
      <BlockStack gap="400">
        {error && (
          <Banner title="Atenție la conexiune" tone="warning">
            <p>{error}</p>
          </Banner>
        )}

        <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
          <Box paddingBlockStart="400">
            {/* ── TAB 1: BRIEFING & CIFRE ── */}
            {selectedTab === 0 && (
              <Layout>
                {briefingData && (
                  <Layout.Section>
                    <Banner
                      title={briefingData.greeting || 'Salutare! Să facem magazinul să vândă!'}
                      tone="info"
                    >
                      <p style={{ marginTop: '4px', fontSize: '15px' }}>
                        {briefingData.summary}
                      </p>
                      {briefingData.motivation && (
                        <p style={{ marginTop: '8px', fontStyle: 'italic', color: '#5c6ac4' }}>
                          „{briefingData.motivation}”
                        </p>
                      )}
                    </Banner>
                  </Layout.Section>
                )}

                {/* Cifre Cheie */}
                {snapshot && (
                  <Layout.Section>
                    <Card>
                      <BlockStack gap="300">
                        <Text variant="headingMd" as="h2">
                          📈 Performanță Magazin
                        </Text>
                        <Divider />
                        <InlineStack gap="400" align="space-between">
                          <Box>
                            <Text variant="bodySm" tone="subdued" as="p">Comenzi Azi</Text>
                            <Text variant="headingLg" as="p">{snapshot.orders_today}</Text>
                          </Box>
                          <Box>
                            <Text variant="bodySm" tone="subdued" as="p">Venit Azi</Text>
                            <Text variant="headingLg" as="p">
                              {snapshot.revenue_today} {snapshot.currency}
                            </Text>
                          </Box>
                          <Box>
                            <Text variant="bodySm" tone="subdued" as="p">Venit 30 Zile</Text>
                            <Text variant="headingLg" as="p">
                              {snapshot.revenue_30d} {snapshot.currency}
                            </Text>
                          </Box>
                          <Box>
                            <Text variant="bodySm" tone="subdued" as="p">Coșuri Abandonate</Text>
                            <Text variant="headingLg" as="p" tone={snapshot.abandoned_carts > 0 ? "critical" : "base"}>
                              {snapshot.abandoned_carts}
                            </Text>
                          </Box>
                        </InlineStack>
                      </BlockStack>
                    </Card>
                  </Layout.Section>
                )}

                {/* Sfatul de Trafic */}
                {briefingData?.traffic_tip && (
                  <Layout.Section>
                    <Card background="bg-surface-secondary">
                      <BlockStack gap="200">
                        <InlineStack gap="200" align="start">
                          <Badge tone="success">Sfatul Zilei pentru Trafic</Badge>
                        </InlineStack>
                        <Text variant="bodyMd" as="p">
                          {briefingData.traffic_tip}
                        </Text>
                      </BlockStack>
                    </Card>
                  </Layout.Section>
                )}

                {/* Alerte Inteligente */}
                {briefingData?.alerts && briefingData.alerts.length > 0 && (
                  <Layout.Section>
                    <Card>
                      <BlockStack gap="300">
                        <Text variant="headingMd" as="h2">🚨 Alerte & Oportunități Imediate</Text>
                        <Divider />
                        <List type="bullet">
                          {briefingData.alerts.map((al, idx) => (
                            <List.Item key={idx}>
                              <strong>{al.message}</strong> — Recomandare: {al.action}
                            </List.Item>
                          ))}
                        </List>
                      </BlockStack>
                    </Card>
                  </Layout.Section>
                )}
              </Layout>
            )}

            {/* ── TAB 2: CHAT CU JARVIS ── */}
            {selectedTab === 1 && (
              <Layout>
                <Layout.Section>
                  <Card>
                    <BlockStack gap="400">
                      <InlineStack align="space-between">
                        <Text variant="headingMd" as="h2">
                          Asistentul tău personal AI
                        </Text>
                        <Badge tone="info">Cunoaște datele magazinului tău</Badge>
                      </InlineStack>
                      <Divider />

                      {/* Chat messages viewport */}
                      <Box
                        padding="400"
                        background="bg-surface-secondary"
                        borderRadius="200"
                        minHeight="350px"
                        maxHeight="480px"
                        style={{ overflowY: 'auto' }}
                      >
                        <BlockStack gap="300">
                          {chatMessages.length === 0 && (
                            <Text tone="subdued" as="p">
                              Jarvis te așteaptă! Întreabă-mă orice: „De ce nu am comenzi azi?”, „Cum fac o campanie de TikTok pentru cel mai vândut produs?”, sau „Scrie-mi un email pentru coșurile abandonate”.
                            </Text>
                          )}
                          {chatMessages.map((m, idx) => (
                            <Box
                              key={idx}
                              padding="300"
                              borderRadius="200"
                              background={m.role === 'user' ? 'bg-surface-active' : 'bg-surface'}
                              style={{
                                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                maxWidth: '85%'
                              }}
                            >
                              <Text variant="bodySm" tone="subdued" as="p">
                                {m.role === 'user' ? 'Tu' : '🤖 Jarvis'}
                              </Text>
                              <Text variant="bodyMd" as="p" style={{ whiteSpace: 'pre-wrap' }}>
                                {m.content}
                              </Text>
                            </Box>
                          ))}
                          {sendingChat && (
                            <InlineStack gap="200" align="start">
                              <Spinner size="small" />
                              <Text variant="bodySm" tone="subdued" as="p">
                                Jarvis gândește răspunsul...
                              </Text>
                            </InlineStack>
                          )}
                          <div ref={chatBottomRef} />
                        </BlockStack>
                      </Box>

                      {/* Input bar */}
                      <InlineStack gap="200">
                        <div style={{ flex: 1 }}>
                          <TextField
                            placeholder="Scrie o întrebare pentru Jarvis..."
                            value={inputMessage}
                            onChange={setInputMessage}
                            autoComplete="off"
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleSendMessage()
                            }}
                          />
                        </div>
                        <Button variant="primary" onClick={handleSendMessage} loading={sendingChat}>
                          Trimite
                        </Button>
                      </InlineStack>
                    </BlockStack>
                  </Card>
                </Layout.Section>
              </Layout>
            )}

            {/* ── TAB 3: SARCINI RECOMANDATE ── */}
            {selectedTab === 2 && (
              <Layout>
                <Layout.Section>
                  <Card>
                    <BlockStack gap="400">
                      <InlineStack align="space-between">
                        <Text variant="headingMd" as="h2">
                          🎯 Ce trebuie să faci azi pentru a crește vânzările
                        </Text>
                        <Badge tone="success">Prioritizate după impact</Badge>
                      </InlineStack>
                      <Divider />

                      <BlockStack gap="300">
                        {briefingData?.top_tasks && briefingData.top_tasks.length > 0 ? (
                          briefingData.top_tasks.map((t, idx) => (
                            <Box
                              key={idx}
                              padding="300"
                              borderRadius="200"
                              background={completedTasks[idx] ? 'bg-surface-secondary' : 'bg-surface'}
                            >
                              <InlineStack align="start" gap="300">
                                <Checkbox
                                  checked={!!completedTasks[idx]}
                                  onChange={() => toggleTask(idx)}
                                />
                                <BlockStack gap="100">
                                  <Text
                                    variant="bodyMd"
                                    fontWeight="bold"
                                    as="p"
                                    style={{
                                      textDecoration: completedTasks[idx] ? 'line-through' : 'none'
                                    }}
                                  >
                                    {t.icon || '📌'} Prioritate {t.priority}: {t.task}
                                  </Text>
                                  <Text variant="bodySm" tone="subdued" as="p">
                                    De ce: {t.why}
                                  </Text>
                                </BlockStack>
                              </InlineStack>
                            </Box>
                          ))
                        ) : (
                          <Text as="p" tone="subdued">
                            Nicio sarcină generată momentan. Verifică din nou mai târziu.
                          </Text>
                        )}
                      </BlockStack>
                    </BlockStack>
                  </Card>
                </Layout.Section>
              </Layout>
            )}

            {/* ── TAB 4: ABONAMENT ── */}
            {selectedTab === 3 && (
              <Layout>
                <Layout.Section>
                  <Card>
                    <BlockStack gap="400">
                      <Text variant="headingLg" as="h2">
                        Planul Jarvis Pro — $9.99/lună
                      </Text>
                      <Divider />
                      <Text variant="bodyMd" as="p">
                        Asistentul tău dedicat de eCommerce care lucrează 24/7 pentru magazinul tău:
                      </Text>
                      <List type="bullet">
                        <List.Item>Briefing zilnic automat generat în fiecare dimineață</List.Item>
                        <List.Item>Alerte proactive pentru coșuri abandonate și stoc critic</List.Item>
                        <List.Item>Sarcini acționabile și sfaturi verificate de trafic organic/plătit</List.Item>
                        <List.Item>Chat nelimitat cu AI antrenat pe datele tale Shopify</List.Item>
                        <List.Item>Perioadă de test gratuit de 7 zile inclusă</List.Item>
                      </List>
                      <InlineStack gap="300">
                        <Button variant="primary" size="large">
                          Activează Abonamentul ($9.99/lună)
                        </Button>
                        <Button variant="plain">Condiții & Suport</Button>
                      </InlineStack>
                    </BlockStack>
                  </Card>
                </Layout.Section>
              </Layout>
            )}
          </Box>
        </Tabs>
      </BlockStack>
    </Page>
  )
}
