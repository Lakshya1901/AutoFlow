/**
 * AutoFlow — Shared TypeScript Types
 * Mirrors the backend Pydantic schemas for type safety.
 */

// ─── Enums ────────────────────────────────────────────────────────────────────

export type RecordingStatus = 'active' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type RecordingSource = 'browser_extension' | 'desktop_agent' | 'api';
export type SemanticActionType =
  | 'navigate' | 'tab_switch'
  | 'click' | 'input' | 'form_submit' | 'select' | 'scroll'
  | 'download' | 'upload' | 'file_create' | 'file_rename' | 'file_move' | 'file_delete'
  | 'copy' | 'paste' | 'extract_data'
  | 'open_email' | 'send_email' | 'download_attachment' | 'search'
  | 'archive_document' | 'fill_form' | 'login'
  | 'unknown';

export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived';
export type WorkflowRunStatus =
  | 'queued' | 'running' | 'waiting_for_approval'
  | 'completed' | 'failed' | 'cancelled' | 'skipped';
export type StepType =
  | 'browser_navigate' | 'browser_click' | 'browser_input' | 'browser_extract'
  | 'browser_download' | 'browser_upload' | 'browser_wait'
  | 'file_rename' | 'file_move' | 'file_copy' | 'file_create_folder' | 'file_delete'
  | 'data_transform' | 'data_extract'
  | 'condition' | 'loop' | 'approval_checkpoint' | 'wait'
  | 'notification' | 'webhook' | 'http_request'
  | 'connector_action';
export type TriggerType = 'manual' | 'schedule' | 'webhook' | 'event';
export type VariableType = 'string' | 'number' | 'boolean' | 'date' | 'email' | 'file_path' | 'url' | 'json';

// ─── Recording Types ──────────────────────────────────────────────────────────

export interface SemanticAction {
  id: string;
  session_id: string;
  action_type: SemanticActionType;
  description: string;
  sequence_number: number;
  url?: string;
  application?: string;
  extracted_data?: Record<string, unknown>;
  confidence?: number;
  created_at: string;
}

export interface RecordingSession {
  id: string;
  name?: string;
  description?: string;
  source: RecordingSource;
  status: RecordingStatus;
  raw_event_count: number;
  semantic_action_count: number;
  duration_seconds?: number;
  error_message?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RecordingSessionWithActions extends RecordingSession {
  semantic_actions: SemanticAction[];
}

export interface RecordingSessionCreate {
  name?: string;
  description?: string;
  source?: RecordingSource;
  metadata?: Record<string, unknown>;
}

export interface RawEventBatch {
  events: RawEvent[];
}

export interface RawEvent {
  event_type: string;
  sequence_number: number;
  client_timestamp: number;
  url?: string;
  page_title?: string;
  element?: {
    tag?: string;
    role?: string;
    aria_label?: string;
    text?: string;
    placeholder?: string;
    element_id?: string;
    parent_context?: string;
  };
  value?: string;
  payload?: Record<string, unknown>;
}

export interface RecordingListResponse {
  items: RecordingSession[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

// ─── AI Types ─────────────────────────────────────────────────────────────────

export interface IntentExtractionRequest {
  session_id: string;
}

export interface IntentExtractionResponse {
  id: string;
  session_id: string;
  intent: string;
  goal_summary: string;
  steps_summary?: string[];
  detected_variables?: DetectedVariable[];
  suggested_name?: string;
  notes?: string;
  confidence: number;
  ai_provider: string;
  ai_model: string;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
}

export interface DetectedVariable {
  name: string;
  description: string;
  example?: string;
  type?: string;
}

export interface WorkflowGenerationRequest {
  intent_analysis_id: string;
}

export interface WorkflowSuggestionResponse {
  id: string;
  session_id: string;
  intent_analysis_id: string;
  workflow_definition: Record<string, unknown>;
  accepted: boolean;
  workflow_id?: string;
  ai_provider: string;
  ai_model: string;
  created_at: string;
}

export interface AIHealthResponse {
  status: 'healthy' | 'unhealthy';
  provider: string;
  model: string;
  response?: string;
  error?: string;
}

// ─── Workflow Types ───────────────────────────────────────────────────────────

export interface WorkflowVariable {
  id: string;
  workflow_id: string;
  name: string;
  display_name?: string;
  description?: string;
  variable_type: VariableType;
  default_value?: string;
  is_required: boolean;
  is_secret: boolean;
  created_at: string;
}

export interface WorkflowStep {
  id: string;
  workflow_id: string;
  step_key: string;
  name: string;
  description?: string;
  step_type: StepType;
  connector?: string;
  config?: Record<string, unknown>;
  position: number;
  position_x?: number;
  position_y?: number;
  next_step_key?: string;
  on_success_step_key?: string;
  on_failure_step_key?: string;
  condition?: string;
  on_error: string;
  max_retries: number;
  requires_approval: boolean;
  outputs?: Record<string, string>;
  is_disabled: boolean;
  notes?: string;
  created_at: string;
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  version: number;
  source_recording_id?: string;
  trigger_type: TriggerType;
  trigger_config?: Record<string, unknown>;
  definition?: Record<string, unknown>;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  avg_duration_ms: number;
  estimated_time_saved_minutes: number;
  tags?: string[];
  created_at: string;
  updated_at: string;
  steps: WorkflowStep[];
  variables: WorkflowVariable[];
}

export interface WorkflowCreate {
  name: string;
  description?: string;
  trigger_type?: TriggerType;
  trigger_config?: Record<string, unknown>;
  steps?: Partial<WorkflowStep>[];
  variables?: Partial<WorkflowVariable>[];
  tags?: string[];
  definition?: Record<string, unknown>;
  source_recording_id?: string;
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  status?: WorkflowStatus;
  trigger_type?: TriggerType;
  trigger_config?: Record<string, unknown>;
  tags?: string[];
}

export interface WorkflowListResponse {
  items: Workflow[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface WorkflowRunCreate {
  variable_values?: Record<string, unknown>;
  triggered_by?: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: WorkflowRunStatus;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  variable_values?: Record<string, unknown>;
  current_step_key?: string;
  completed_steps?: string[];
  outputs?: Record<string, unknown>;
  error_message?: string;
  error_step_key?: string;
  triggered_by: string;
  step_logs?: StepLog[];
  created_at: string;
}

export interface StepLog {
  step_key: string;
  step_name: string;
  success: boolean;
  outputs?: Record<string, unknown>;
  error?: string;
  timestamp: string;
}

export interface WorkflowRunListResponse {
  items: WorkflowRun[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

// ─── Connector Types ──────────────────────────────────────────────────────────

export interface ConnectorSummary {
  connector_id: string;
  display_name: string;
  description: string;
  action_count: number;
}

export interface ConnectorDetail extends ConnectorSummary {
  actions: ConnectorAction[];
}

export interface ConnectorAction {
  name: string;
  display_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  requires_auth: boolean;
  is_destructive: boolean;
}
