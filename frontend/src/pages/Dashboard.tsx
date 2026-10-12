import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Video, Workflow, Play, Clock, CheckCircle, ArrowRight, Zap } from 'lucide-react'
import { recordingsApi, workflowsApi } from '@/lib/api'
import { formatRelativeTime } from '@/lib/utils'

function StatCard({
  label, value, icon: Icon, color, trend
}: {
  label: string
  value: string | number
  icon: React.ElementType
  color: string
  trend?: string
}) {
  return (
    <div className="glass-card p-5 animate-fade-in">
      <div className="flex items-start justify-between mb-4">
        <div
          className="p-2.5 rounded-lg"
          style={{ background: `${color}15`, border: `1px solid ${color}25` }}
        >
          <Icon size={20} style={{ color }} />
        </div>
        {trend && (
          <span className="text-xs font-medium" style={{ color: 'oklch(68% 0.20 145)' }}>
            {trend}
          </span>
        )}
      </div>
      <div className="text-3xl font-bold mb-1" style={{ color: 'oklch(95% 0.005 265)' }}>
        {value}
      </div>
      <div className="text-sm" style={{ color: 'oklch(55% 0.015 265)' }}>{label}</div>
    </div>
  )
}

export function DashboardPage() {
  const navigate = useNavigate()

  const { data: recordings } = useQuery({
    queryKey: ['recordings'],
    queryFn: () => recordingsApi.list(1, 5),
  })

  const { data: workflows } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => workflowsApi.list(1, 10),
  })

  const totalRuns = workflows?.items.reduce((sum, w) => sum + w.total_runs, 0) ?? 0
  const successfulRuns = workflows?.items.reduce((sum, w) => sum + w.successful_runs, 0) ?? 0
  const successRate = totalRuns > 0 ? Math.round((successfulRuns / totalRuns) * 100) : 0
  const timeSaved = workflows?.items.reduce((sum, w) => sum + w.estimated_time_saved_minutes, 0) ?? 0

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Hero */}
      <div
        className="rounded-xl p-6 relative overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, oklch(58% 0.26 265 / 0.15) 0%, oklch(72% 0.22 195 / 0.08) 100%)',
          border: '1px solid oklch(58% 0.26 265 / 0.2)',
        }}
      >
        <div className="absolute top-0 right-0 w-64 h-64 opacity-5 pointer-events-none"
          style={{
            background: 'radial-gradient(circle, oklch(72% 0.22 195), transparent)',
            transform: 'translate(30%, -30%)',
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={16} style={{ color: 'oklch(72% 0.22 195)' }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'oklch(72% 0.22 195)' }}>
              AutoFlow AI
            </span>
          </div>
          <h2 className="text-2xl font-bold mb-2" style={{ color: 'oklch(97% 0.005 265)' }}>
            Demonstrate it once.{' '}
            <span className="gradient-text">AutoFlow handles it forever.</span>
          </h2>
          <p className="text-sm mb-5" style={{ color: 'oklch(65% 0.015 265)' }}>
            Start recording a workflow and let AI understand your intent.
          </p>
          <button
            onClick={() => navigate('/recordings')}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all duration-200 hover:scale-105"
            style={{
              background: 'linear-gradient(135deg, oklch(58% 0.26 265), oklch(72% 0.22 195))',
              boxShadow: 'var(--shadow-glow)',
            }}
          >
            <Video size={16} />
            Start Recording
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Recordings"
          value={recordings?.total ?? 0}
          icon={Video}
          color="oklch(72% 0.22 195)"
        />
        <StatCard
          label="Active Workflows"
          value={workflows?.total ?? 0}
          icon={Workflow}
          color="oklch(58% 0.26 265)"
        />
        <StatCard
          label="Success Rate"
          value={`${successRate}%`}
          icon={CheckCircle}
          color="oklch(68% 0.20 145)"
          trend={totalRuns > 0 ? `${successfulRuns}/${totalRuns} runs` : undefined}
        />
        <StatCard
          label="Time Saved"
          value={timeSaved > 60 ? `${Math.round(timeSaved / 60)}h` : `${Math.round(timeSaved)}m`}
          icon={Clock}
          color="oklch(74% 0.20 80)"
        />
      </div>

      {/* Recent Workflows & Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Workflows */}
        <div className="glass-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold" style={{ color: 'oklch(90% 0.008 265)' }}>
              Recent Workflows
            </h3>
            <button
              onClick={() => navigate('/workflows')}
              className="flex items-center gap-1 text-xs transition-colors"
              style={{ color: 'oklch(68% 0.16 265)' }}
            >
              View all <ArrowRight size={12} />
            </button>
          </div>
          <div className="space-y-2">
            {workflows?.items.slice(0, 5).map((wf) => (
              <div
                key={wf.id}
                onClick={() => navigate(`/workflows/${wf.id}`)}
                className="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all duration-150"
                style={{ background: 'oklch(16% 0.018 265 / 0.4)' }}
              >
                <span className={`status-dot ${wf.status}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: 'oklch(90% 0.008 265)' }}>
                    {wf.name}
                  </p>
                  <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>
                    {wf.total_runs} runs · {formatRelativeTime(wf.updated_at)}
                  </p>
                </div>
                <ArrowRight size={14} style={{ color: 'oklch(50% 0.015 265)' }} />
              </div>
            ))}
            {!workflows?.items.length && (
              <div className="text-center py-8">
                <Workflow size={32} className="mx-auto mb-3 opacity-20" />
                <p className="text-sm" style={{ color: 'oklch(50% 0.015 265)' }}>
                  No workflows yet
                </p>
                <button
                  onClick={() => navigate('/recordings')}
                  className="mt-3 text-sm"
                  style={{ color: 'oklch(68% 0.16 265)' }}
                >
                  Record one to get started →
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold mb-4" style={{ color: 'oklch(90% 0.008 265)' }}>
            Quick Actions
          </h3>
          <div className="space-y-3">
            {[
              {
                icon: Video,
                label: 'Record New Workflow',
                desc: 'Capture browser actions and extract intent',
                color: 'oklch(72% 0.22 195)',
                path: '/recordings',
              },
              {
                icon: Workflow,
                label: 'Browse Workflows',
                desc: 'View, edit, and run your automations',
                color: 'oklch(58% 0.26 265)',
                path: '/workflows',
              },
              {
                icon: Play,
                label: 'View Run History',
                desc: 'Monitor execution logs and results',
                color: 'oklch(68% 0.20 145)',
                path: '/workflows',
              },
            ].map(({ icon: Icon, label, desc, color, path }) => (
              <button
                key={label}
                onClick={() => navigate(path)}
                className="w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all duration-200 group"
                style={{ background: 'oklch(16% 0.018 265 / 0.4)' }}
              >
                <div
                  className="p-2 rounded-lg flex-shrink-0"
                  style={{ background: `${color}15`, border: `1px solid ${color}25` }}
                >
                  <Icon size={16} style={{ color }} />
                </div>
                <div>
                  <p className="text-sm font-medium" style={{ color: 'oklch(90% 0.008 265)' }}>{label}</p>
                  <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>{desc}</p>
                </div>
                <ArrowRight
                  size={14}
                  className="ml-auto transition-transform group-hover:translate-x-1"
                  style={{ color: 'oklch(50% 0.015 265)' }}
                />
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
