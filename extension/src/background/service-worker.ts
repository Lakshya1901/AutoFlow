/**
 * AutoFlow Chrome Extension — Background Service Worker
 *
 * Responsibilities:
 * - Maintain recording session state
 * - Relay events from content scripts to the AutoFlow API
 * - Batch events for efficiency
 * - Manage WebSocket connection to the API for live feedback
 */

// ─── Types ────────────────────────────────────────────────────────────────────

interface RecordedEvent {
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

interface RecordingSession {
  sessionId: string;
  startTime: number;
  status: 'active' | 'stopped' | 'processing';
  eventCount: number;
  apiUrl: string;
  apiKey: string;
}

interface ExtensionSettings {
  apiUrl: string;
  apiKey: string;
}

// ─── State ────────────────────────────────────────────────────────────────────

let currentSession: RecordingSession | null = null;
let eventBuffer: RecordedEvent[] = [];
let sequenceCounter = 0;
let flushTimer: ReturnType<typeof setTimeout> | null = null;

const FLUSH_INTERVAL_MS = 500;
const FLUSH_BATCH_SIZE = 50;
const DEFAULT_API_URL = 'http://localhost:8000';

// ─── Settings Management ──────────────────────────────────────────────────────

async function getSettings(): Promise<ExtensionSettings> {
  const result = await chrome.storage.sync.get(['apiUrl', 'apiKey']);
  return {
    apiUrl: result.apiUrl || DEFAULT_API_URL,
    apiKey: result.apiKey || '',
  };
}

// ─── API Communication ────────────────────────────────────────────────────────

async function apiRequest(
  endpoint: string,
  method: string,
  body?: unknown,
  apiUrl?: string,
  apiKey?: string,
): Promise<Response> {
  const settings = await getSettings();
  const baseUrl = apiUrl || settings.apiUrl;
  const key = apiKey || settings.apiKey;

  return fetch(`${baseUrl}${endpoint}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(key ? { 'X-AutoFlow-API-Key': key } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// ─── Session Management ───────────────────────────────────────────────────────

async function startRecording(name?: string): Promise<RecordingSession> {
  const settings = await getSettings();

  const response = await apiRequest(
    '/api/v1/recordings/start',
    'POST',
    {
      name: name || `Recording ${new Date().toLocaleString()}`,
      source: 'browser_extension',
      metadata: {
        extension_version: chrome.runtime.getManifest().version,
        user_agent: navigator.userAgent,
      },
    },
    settings.apiUrl,
    settings.apiKey,
  );

  if (!response.ok) {
    throw new Error(`Failed to start recording: ${response.statusText}`);
  }

  const data = await response.json();
  sequenceCounter = 0;
  eventBuffer = [];

  currentSession = {
    sessionId: data.id,
    startTime: Date.now(),
    status: 'active',
    eventCount: 0,
    apiUrl: settings.apiUrl,
    apiKey: settings.apiKey,
  };

  // Persist session to storage (survives service worker restarts)
  await chrome.storage.local.set({ currentSession });

  // Start flush timer
  scheduleFlush();

  // Notify all tabs that recording started
  await broadcastToContentScripts({ type: 'RECORDING_STARTED', sessionId: data.id });

  console.log('[AutoFlow] Recording started:', data.id);
  return currentSession;
}

async function stopRecording(): Promise<void> {
  if (!currentSession) {
    throw new Error('No active recording session');
  }

  // Flush any remaining buffered events
  await flushEvents();

  const response = await apiRequest(
    `/api/v1/recordings/${currentSession.sessionId}/stop`,
    'POST',
    {},
    currentSession.apiUrl,
    currentSession.apiKey,
  );

  if (!response.ok) {
    throw new Error(`Failed to stop recording: ${response.statusText}`);
  }

  const data = await response.json();
  currentSession.status = 'stopped';

  // Notify content scripts
  await broadcastToContentScripts({ type: 'RECORDING_STOPPED' });

  // Clear session
  currentSession = null;
  await chrome.storage.local.remove('currentSession');

  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }

  console.log('[AutoFlow] Recording stopped. Semantic actions:', data.semantic_action_count);
  return data;
}

// ─── Event Buffering ──────────────────────────────────────────────────────────

function addEvent(event: Omit<RecordedEvent, 'sequence_number'>): void {
  if (!currentSession || currentSession.status !== 'active') return;

  const enrichedEvent: RecordedEvent = {
    ...event,
    sequence_number: sequenceCounter++,
  };

  eventBuffer.push(enrichedEvent);
  currentSession.eventCount++;

  // Flush immediately if batch size reached
  if (eventBuffer.length >= FLUSH_BATCH_SIZE) {
    flushEvents().catch(console.error);
  }
}

function scheduleFlush(): void {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(() => {
    if (currentSession?.status === 'active') {
      flushEvents().catch(console.error);
      scheduleFlush();
    }
  }, FLUSH_INTERVAL_MS);
}

async function flushEvents(): Promise<void> {
  if (!currentSession || eventBuffer.length === 0) return;

  const eventsToSend = [...eventBuffer];
  eventBuffer = [];

  try {
    const response = await apiRequest(
      `/api/v1/recordings/${currentSession.sessionId}/events`,
      'POST',
      { events: eventsToSend },
      currentSession.apiUrl,
      currentSession.apiKey,
    );

    if (!response.ok) {
      // Put events back if flush failed
      eventBuffer = [...eventsToSend, ...eventBuffer];
      console.error('[AutoFlow] Failed to flush events:', response.statusText);
    } else {
      console.debug(`[AutoFlow] Flushed ${eventsToSend.length} events`);
      // Persist progress so a restarted worker continues the sequence instead of reusing numbers
      await chrome.storage.local.set({ currentSession });
    }
  } catch (err) {
    // Network error — put events back
    eventBuffer = [...eventsToSend, ...eventBuffer];
    console.error('[AutoFlow] Network error flushing events:', err);
  }
}

// ─── Content Script Communication ─────────────────────────────────────────────

async function broadcastToContentScripts(message: unknown): Promise<void> {
  const tabs = await chrome.tabs.query({});
  await Promise.allSettled(
    tabs
      .filter(tab => tab.id !== undefined)
      .map(tab => chrome.tabs.sendMessage(tab.id!, message).catch(() => {})),
  );
}

// ─── Web Navigation Events ────────────────────────────────────────────────────

chrome.webNavigation.onCompleted.addListener((details) => {
  if (details.frameId !== 0) return; // Main frame only
  addEvent({
    event_type: 'navigation',
    client_timestamp: Date.now(),
    url: details.url,
    payload: { frame_id: details.frameId },
  });
});

chrome.webNavigation.onTabReplaced.addListener((details) => {
  addEvent({
    event_type: 'tab_switch',
    client_timestamp: Date.now(),
    payload: { tab_id: details.tabId },
  });
});

// ─── Download Tracking ────────────────────────────────────────────────────────

chrome.downloads.onCreated.addListener((downloadItem) => {
  addEvent({
    event_type: 'download',
    client_timestamp: Date.now(),
    url: downloadItem.url,
    payload: {
      filename: downloadItem.filename,
      mime_type: downloadItem.mime,
      file_size: downloadItem.fileSize,
    },
  });
});

// ─── Message Handler (from content scripts and popup) ─────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handleAsync = async () => {
    switch (message.type) {
      case 'DOM_EVENT':
        addEvent({
          ...message.event,
          url: sender.tab?.url,
          page_title: sender.tab?.title,
        });
        return { success: true };

      case 'START_RECORDING':
        try {
          const session = await startRecording(message.name);
          return { success: true, session };
        } catch (err) {
          return { success: false, error: (err as Error).message };
        }

      case 'STOP_RECORDING':
        try {
          const result = await stopRecording();
          return { success: true, result };
        } catch (err) {
          return { success: false, error: (err as Error).message };
        }

      case 'GET_STATE':
        return {
          isRecording: currentSession?.status === 'active',
          session: currentSession,
          bufferedEvents: eventBuffer.length,
        };

      case 'GET_SETTINGS':
        return await getSettings();

      case 'SAVE_SETTINGS':
        await chrome.storage.sync.set(message.settings);
        return { success: true };

      default:
        return { success: false, error: 'Unknown message type' };
    }
  };

  handleAsync().then(sendResponse).catch((err) => {
    sendResponse({ success: false, error: err.message });
  });

  return true; // Keep channel open for async response
});

// ─── Restore Session on Service Worker Restart ────────────────────────────────
// MV3 workers are killed after ~30s idle and restarted on the next event, which
// wipes module state. Restore on every start, not only on browser startup.

async function restoreSession(): Promise<void> {
  if (currentSession) return;
  const stored = await chrome.storage.local.get('currentSession');
  const session = stored.currentSession as RecordingSession | undefined;
  if (session) {
    currentSession = session;
    sequenceCounter = session.eventCount;  // sequence_number and eventCount advance together
    scheduleFlush();
    console.log('[AutoFlow] Session restored after restart:', session.sessionId);
  }
}

chrome.runtime.onStartup.addListener(restoreSession);
void restoreSession();

console.log('[AutoFlow] Service worker initialized');
