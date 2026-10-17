const TOKEN_KEY = 'tadbeer_token'
const USER_KEY = 'tadbeer_username'

export function getStoredSession() {
  const token = localStorage.getItem(TOKEN_KEY)
  const username = localStorage.getItem(USER_KEY)
  return token && username ? { token, username } : null
}

export function storeSession({ token, username }) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, username)
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

let onUnauthorized = () => {}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

async function request(path, options = {}) {
  const session = getStoredSession()
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (session) headers.Authorization = `Bearer ${session.token}`

  let response
  try {
    response = await fetch(path, { ...options, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the Tadbeer backend. Is it running on port 8000?')
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // keep the generic message
    }
    if (response.status === 401 && path !== '/api/auth/login') onUnauthorized()
    throw new ApiError(response.status, detail)
  }

  return response.json()
}

export function login(username, password) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function listRuns() {
  return request('/api/runs')
}

export function getRun(id) {
  return request(`/api/runs/${id}`)
}

export function checkClickUpNow(id) {
  return request(`/api/runs/${id}/monitor`, { method: 'POST' })
}
