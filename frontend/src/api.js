// Central API helper for the Jarvis dashboard.
//
// - When the app runs embedded in Shopify Admin, the App Bridge CDN script
//   (app-bridge.js, loaded first in index.html) patches the global fetch and
//   adds `Authorization: Bearer <session token>` to same-origin requests.
//   We therefore always call `window.fetch` at request time and never set an
//   Authorization header ourselves.
// - Outside Shopify Admin (direct access), the owner can provide a Jarvis
//   admin key; it is sent as `X-Jarvis-Key`.
// - A 401 response notifies subscribers (the App shows the login card).
//
// All storage access is wrapped in try/catch: embedded iframes and private
// windows may block localStorage.

const KEY_STORAGE = 'jarvis_admin_key'

let memoryKey = null
const authListeners = new Set()

export function storageGet(name) {
  try {
    return window.localStorage.getItem(name)
  } catch (e) {
    return null
  }
}

export function storageSet(name, value) {
  try {
    if (value === null || value === undefined || value === '') {
      window.localStorage.removeItem(name)
    } else {
      window.localStorage.setItem(name, value)
    }
    return true
  } catch (e) {
    return false
  }
}

export function getAdminKey() {
  if (memoryKey) return memoryKey
  const stored = storageGet(KEY_STORAGE)
  if (stored) memoryKey = stored
  return memoryKey
}

export function setAdminKey(key) {
  const clean = typeof key === 'string' ? key.trim() : ''
  memoryKey = clean || null
  storageSet(KEY_STORAGE, memoryKey)
}

export function hasAdminKey() {
  return !!getAdminKey()
}

// Subscribe to "authentication required" events. Returns an unsubscribe fn.
export function onAuthRequired(listener) {
  authListeners.add(listener)
  return () => authListeners.delete(listener)
}

function notifyAuthRequired(path) {
  authListeners.forEach((fn) => {
    try {
      fn({ path })
    } catch (e) {
      console.warn('auth listener error', e)
    }
  })
}

function toPlainHeaders(headers) {
  const out = {}
  if (!headers) return out
  if (typeof Headers !== 'undefined' && headers instanceof Headers) {
    headers.forEach((v, k) => { out[k] = v })
    return out
  }
  if (Array.isArray(headers)) {
    headers.forEach(([k, v]) => { out[k] = v })
    return out
  }
  return { ...headers }
}

function hasHeader(headers, name) {
  const lower = name.toLowerCase()
  return Object.keys(headers).some((k) => k.toLowerCase() === lower)
}

// fetch wrapper. Returns the raw Response (callers check res.ok).
export async function api(path, opts = {}) {
  const headers = toPlainHeaders(opts.headers)
  if (typeof opts.body === 'string' && !hasHeader(headers, 'Content-Type')) {
    headers['Content-Type'] = 'application/json'
  }
  const key = getAdminKey()
  if (key && !hasHeader(headers, 'X-Jarvis-Key')) {
    headers['X-Jarvis-Key'] = key
  }
  const res = await window.fetch(path, { ...opts, headers })
  if (res.status === 401) {
    notifyAuthRequired(path)
  }
  return res
}

// Convenience: JSON body POST.
export function apiPost(path, body, opts = {}) {
  return api(path, { ...opts, method: 'POST', body: JSON.stringify(body || {}) })
}

// Parse JSON safely (returns {} on empty / invalid body).
export async function readJson(res) {
  try {
    const text = await res.text()
    return text ? JSON.parse(text) : {}
  } catch (e) {
    return {}
  }
}

// Human readable error from a failed response body.
export function errorText(data, res) {
  if (data && typeof data === 'object') {
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) {
      return data.detail.map((d) => (d && d.msg) || String(d)).join('; ')
    }
    if (typeof data.error === 'string') return data.error
    if (typeof data.reason === 'string') return data.reason
  }
  return res ? `HTTP ${res.status}` : 'eroare necunoscută'
}
