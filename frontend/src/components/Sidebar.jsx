import { NavLink } from 'react-router-dom'
import { GridIcon, DocumentIcon, SettingsIcon, ChatIcon } from './icons.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const navItems = [
  { label: 'Dashboard', to: '/dashboard', icon: GridIcon },
  { label: 'Project Overview', to: '/project-overview', icon: DocumentIcon },
]

function getInitials(name) {
  if (!name) return '?'
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

const linkClass = ({ isActive }) =>
  `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
    isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-900 hover:text-white'
  }`

export default function Sidebar() {
  const { user } = useAuth()

  return (
    <aside className="flex h-screen w-72 shrink-0 flex-col justify-between border-r border-slate-800 bg-slate-950 px-4 py-6">
      <div>
        <div className="mb-6 flex items-center gap-3 px-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-500 font-bold text-white">
            T
          </div>
          <div>
            <p className="font-semibold text-white">Tadbeer</p>
            <p className="text-xs text-slate-400">AI-Powered SDLC</p>
          </div>
        </div>

        <div className="mb-6 rounded-lg border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400">
          <div className="mb-1 flex items-center gap-2 font-semibold text-slate-200">
            <ChatIcon className="h-4 w-4" />
            Start a project in Slack
          </div>
          Discuss it in a channel, then run <span className="font-mono text-teal-400">/pm start</span>.
        </div>

        <nav className="space-y-1">
          {navItems.map(({ label, to, icon: Icon }) => (
            <NavLink key={to} to={to} className={linkClass}>
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="space-y-1 border-t border-slate-800 pt-4">
        <NavLink to="/settings" className={linkClass}>
          <SettingsIcon className="h-5 w-5" />
          Settings
        </NavLink>

        <NavLink
          to="/profile"
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 transition ${
              isActive ? 'bg-slate-800' : 'hover:bg-slate-900'
            }`
          }
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-teal-500 text-sm font-semibold text-white">
            {getInitials(user?.username)}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">{user?.username}</p>
            <p className="truncate text-xs text-slate-400">Signed in</p>
          </div>
        </NavLink>
      </div>
    </aside>
  )
}
