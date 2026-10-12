import { useLocation } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { systemApi } from '@/lib/api'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/recordings': 'Recordings',
  '/workflows': 'Workflows',
  '/settings': 'Settings',
}

export function Header() {
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] ??
    (location.pathname.includes('/workflows/') ? 'Workflow Editor' : 'AutoFlow')

  const { data: health } = useQuery({
    queryKey: ['system-health'],
    queryFn: systemApi.health,
    refetchInterval: 30_000,
    retry: false,
  })

  const isHealthy = health?.status === 'healthy'

  return (
    <header
      className="flex items-center justify-between px-6 py-4 border-b"
      style={{
        background: 'oklch(12% 0.014 265 / 0.8)',
        borderColor: 'oklch(25% 0.020 265 / 0.4)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <h1 className="text-lg font-semibold" style={{ color: 'oklch(95% 0.005 265)' }}>
        {title}
      </h1>

      <div className="flex items-center gap-4">
        {/* API Health Indicator */}
        <div className="flex items-center gap-2 text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>
          <span
            className={`status-dot ${isHealthy ? 'active' : 'failed'}`}
            title={isHealthy ? 'API is healthy' : 'API is unreachable'}
          />
          <span>{isHealthy ? 'Connected' : 'Offline'}</span>
        </div>

        {/* Notifications */}
        <button
          className="p-2 rounded-lg transition-colors"
          style={{ color: 'oklch(60% 0.010 265)' }}
          aria-label="Notifications"
        >
          <Bell size={18} />
        </button>
      </div>
    </header>
  )
}
