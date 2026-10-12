import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Video, Trash2, Eye, Zap, Clock } from 'lucide-react'
import { toast } from 'sonner'
import { recordingsApi, aiApi, workflowsApi } from '@/lib/api'
import { formatRelativeTime, formatDuration, getStatusColor } from '@/lib/utils'
import type { RecordingSession } from '@/types/api'

function RecordingCard({ recording, onDelete, onExtractIntent }: {
  recording: RecordingSession
  onDelete: (id: string) => void
  onExtractIntent: (id: string) => void
}) {
  const navigate = useNavigate()
  const statusColor = getStatusColor(recording.status)

  return (
    <div className="glass-card p-5 animate-fade-in">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`status-dot ${recording.status}`} />
          <span
            className="text-xs font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
            style={{ background: `${statusColor}15`, color: statusColor, border: `1px solid ${statusColor}25` }}
          >
            {recording.status}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => navigate(`/recordings/${recording.id}`)}
            className="p-1.5 rounded-lg transition-colors hover:opacity-80"
            style={{ color: 'oklch(60% 0.015 265)' }}
            aria-label="View recording"
          >
            <Eye size={15} />
          </button>
          <button
            onClick={() => onDelete(recording.id)}
            className="p-1.5 rounded-lg transition-colors hover:opacity-80"
            style={{ color: 'oklch(55% 0.015 265)' }}
            aria-label="Delete recording"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      <h3 className="text-sm font-semibold mb-1 truncate" style={{ color: 'oklch(95% 0.005 265)' }}>
        {recording.name ?? `Recording ${recording.id.slice(0, 8)}`}
      </h3>

      <div className="flex items-center gap-3 text-xs mb-4" style={{ color: 'oklch(55% 0.015 265)' }}>
        <span className="flex items-center gap-1">
          <Clock size={11} />
          {formatRelativeTime(recording.created_at)}
        </span>
        {recording.duration_seconds && (
          <span>{formatDuration(recording.duration_seconds * 1000)}</span>
        )}
        <span>{recording.raw_event_count} events</span>
      </div>

      {recording.status === 'completed' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs mb-2">
            <span style={{ color: 'oklch(60% 0.015 265)' }}>
              {recording.semantic_action_count} semantic actions extracted
            </span>
          </div>
          <button
            onClick={() => onExtractIntent(recording.id)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all duration-200 hover:scale-[1.02]"
            style={{
              background: 'linear-gradient(135deg, oklch(58% 0.26 265 / 0.2), oklch(72% 0.22 195 / 0.15))',
              border: '1px solid oklch(58% 0.26 265 / 0.3)',
              color: 'oklch(78% 0.16 265)',
            }}
          >
            <Zap size={13} />
            Extract Intent & Generate Workflow
          </button>
        </div>
      )}
    </div>
  )
}

export function RecordingsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['recordings'],
    queryFn: () => recordingsApi.list(1, 50),
  })

  const deleteMutation = useMutation({
    mutationFn: recordingsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      toast.success('Recording deleted')
    },
    onError: () => toast.error('Failed to delete recording'),
  })

  const extractIntentMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      const analysis = await aiApi.extractIntent({ session_id: sessionId })
      const suggestion = await aiApi.generateWorkflow({ intent_analysis_id: analysis.id })
      const workflow = await workflowsApi.createFromSuggestion(suggestion.id)
      return { analysis, workflow }
    },
    onSuccess: ({ analysis, workflow }) => {
      toast.success(`Intent: "${analysis.intent}"`, { duration: 4000 })
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      navigate(`/workflows/${workflow.id}`)
    },
    onError: () => toast.error('Failed to extract intent. Is the AI provider running?'),
  })

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'oklch(97% 0.005 265)' }}>
            Recordings
          </h2>
          <p className="text-sm mt-0.5" style={{ color: 'oklch(55% 0.015 265)' }}>
            {data?.total ?? 0} total recordings
          </p>
        </div>
        <a
          href="chrome-extension://autoflow/popup.html"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all duration-200 hover:scale-105"
          style={{
            background: 'linear-gradient(135deg, oklch(58% 0.26 265), oklch(72% 0.22 195))',
            boxShadow: 'var(--shadow-glow)',
          }}
        >
          <Video size={16} />
          Open Extension to Record
        </a>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="skeleton h-48 rounded-xl" />
          ))}
        </div>
      ) : data?.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div
            className="w-16 h-16 rounded-xl flex items-center justify-center mb-4"
            style={{ background: 'oklch(58% 0.26 265 / 0.1)', border: '1px solid oklch(58% 0.26 265 / 0.2)' }}
          >
            <Video size={28} style={{ color: 'oklch(58% 0.26 265)' }} />
          </div>
          <h3 className="text-base font-semibold mb-2" style={{ color: 'oklch(90% 0.008 265)' }}>
            No recordings yet
          </h3>
          <p className="text-sm max-w-sm" style={{ color: 'oklch(55% 0.015 265)' }}>
            Install the AutoFlow Chrome Extension and start recording a workflow to see it here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data?.items.map((recording) => (
            <RecordingCard
              key={recording.id}
              recording={recording}
              onDelete={(id) => deleteMutation.mutate(id)}
              onExtractIntent={(id) => extractIntentMutation.mutate(id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
