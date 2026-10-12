/**
 * AutoFlow API Client
 * Type-safe REST client for all backend endpoints.
 */

import type {
  RecordingSession,
  RecordingSessionCreate,
  RawEventBatch,
  RecordingSessionWithActions,
  RecordingListResponse,
  WorkflowCreate,
  WorkflowUpdate,
  Workflow,
  WorkflowListResponse,
  WorkflowRunCreate,
  WorkflowRun,
  WorkflowRunListResponse,
  IntentExtractionRequest,
  IntentExtractionResponse,
  WorkflowGenerationRequest,
  WorkflowSuggestionResponse,
  AIHealthResponse,
  ConnectorSummary,
  ConnectorDetail,
} from '@/types/api';

// ─── Configuration ────────────────────────────────────────────────────────────

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const API_PREFIX = '/api/v1';

// ─── Error Handling ───────────────────────────────────────────────────────────

export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'APIError';
  }
}

// ─── Base Client ──────────────────────────────────────────────────────────────

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_URL}${API_PREFIX}${path}`;

  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new APIError(
      `API request failed: ${response.statusText}`,
      response.status,
      detail,
    );
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

const get = <T>(path: string) => request<T>(path, { method: 'GET' });

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) });

const del = (path: string) => request<void>(path, { method: 'DELETE' });

// ─── Recordings API ───────────────────────────────────────────────────────────

export const recordingsApi = {
  start: (data: RecordingSessionCreate) =>
    post<RecordingSession>('/recordings/start', data),

  ingestEvents: (sessionId: string, batch: RawEventBatch) =>
    post<{ session_id: string; events_ingested: number; total_events: number }>(
      `/recordings/${sessionId}/events`,
      batch,
    ),

  stop: (sessionId: string) =>
    post<RecordingSessionWithActions>(`/recordings/${sessionId}/stop`, {}),

  get: (sessionId: string) =>
    get<RecordingSessionWithActions>(`/recordings/${sessionId}`),

  list: (page = 1, pageSize = 20) =>
    get<RecordingListResponse>(`/recordings?page=${page}&page_size=${pageSize}`),

  delete: (sessionId: string) =>
    del(`/recordings/${sessionId}`),
};

// ─── AI API ───────────────────────────────────────────────────────────────────

export const aiApi = {
  extractIntent: (data: IntentExtractionRequest) =>
    post<IntentExtractionResponse>('/ai/extract-intent', data),

  generateWorkflow: (data: WorkflowGenerationRequest) =>
    post<WorkflowSuggestionResponse>('/ai/generate-workflow', data),

  naturalLanguageEdit: (workflowId: string, instruction: string) =>
    post('/ai/natural-language-edit', { workflow_id: workflowId, instruction }),

  health: () =>
    get<AIHealthResponse>('/ai/health'),

  getAnalysis: (analysisId: string) =>
    get<IntentExtractionResponse>(`/ai/analyses/${analysisId}`),

  getSuggestion: (suggestionId: string) =>
    get<WorkflowSuggestionResponse>(`/ai/suggestions/${suggestionId}`),
};

// ─── Workflows API ────────────────────────────────────────────────────────────

export const workflowsApi = {
  create: (data: WorkflowCreate) =>
    post<Workflow>('/workflows', data),

  list: (page = 1, pageSize = 20, status?: string) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (status) params.set('status', status);
    return get<WorkflowListResponse>(`/workflows?${params}`);
  },

  get: (workflowId: string) =>
    get<Workflow>(`/workflows/${workflowId}`),

  update: (workflowId: string, data: WorkflowUpdate) =>
    put<Workflow>(`/workflows/${workflowId}`, data),

  updateDefinition: (workflowId: string, definition: Record<string, unknown>) =>
    put<Workflow>(`/workflows/${workflowId}/definition`, { definition }),

  delete: (workflowId: string) =>
    del(`/workflows/${workflowId}`),

  clone: (workflowId: string, newName?: string) => {
    const params = newName ? `?new_name=${encodeURIComponent(newName)}` : '';
    return post<Workflow>(`/workflows/${workflowId}/clone${params}`);
  },

  createFromSuggestion: (suggestionId: string, name?: string) => {
    const params = name ? `?name=${encodeURIComponent(name)}` : '';
    return post<Workflow>(`/workflows/from-suggestion/${suggestionId}${params}`);
  },

  execute: (workflowId: string, data: WorkflowRunCreate) =>
    post<WorkflowRun>(`/workflows/${workflowId}/execute`, data),

  getRun: (runId: string) =>
    get<WorkflowRun>(`/workflows/runs/${runId}`),

  listRuns: (workflowId: string, page = 1, pageSize = 20) =>
    get<WorkflowRunListResponse>(
      `/workflows/${workflowId}/runs?page=${page}&page_size=${pageSize}`,
    ),

  approveRun: (runId: string) =>
    post<WorkflowRun>(`/workflows/runs/${runId}/approve`, {}),

  cancelRun: (runId: string) =>
    post<WorkflowRun>(`/workflows/runs/${runId}/cancel`, {}),
};

// ─── Connectors API ───────────────────────────────────────────────────────────

export const connectorsApi = {
  list: () => get<ConnectorSummary[]>('/connectors'),
  get: (connectorId: string) => get<ConnectorDetail>(`/connectors/${connectorId}`),
};

// ─── System API ───────────────────────────────────────────────────────────────

export const systemApi = {
  health: () =>
    fetch(`${API_URL}/health`).then((r) => r.json() as Promise<{ status: string; version: string }>),
};

// ─── WebSocket Manager ────────────────────────────────────────────────────────

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';

export function createRunWebSocket(
  runId: string,
  onMessage: (data: unknown) => void,
  onError?: (err: Event) => void,
): WebSocket {
  const ws = new WebSocket(`${WS_URL}/api/v1/workflows/runs/${runId}/live`);

  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // Non-JSON message (e.g., pong)
    }
  };

  ws.onerror = onError ?? (() => {});

  // Keep-alive ping
  const interval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('ping');
    } else {
      clearInterval(interval);
    }
  }, 30000);

  return ws;
}

export function createRecordingWebSocket(
  sessionId: string,
  onMessage: (data: unknown) => void,
): WebSocket {
  const ws = new WebSocket(`${WS_URL}/api/v1/recordings/${sessionId}/stream`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      console.warn('Ignoring non-JSON recording stream message');
    }
  };
  return ws;
}
