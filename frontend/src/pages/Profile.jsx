import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { UserIcon, LogoutIcon } from '../components/icons.jsx'

export default function Profile() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div>
      <h1 className="text-3xl font-bold text-slate-900">Profile</h1>
      <p className="mt-1 text-slate-500">Your Tadbeer account</p>

      <div className="mt-6 max-w-xl rounded-2xl border border-slate-200 bg-white p-8">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-teal-500 text-xl font-semibold text-white">
            {user?.username?.[0]?.toUpperCase() || '?'}
          </div>
          <div>
            <p className="flex items-center gap-2 text-sm text-slate-500">
              <UserIcon className="h-4 w-4" />
              Username
            </p>
            <p className="text-lg font-semibold text-slate-900">{user?.username}</p>
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="mt-8 flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2.5 font-semibold text-slate-700 transition hover:bg-slate-50"
        >
          <LogoutIcon className="h-4 w-4" />
          Log Out
        </button>
      </div>
    </div>
  )
}
