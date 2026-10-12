import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Zap, Clock, Activity } from 'lucide-react'
import { recordingsApi } from '@/lib/api'
import { formatDate, formatDuration, getActionTypeIcon, getStatusColor } from '@/lib/utils'

export function RecordingDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()

  const { data: session, isLoading } = useQuery({
    queryKey: ['recording', sessionId],
    queryFn: () => recordingsApi.get(sessionId!),
    enabled: !!sessionId,
  })

  if (isLoading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="skeleton h-8 w-48 rounded" />
        <div className="skeleton h-64 rounded-xl" />
      </div>
    )
  }

  if (!session) return null

  const statusColor = getStatusColor(session.status)

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/recordings')}
          className="p-2 rounded-lg transition-colors"
          style={{ color: 'oklch(60% 0.015 265)' }}
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'oklch(97% 0.005 265)' }}>
            {session.name ?? `Recording ${session.id.slice(0, 8)}`}
          </h2>
          <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>
            {formatDate(session.created_at)}
          </p>
        </div>
        <span
          className="ml-auto text-xs font-semibold px-2 py-1 rounded-full"
          style={{ background: `${statusColor}15`, color: statusColor, border: `1px solid ${statusColor}25` }}
        >
          {session.status}
        </span>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Raw Events', value: session.raw_event_count, icon: Activity, color: 'oklch(72% 0.22 195)' },
          { label: 'Semantic Actions', value: session.semantic_action_count, icon: Zap, color: 'oklch(58% 0.26 265)' },
          { label: 'Duration', value: session.duration_seconds ? formatDuration(session.duration_seconds * 1000) : '—', icon: Clock, color: 'oklch(74% 0.20 80)' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="glass-card p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon size={16} style={{ color }} />
              <span className="text-xs" style={{ color: 'oklch(60% 0.015 265)' }}>{label}</span>
            </div>
            <div className="text-2xl font-bold" style={{ color: 'oklch(95% 0.005 265)' }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Semantic Actions Timeline */}
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold mb-4" style={{ color: 'oklch(90% 0.008 265)' }}>
          Semantic Actions
        </h3>
        {session.semantic_actions?.length === 0 ? (
          <p className="text-sm text-center py-8" style={{ color: 'oklch(50% 0.015 265)' }}>
            No semantic actions yet — recording may still be processing.
          </p>
        ) : (
          <div className="space-y-2">
            {session.semantic_actions?.map((action, idx) => (
              <div
                key={action.id}
                className="flex items-start gap-3 p-3 rounded-lg animate-fade-in"
                style={{
                  background: 'oklch(16% 0.018 265 / 0.5)',
                  border: '1px solid oklch(28% 0.020 265 / 0.3)',
                  animationDelay: `${idx * 50}ms`,
                }}
              >
                <span className="text-lg leading-none mt-0.5">{getActionTypeIcon(action.action_type)}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium" style={{ color: 'oklch(90% 0.008 265)' }}>
                    {action.description}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs" style={{ color: 'oklch(50% 0.015 265)' }}>
                      {action.action_type}
                    </span>
                    {action.application && (
                      <>
                        <span style={{ color: 'oklch(35% 0.015 265)' }}>·</span>
                        <span className="text-xs" style={{ color: 'oklch(60% 0.015 265)' }}>
                          {action.application}
                        </span>
                      </>
                    )}
                    {action.confidence && (
                      <>
                        <span style={{ color: 'oklch(35% 0.015 265)' }}>·</span>
                        <span className="text-xs" style={{ color: 'oklch(68% 0.20 145)' }}>
                          {Math.round(action.confidence * 100)}% confidence
                        </span>
                      </>
                    )}
                  </div>
                  {action.extracted_data && Object.keys(action.extracted_data).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {Object.entries(action.extracted_data).slice(0, 3).map(([k, v]) => (
                        <span
                          key={k}
                          className="text-xs px-2 py-0.5 rounded"
                          style={{ background: 'oklch(25% 0.020 265 / 0.5)', color: 'oklch(75% 0.012 265)' }}
                        >
                          {k}: {String(v).slice(0, 30)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <span
                  className="text-xs flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center"
                  style={{ background: 'oklch(25% 0.020 265 / 0.5)', color: 'oklch(60% 0.015 265)' }}
                >
                  {idx + 1}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
