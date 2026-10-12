import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Video,
  Workflow,
  History,
  Settings,
  Zap,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/recordings', icon: Video, label: 'Recordings' },
  { to: '/workflows', icon: Workflow, label: 'Workflows' },
  { to: '/runs', icon: History, label: 'Run History' },
]

export function Sidebar() {
  return (
    <aside
      className="w-64 flex-shrink-0 flex flex-col border-r"
      style={{
        background: 'oklch(12% 0.014 265 / 0.95)',
        borderColor: 'oklch(25% 0.020 265 / 0.4)',
      }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b" style={{ borderColor: 'oklch(25% 0.020 265 / 0.4)' }}>
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: 'linear-gradient(135deg, oklch(58% 0.26 265), oklch(72% 0.22 195))' }}
        >
          <Zap size={16} className="text-white" />
        </div>
        <div>
          <span className="font-bold text-base tracking-tight gradient-text">AutoFlow</span>
          <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>AI Automation</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group',
                isActive
                  ? 'text-white'
                  : 'hover:text-white',
              )
            }
            style={({ isActive }) => ({
              background: isActive ? 'oklch(58% 0.26 265 / 0.15)' : 'transparent',
              color: isActive ? 'oklch(78% 0.16 265)' : 'oklch(60% 0.010 265)',
              border: isActive ? '1px solid oklch(58% 0.26 265 / 0.25)' : '1px solid transparent',
            })}
          >
            {({ isActive }) => (
              <>
                <Icon size={18} style={{ color: isActive ? 'oklch(72% 0.22 195)' : 'currentColor' }} />
                <span>{label}</span>
                {isActive && (
                  <ChevronRight size={14} className="ml-auto opacity-50" />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Settings */}
      <div className="px-3 py-4 border-t" style={{ borderColor: 'oklch(25% 0.020 265 / 0.4)' }}>
        <NavLink
          to="/settings"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200"
          style={({ isActive }) => ({
            background: isActive ? 'oklch(58% 0.26 265 / 0.15)' : 'transparent',
            color: isActive ? 'oklch(78% 0.16 265)' : 'oklch(60% 0.010 265)',
          })}
        >
          <Settings size={18} />
          <span>Settings</span>
        </NavLink>
      </div>
    </aside>
  )
}
