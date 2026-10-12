import { useState, useCallback, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  BackgroundVariant,
  Handle,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  ArrowLeft, Play, Settings2, Zap, Globe, MousePointerClick,
  Type, Download, GitBranch, Clock, CheckSquare,
  MessageSquare, Webhook, Code2
} from 'lucide-react'
import { toast } from 'sonner'
import { workflowsApi, aiApi } from '@/lib/api'
import type { WorkflowStep } from '@/types/api'

// ─── Step Type Metadata ───────────────────────────────────────────────────────

const STEP_TYPE_META: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  browser_navigate: { icon: Globe, color: 'oklch(72% 0.22 195)', label: 'Navigate' },
  browser_click: { icon: MousePointerClick, color: 'oklch(68% 0.20 145)', label: 'Click' },
  browser_input: { icon: Type, color: 'oklch(74% 0.20 80)', label: 'Input' },
  browser_download: { icon: Download, color: 'oklch(58% 0.26 265)', label: 'Download' },
  condition: { icon: GitBranch, color: 'oklch(70% 0.22 310)', label: 'Condition' },
  approval_checkpoint: { icon: CheckSquare, color: 'oklch(74% 0.20 80)', label: 'Approval' },
  notification: { icon: MessageSquare, color: 'oklch(68% 0.20 145)', label: 'Notify' },
  http_request: { icon: Webhook, color: 'oklch(72% 0.22 195)', label: 'HTTP' },
  wait: { icon: Clock, color: 'oklch(60% 0.015 265)', label: 'Wait' },
  connector_action: { icon: Code2, color: 'oklch(58% 0.26 265)', label: 'Action' },
}

// ─── Custom Workflow Node ─────────────────────────────────────────────────────

function WorkflowNode({ data }: { data: { step: WorkflowStep; isSelected?: boolean } }) {
  const { step } = data
  const meta = STEP_TYPE_META[step.step_type] ?? STEP_TYPE_META.connector_action
  const Icon = meta.icon

  return (
    <div
      className="min-w-[180px] rounded-xl transition-all duration-200"
      style={{
        background: 'oklch(16% 0.018 265 / 0.95)',
        border: `1px solid ${meta.color}30`,
        boxShadow: `0 0 0 0 ${meta.color}00`,
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: meta.color, width: 10, height: 10 }} />

      <div className="p-3">
        <div className="flex items-center gap-2 mb-2">
          <div
            className="p-1.5 rounded-lg"
            style={{ background: `${meta.color}15`, border: `1px solid ${meta.color}25` }}
          >
            <Icon size={13} style={{ color: meta.color }} />
          </div>
          <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: meta.color }}>
            {meta.label}
          </span>
        </div>
        <p className="text-sm font-medium" style={{ color: 'oklch(92% 0.006 265)' }}>
          {step.name}
        </p>
        {step.description && (
          <p className="text-xs mt-1 line-clamp-2" style={{ color: 'oklch(55% 0.015 265)' }}>
            {step.description}
          </p>
        )}
        {step.requires_approval && (
          <div className="mt-2 flex items-center gap-1">
            <CheckSquare size={11} style={{ color: 'oklch(74% 0.20 80)' }} />
            <span className="text-xs" style={{ color: 'oklch(74% 0.20 80)' }}>Requires approval</span>
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} style={{ background: meta.color, width: 10, height: 10 }} />
    </div>
  )
}

const nodeTypes = { workflowNode: WorkflowNode }

// ─── Workflow Editor Page ─────────────────────────────────────────────────────

export function WorkflowEditorPage() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [nlInstruction, setNlInstruction] = useState('')
  const [showNLPanel, setShowNLPanel] = useState(false)
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null)

  const { data: workflow, isLoading } = useQuery({
    queryKey: ['workflow', workflowId],
    queryFn: () => workflowsApi.get(workflowId!),
    enabled: !!workflowId,
  })

  // Build React Flow nodes and edges from workflow steps
  const initialNodes: Node[] = (workflow?.steps ?? []).map((step, idx) => ({
    id: step.step_key,
    type: 'workflowNode',
    position: {
      x: step.position_x ?? 250,
      y: step.position_y ?? idx * 140,
    },
    data: { step },
  }))

  // Same ordering as the engine: explicit next_step_key, otherwise the next step by position
  const ordered = [...(workflow?.steps ?? [])].sort((a, b) => a.position - b.position)
  const initialEdges: Edge[] = ordered.flatMap((step, idx) => {
    const target = step.next_step_key ?? ordered[idx + 1]?.step_key
    if (!target) return []
    return [{
      id: `${step.step_key}->${target}`,
      source: step.step_key,
      target,
      animated: true,
      style: { stroke: 'oklch(58% 0.26 265 / 0.6)', strokeWidth: 2 },
    }]
  })

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // Seed the canvas once the workflow loads; afterwards React Flow owns node/edge state
  useEffect(() => {
    setNodes(initialNodes)
    setEdges(initialEdges)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow])

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, animated: true }, eds)),
    [setEdges],
  )

  const runMutation = useMutation({
    mutationFn: () => workflowsApi.execute(workflowId!, { triggered_by: 'manual' }),
    onSuccess: (run) => {
      toast.success(`Run started: ${run.id.slice(0, 8)}`)
    },
    onError: () => toast.error('Failed to start run'),
  })

  const nlMutation = useMutation({
    mutationFn: () => aiApi.naturalLanguageEdit(workflowId!, nlInstruction),
    onSuccess: () => {
      toast.success('Workflow updated!')
      queryClient.invalidateQueries({ queryKey: ['workflow', workflowId] })
      setNlInstruction('')
      setShowNLPanel(false)
    },
    onError: () => toast.error('NL edit failed'),
  })

  if (isLoading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="skeleton h-12 rounded-xl" />
        <div className="skeleton h-[calc(100vh-200px)] rounded-xl" />
      </div>
    )
  }

  if (!workflow) return null

  return (
    <div className="flex flex-col h-[calc(100vh-88px)] -m-6 animate-fade-in">
      {/* Toolbar */}
      <div
        className="flex items-center gap-3 px-5 py-3 border-b flex-shrink-0"
        style={{
          background: 'oklch(12% 0.014 265 / 0.95)',
          borderColor: 'oklch(25% 0.020 265 / 0.4)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <button
          onClick={() => navigate('/workflows')}
          className="p-2 rounded-lg transition-colors flex-shrink-0"
          style={{ color: 'oklch(60% 0.015 265)' }}
        >
          <ArrowLeft size={16} />
        </button>

        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold truncate" style={{ color: 'oklch(95% 0.005 265)' }}>
            {workflow.name}
          </h2>
          <div className="flex items-center gap-2">
            <span className={`status-dot ${workflow.status}`} />
            <span className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}>
              v{workflow.version} · {workflow.steps?.length ?? 0} steps
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* NL Edit */}
          <button
            onClick={() => setShowNLPanel(!showNLPanel)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{
              background: showNLPanel ? 'oklch(58% 0.26 265 / 0.2)' : 'oklch(16% 0.018 265 / 0.6)',
              border: `1px solid ${showNLPanel ? 'oklch(58% 0.26 265 / 0.4)' : 'oklch(28% 0.020 265 / 0.4)'}`,
              color: showNLPanel ? 'oklch(78% 0.16 265)' : 'oklch(65% 0.015 265)',
            }}
          >
            <Zap size={13} />
            AI Edit
          </button>

          {/* Run */}
          <button
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-all hover:scale-105"
            style={{
              background: 'linear-gradient(135deg, oklch(58% 0.26 265), oklch(72% 0.22 195))',
            }}
          >
            <Play size={13} />
            {runMutation.isPending ? 'Starting…' : 'Run'}
          </button>
        </div>
      </div>

      {/* NL Edit Panel */}
      {showNLPanel && (
        <div
          className="px-5 py-3 border-b flex-shrink-0"
          style={{
            background: 'oklch(14% 0.016 265 / 0.9)',
            borderColor: 'oklch(58% 0.26 265 / 0.2)',
          }}
        >
          <div className="flex items-center gap-2">
            <Zap size={13} style={{ color: 'oklch(72% 0.22 195)' }} />
            <span className="text-xs font-medium" style={{ color: 'oklch(70% 0.012 265)' }}>
              Natural Language Edit
            </span>
          </div>
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              value={nlInstruction}
              onChange={(e) => setNlInstruction(e.target.value)}
              placeholder='e.g., "Run this every weekday at 9am" or "Add approval before upload"'
              className="flex-1 px-3 py-2 text-sm rounded-lg outline-none"
              style={{
                background: 'oklch(12% 0.014 265)',
                border: '1px solid oklch(30% 0.020 265 / 0.5)',
                color: 'oklch(90% 0.008 265)',
              }}
              onKeyDown={(e) => e.key === 'Enter' && nlMutation.mutate()}
            />
            <button
              onClick={() => nlMutation.mutate()}
              disabled={!nlInstruction.trim() || nlMutation.isPending}
              className="px-4 py-2 rounded-lg text-xs font-semibold text-white transition-all"
              style={{ background: 'oklch(58% 0.26 265)' }}
            >
              {nlMutation.isPending ? '…' : 'Apply'}
            </button>
          </div>
        </div>
      )}

      {/* React Flow Canvas */}
      <div className="flex-1 relative">
        {workflow.steps?.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div style={{ color: 'oklch(40% 0.015 265)' }}>
              <Settings2 size={48} className="mx-auto mb-4 opacity-30" />
              <p className="text-sm text-center">This workflow has no steps yet.</p>
              <p className="text-xs text-center mt-1" style={{ color: 'oklch(35% 0.012 265)' }}>
                Steps are auto-generated when you accept an AI suggestion.
              </p>
            </div>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            onNodeClick={(_, node) => {
              const step = workflow.steps?.find((s) => s.step_key === node.id)
              setSelectedStep(step ?? null)
            }}
            fitView
            fitViewOptions={{ padding: 0.3 }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="oklch(30% 0.015 265)"
            />
            <Controls />
            <MiniMap
              nodeColor={() => 'oklch(58% 0.26 265)'}
              maskColor="oklch(10% 0.012 265 / 0.8)"
            />
          </ReactFlow>
        )}

        {/* Step Detail Panel */}
        {selectedStep && (
          <div
            className="absolute top-4 right-4 w-72 rounded-xl p-4 overflow-y-auto max-h-[calc(100%-2rem)]"
            style={{
              background: 'oklch(14% 0.016 265 / 0.97)',
              border: '1px solid oklch(35% 0.025 265 / 0.3)',
              backdropFilter: 'blur(20px)',
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold" style={{ color: 'oklch(95% 0.005 265)' }}>
                Step Details
              </h4>
              <button
                onClick={() => setSelectedStep(null)}
                className="text-xs" style={{ color: 'oklch(55% 0.015 265)' }}
              >
                ✕
              </button>
            </div>
            <div className="space-y-3">
              {[
                { label: 'Key', value: selectedStep.step_key },
                { label: 'Type', value: selectedStep.step_type },
                { label: 'Connector', value: selectedStep.connector ?? '—' },
                { label: 'On Error', value: selectedStep.on_error },
                { label: 'Retries', value: String(selectedStep.max_retries) },
                { label: 'Approval', value: selectedStep.requires_approval ? 'Required' : 'Not required' },
              ].map(({ label, value }) => (
                <div key={label}>
                  <p className="text-xs mb-1" style={{ color: 'oklch(55% 0.015 265)' }}>{label}</p>
                  <p className="text-sm font-medium" style={{ color: 'oklch(85% 0.008 265)' }}>{value}</p>
                </div>
              ))}
              {selectedStep.config && Object.keys(selectedStep.config).length > 0 && (
                <div>
                  <p className="text-xs mb-1" style={{ color: 'oklch(55% 0.015 265)' }}>Config</p>
                  <pre
                    className="text-xs overflow-auto max-h-32 rounded p-2"
                    style={{ background: 'oklch(10% 0.012 265)', color: 'oklch(72% 0.22 195)' }}
                  >
                    {JSON.stringify(selectedStep.config, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
