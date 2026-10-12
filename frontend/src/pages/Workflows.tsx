import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Workflow, Play, Edit3, Copy, Trash2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { workflowsApi } from '@/lib/api'
import { formatRelativeTime, getStatusColor } from '@/lib/utils'
import type { Workflow as WorkflowType } from '@/types/api'

function WorkflowCard({ workflow, onDelete, onClone, onRun }: {
  workflow: WorkflowType
  onDelete: (id: string) => void
  onClone: (id: string) => void
  onRun: (id: string) => void
}) {
  const navigate = useNavigate()
  const statusColor = getStatusColor(workflow.status)
  const successRate = workflow.total_runs > 0
    ? Math.round((workflow.successful_runs / workflow.total_runs) * 100)
    : null

  return (
    <div className="glass-card p-5 animate-fade-in">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`status-dot ${workflow.status}`} />
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ background: `${statusColor}15`, color: statusColor, border: `1px solid ${statusColor}25` }}
          >
            {workflow.status}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onRun(workflow.id)}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'oklch(68% 0.20 145)' }}
            title="Run workflow"
            aria-label="Run workflow"
          >
            <Play size={14} />
          </button>
          <button
            onClick={() => navigate(`/workflows/${workflow.id}`)}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'oklch(60% 0.015 265)' }}
            title="Edit workflow"
            aria-label="Edit workflow"
          >
            <Edit3 size={14} />
          </button>
          <button
            onClick={() => onClone(workflow.id)}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'oklch(60% 0.015 265)' }}
            title="Clone workflow"
            aria-label="Clone workflow"
          >
            <Copy size={14} />
          </button>
          <button
            onClick={() => onDelete(workflow.id)}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'oklch(55% 0.015 265)' }}
            title="Delete workflow"
            aria-label="Delete workflow"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <h3 className="text-sm font-semibold mb-1 truncate" style={{ color: 'oklch(95% 0.005 265)' }}>
        {workflow.name}
      </h3>
      {workflow.description && (
        <p className="text-xs mb-3 line-clamp-2" style={{ color: 'oklch(60% 0.015 265)' }}>
          {workflow.description}
        </p>
      )}

      <div className="grid grid-cols-3 gap-2 mt-4">
        <div className="text-center">
          <p className="text-lg font-bold" style={{ color: 'oklch(95% 0.005 265)' }}>
            {workflow.total_runs}
          </p>
          <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>Runs</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold" style={{ color: successRate !== null ? 'oklch(68% 0.20 145)' : 'oklch(55% 0.015 265)' }}>
            {successRate !== null ? `${successRate}%` : '—'}
          </p>
          <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>Success</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold" style={{ color: 'oklch(95% 0.005 265)' }}>
            {workflow.steps?.length ?? 0}
          </p>
          <p className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>Steps</p>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t flex items-center justify-between" style={{ borderColor: 'oklch(28% 0.020 265 / 0.3)' }}>
        <span className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>
          Updated {formatRelativeTime(workflow.updated_at)}
        </span>
        {workflow.trigger_type !== 'manual' && (
          <span className="text-xs px-2 py-0.5 rounded" style={{ background: 'oklch(58% 0.26 265 / 0.15)', color: 'oklch(72% 0.16 265)' }}>
            {workflow.trigger_type}
          </span>
        )}
      </div>
    </div>
  )
}

export function WorkflowsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => workflowsApi.list(1, 50),
  })

  const deleteMutation = useMutation({
    mutationFn: workflowsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      toast.success('Workflow deleted')
    },
  })

  const cloneMutation = useMutation({
    mutationFn: (id: string) => workflowsApi.clone(id),
    onSuccess: (cloned) => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
      toast.success(`Cloned: ${cloned.name}`)
      navigate(`/workflows/${cloned.id}`)
    },
  })

  const runMutation = useMutation({
    mutationFn: (id: string) => workflowsApi.execute(id, { triggered_by: 'manual' }),
    onSuccess: (run) => {
      toast.success(`Workflow run started: ${run.id.slice(0, 8)}`)
    },
    onError: () => toast.error('Failed to execute workflow'),
  })

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'oklch(97% 0.005 265)' }}>
            Workflows
          </h2>
          <p className="text-sm mt-0.5" style={{ color: 'oklch(55% 0.015 265)' }}>
            {data?.total ?? 0} total workflows
          </p>
        </div>
        <button
          onClick={() => navigate('/recordings')}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all duration-200 hover:scale-105"
          style={{
            background: 'linear-gradient(135deg, oklch(58% 0.26 265), oklch(72% 0.22 195))',
          }}
        >
          <Plus size={16} />
          New Workflow
        </button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-56 rounded-xl" />)}
        </div>
      ) : data?.items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div
            className="w-16 h-16 rounded-xl flex items-center justify-center mb-4"
            style={{ background: 'oklch(58% 0.26 265 / 0.1)', border: '1px solid oklch(58% 0.26 265 / 0.2)' }}
          >
            <Workflow size={28} style={{ color: 'oklch(58% 0.26 265)' }} />
          </div>
          <h3 className="text-base font-semibold mb-2" style={{ color: 'oklch(90% 0.008 265)' }}>
            No workflows yet
          </h3>
          <p className="text-sm max-w-sm mb-4" style={{ color: 'oklch(55% 0.015 265)' }}>
            Record a workflow first, then AI will extract intent and generate an automation for you.
          </p>
          <button
            onClick={() => navigate('/recordings')}
            className="text-sm font-medium"
            style={{ color: 'oklch(68% 0.16 265)' }}
          >
            Go to Recordings →
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data?.items.map((workflow) => (
            <WorkflowCard
              key={workflow.id}
              workflow={workflow}
              onDelete={(id) => deleteMutation.mutate(id)}
              onClone={(id) => cloneMutation.mutate(id)}
              onRun={(id) => runMutation.mutate(id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
