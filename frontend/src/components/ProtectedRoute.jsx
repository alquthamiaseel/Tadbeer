import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

// ---------------------------------------------------------------------------
// ProtectedRoute
// ---------------------------------------------------------------------------
// Wraps pages that should only be visible to a logged-in user (Dashboard,
// Profile, etc.). If nobody is logged in, it sends the visitor to /login
// instead of rendering the page.
// ---------------------------------------------------------------------------
export default function ProtectedRoute({ children }) {
  const { user } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}
