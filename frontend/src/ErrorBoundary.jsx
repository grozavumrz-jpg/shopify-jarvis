import React from 'react'

// Catches render errors in the dashboard and shows a friendly Romanian card
// instead of a blank screen.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Jarvis dashboard error:', error, info)
  }

  handleReload = () => {
    try {
      window.location.reload()
    } catch (e) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    const message = this.state.error && this.state.error.message ? String(this.state.error.message) : ''
    return (
      <div style={{
        minHeight: '100vh',
        background: '#0e121a',
        color: '#f8fafc',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif"
      }}>
        <div style={{
          maxWidth: '520px',
          width: '100%',
          background: 'rgba(22, 28, 42, 0.92)',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          borderRadius: '16px',
          padding: '28px',
          boxShadow: '0 8px 30px rgba(0,0,0,0.45)'
        }}>
          <div style={{ fontSize: '12px', fontWeight: 800, letterSpacing: '1px', color: '#f59e0b', marginBottom: '10px' }}>
            GROZAVU — JARVIS
          </div>
          <h2 style={{ fontFamily: "'Playfair Display', Georgia, serif", fontSize: '22px', marginBottom: '10px' }}>
            Ceva nu a funcționat în panoul Jarvis
          </h2>
          <p style={{ fontSize: '14px', color: '#94a3b8', lineHeight: 1.6, marginBottom: '16px' }}>
            A apărut o eroare neașteptată la afișarea panoului. Datele magazinului nu au fost modificate.
            Reîncarcă pagina; dacă problema persistă, trimite-ne mesajul de mai jos.
          </p>
          {message && (
            <pre style={{
              fontSize: '12px',
              background: '#090c12',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '8px',
              padding: '10px',
              color: '#f87171',
              whiteSpace: 'pre-wrap',
              marginBottom: '16px'
            }}>{message}</pre>
          )}
          <button
            onClick={this.handleReload}
            style={{
              background: '#f59e0b',
              border: 'none',
              color: '#0e121a',
              padding: '10px 20px',
              borderRadius: '10px',
              fontWeight: 800,
              cursor: 'pointer'
            }}
          >
            Reîncarcă pagina
          </button>
        </div>
      </div>
    )
  }
}
