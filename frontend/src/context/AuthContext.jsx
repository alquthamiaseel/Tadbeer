import { createContext, useContext, useEffect, useState } from 'react'
import * as api from '../lib/api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => api.getStoredSession())

  async function login(username, password) {
    const result = await api.login(username, password)
    api.storeSession(result)
    setSession({ token: result.token, username: result.username })
  }

  function logout() {
    api.clearSession()
    setSession(null)
  }

  useEffect(() => {
    api.setUnauthorizedHandler(logout)
  }, [])

  const user = session ? { username: session.username, fullName: session.username } : null

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
