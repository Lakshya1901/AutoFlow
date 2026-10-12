import { useQuery, useMutation } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckCircle, XCircle, Clock } from 'lucide-react'
import { toast } from 'sonner'
import { workflowsApi } from '@/lib/api'
import { formatDuration, formatRelativeTime, getStatusColor } from '@/lib/utils'
import type { WorkflowRun } from '@/types/api'

function RunRow({ run, onCancel }: { run: WorkflowRun; onCancel: (id: string) => void }) {
  const navigate = useNavigate()
  const statusColor = getStatusColor(run.status)
  const canCancel = ['queued', 'running', 'waiting_for_approval'].includes(run.status)

  return (
    <div
      className="glass-card p-4 animate-fade-in"
      onClick={() => navigate(`/workflows/${run.workflow_id}/runs`)}
    >
      <div className="flex items-center gap-3 mb-3">
        <span className={`status-dot ${run.status}`} />
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded-full"
          style={{ background: `${statusColor}15`, color: statusColor, border: `1px solid ${statusColor}25` }}
        >
          {run.status.replace(/_/g, ' ')}
        </span>
        <span className="text-xs ml-auto" style={{ color: 'oklch(55% 0.015 265)' }}>
          {formatRelativeTime(run.created_at)}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 text-xs">
        <div>
          <p style={{ color: 'oklch(55% 0.015 265)' }}>Duration</p>
          <p className="font-medium mt-0.5" style={{ color: 'oklch(85% 0.008 265)' }}>
            {run.duration_ms ? formatDuration(run.duration_ms) : '—'}
          </p>
        </div>
        <div>
          <p style={{ color: 'oklch(55% 0.015 265)' }}>Steps</p>
          <p className="font-medium mt-0.5" style={{ color: 'oklch(85% 0.008 265)' }}>
            {run.completed_steps?.length ?? 0} completed
          </p>
        </div>
        <div>
          <p style={{ color: 'oklch(55% 0.015 265)' }}>Triggered by</p>
          <p className="font-medium mt-0.5" style={{ color: 'oklch(85% 0.008 265)' }}>
            {run.triggered_by}
          </p>
        </div>
      </div>

      {run.error_message && (
        <div
          className="mt-3 p-2 rounded-lg text-xs"
          style={{ background: 'oklch(62% 0.24 25 / 0.1)', border: '1px solid oklch(62% 0.24 25 / 0.2)', color: 'oklch(72% 0.22 25)' }}
        >
          ⚠️ {run.error_message}
        </div>
      )}

      {run.step_logs && run.step_logs.length > 0 && (
        <div className="mt-3 space-y-1">
          {run.step_logs.slice(-3).map((log, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              {log.success
                ? <CheckCircle size={11} style={{ color: 'oklch(68% 0.20 145)' }} />
                : <XCircle size={11} style={{ color: 'oklch(62% 0.24 25)' }} />}
              <span style={{ color: 'oklch(65% 0.015 265)' }}>{log.step_name}</span>
            </div>
          ))}
        </div>
      )}

      {canCancel && (
        <button
          onClick={(e) => { e.stopPropagation(); onCancel(run.id) }}
          className="mt-3 w-full text-xs py-1.5 rounded-lg transition-colors"
          style={{
            background: 'oklch(62% 0.24 25 / 0.1)',
            border: '1px solid oklch(62% 0.24 25 / 0.2)',
            color: 'oklch(72% 0.22 25)',
          }}
        >
          Cancel Run
        </button>
      )}
    </div>
  )
}

export function RunHistoryPage() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()

  const { data: workflow } = useQuery({
    queryKey: ['workflow', workflowId],
    queryFn: () => workflowsApi.get(workflowId!),
    enabled: !!workflowId,
  })

  const { data: runs, isLoading } = useQuery({
    queryKey: ['runs', workflowId],
    queryFn: () => workflowsApi.listRuns(workflowId!, 1, 50),
    enabled: !!workflowId,
    refetchInterval: 5_000, // Poll for active runs
  })

  const cancelMutation = useMutation({
    mutationFn: workflowsApi.cancelRun,
    onSuccess: () => toast.success('Run cancelled'),
    onError: () => toast.error('Failed to cancel run'),
  })

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(`/workflows/${workflowId}`)}
          className="p-2 rounded-lg"
          style={{ color: 'oklch(60% 0.015 265)' }}
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'oklch(97% 0.005 265)' }}>
            Run History
          </h2>
          <p className="text-sm" style={{ color: 'oklch(55% 0.015 265)' }}>
            {workflow?.name} · {runs?.total ?? 0} runs
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => <div key={i} className="skeleton h-28 rounded-xl" />)}
        </div>
      ) : runs?.items.length === 0 ? (
        <div className="text-center py-16">
          <Clock size={36} className="mx-auto mb-3 opacity-20" />
          <p style={{ color: 'oklch(55% 0.015 265)' }}>No runs yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {runs?.items.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              onCancel={(id) => cancelMutation.mutate(id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
