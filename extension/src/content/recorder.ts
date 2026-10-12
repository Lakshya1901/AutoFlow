/**
 * AutoFlow — Content Script: DOM Event Recorder
 *
 * Captures browser interactions as semantic events (not coordinates!).
 * Sent to the background service worker for batching and API delivery.
 */

// ─── Element Identification ───────────────────────────────────────────────────

interface ElementInfo {
  tag: string;
  role?: string;
  aria_label?: string;
  text?: string;
  placeholder?: string;
  element_id?: string;
  parent_context?: string;
}

/**
 * Extract semantic identification from a DOM element.
 * We deliberately avoid coordinates — we capture meaning, not position.
 */
function identifyElement(el: Element): ElementInfo {
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute('role') || inferRole(el) || undefined;
  const ariaLabel = el.getAttribute('aria-label') ||
    el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby')!)?.textContent?.trim() ||
    undefined;

  // Get visible text (limited to prevent huge strings)
  const rawText = (el as HTMLElement).innerText || el.textContent || '';
  const text = rawText.trim().slice(0, 200) || undefined;

  const placeholder = (el as HTMLInputElement).placeholder || undefined;
  const elementId = el.id || undefined;

  // Build parent context — the surrounding semantic context
  const parentContext = buildParentContext(el);

  return {
    tag,
    role,
    aria_label: ariaLabel || undefined,
    text,
    placeholder,
    element_id: elementId,
    parent_context: parentContext,
  };
}

function inferRole(el: Element): string | null {
  const tag = el.tagName.toLowerCase();
  const type = (el as HTMLInputElement).type?.toLowerCase();

  const implicit: Record<string, string> = {
    a: 'link',
    button: 'button',
    input: type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : type === 'submit' ? 'button' : 'textbox',
    select: 'listbox',
    textarea: 'textbox',
    nav: 'navigation',
    main: 'main',
    header: 'banner',
    footer: 'contentinfo',
    form: 'form',
    h1: 'heading', h2: 'heading', h3: 'heading',
    table: 'table',
    img: 'img',
  };

  return implicit[tag] || null;
}

/**
 * Build a semantic description of the element's surrounding context.
 * This helps reconstruct the element's meaning without coordinates.
 */
function buildParentContext(el: Element): string {
  const parts: string[] = [];
  let current: Element | null = el.parentElement;
  let depth = 0;

  while (current && depth < 4) {
    const label = current.getAttribute('aria-label') ||
      current.getAttribute('data-testid') ||
      current.id ||
      null;

    if (label) {
      parts.push(label);
    }

    const heading = current.querySelector('h1, h2, h3, h4');
    if (heading) {
      const headingText = (heading as HTMLElement).innerText?.trim().slice(0, 50);
      if (headingText) parts.push(`[${headingText}]`);
    }

    current = current.parentElement;
    depth++;
  }

  return parts.join(' > ').slice(0, 200);
}

// ─── Sensitive Data Filtering ─────────────────────────────────────────────────

const SENSITIVE_INPUT_TYPES = new Set(['password', 'credit-card', 'card-number', 'cvv', 'ssn']);
const SENSITIVE_ARIA_LABELS = ['password', 'card number', 'cvv', 'social security'];

function isSensitiveInput(el: HTMLInputElement): boolean {
  if (SENSITIVE_INPUT_TYPES.has(el.type?.toLowerCase())) return true;
  const label = el.getAttribute('aria-label')?.toLowerCase() || '';
  return SENSITIVE_ARIA_LABELS.some(s => label.includes(s));
}

function sanitizeValue(el: HTMLInputElement): string | undefined {
  if (isSensitiveInput(el)) return '[REDACTED]';
  const value = el.value?.trim();
  return value ? value.slice(0, 500) : undefined;
}

// ─── Event Filtering ──────────────────────────────────────────────────────────

// Avoid recording noise events
const NOISE_ELEMENT_TAGS = new Set(['html', 'body', 'head']);
const IGNORED_CLASSES = ['tooltip', 'popover', 'overlay'];

function shouldRecordClick(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  if (NOISE_ELEMENT_TAGS.has(tag)) return false;

  const cls = el.className?.toString() || '';
  if (IGNORED_CLASSES.some(c => cls.includes(c))) return false;

  // Must be interactive or have text
  const interactive = ['a', 'button', 'input', 'select', 'textarea', 'label'];
  const hasRole = el.getAttribute('role') !== null;
  const hasClickHandler = (el as HTMLElement).onclick !== null;

  return interactive.includes(tag) || hasRole || hasClickHandler;
}

// ─── Event Senders ────────────────────────────────────────────────────────────

function sendEvent(eventData: Record<string, unknown>): void {
  chrome.runtime.sendMessage({
    type: 'DOM_EVENT',
    event: {
      ...eventData,
      client_timestamp: Date.now(),
    },
  }).catch(() => {
    // Extension may not be recording — silently ignore
  });
}

// ─── Event Listeners ──────────────────────────────────────────────────────────

// Click events
document.addEventListener('click', (e: MouseEvent) => {
  const target = e.target as Element;
  if (!shouldRecordClick(target)) return;

  sendEvent({
    event_type: 'click',
    element: identifyElement(target),
  });
}, { capture: true, passive: true });

// Input/change events
document.addEventListener('change', (e: Event) => {
  const target = e.target as HTMLElement;
  const tag = target.tagName?.toLowerCase();
  if (!['input', 'select', 'textarea'].includes(tag)) return;

  const value = target instanceof HTMLSelectElement
    ? target.options[target.selectedIndex]?.text
    : sanitizeValue(target as HTMLInputElement);

  sendEvent({
    event_type: tag === 'select' ? 'select' : 'input',
    element: identifyElement(target),
    value,
  });
}, { capture: true, passive: true });

// Form submissions
document.addEventListener('submit', (e: SubmitEvent) => {
  const form = e.target as HTMLFormElement;
  sendEvent({
    event_type: 'form_submit',
    element: identifyElement(form),
    payload: {
      action: form.action,
      method: form.method,
    },
  });
}, { capture: true });

// Copy events (track what the user is copying)
document.addEventListener('copy', () => {
  const selected = window.getSelection()?.toString().slice(0, 200);
  sendEvent({
    event_type: 'copy',
    value: selected,
    payload: { selection_length: selected?.length || 0 },
  });
}, { passive: true });

// Paste events
document.addEventListener('paste', (e: ClipboardEvent) => {
  const pasted = e.clipboardData?.getData('text/plain')?.slice(0, 200);
  const target = e.target as Element;
  sendEvent({
    event_type: 'paste',
    element: identifyElement(target),
    value: pasted,
    payload: { paste_length: pasted?.length || 0 },
  });
}, { passive: true });

// ─── Message Listener (from service worker) ───────────────────────────────────

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'RECORDING_STARTED') {
    // Show visual indicator that recording is active
    showRecordingIndicator(true);
  } else if (message.type === 'RECORDING_STOPPED') {
    showRecordingIndicator(false);
  }
});

// ─── Visual Recording Indicator ───────────────────────────────────────────────

function showRecordingIndicator(active: boolean): void {
  const existingIndicator = document.getElementById('autoflow-recording-indicator');

  if (!active) {
    existingIndicator?.remove();
    return;
  }

  if (existingIndicator) return;

  const indicator = document.createElement('div');
  indicator.id = 'autoflow-recording-indicator';
  indicator.style.cssText = `
    position: fixed;
    top: 12px;
    right: 12px;
    background: rgba(239, 68, 68, 0.95);
    color: white;
    padding: 6px 12px;
    border-radius: 20px;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 12px;
    font-weight: 600;
    z-index: 2147483647;
    display: flex;
    align-items: center;
    gap: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    pointer-events: none;
  `;
  indicator.innerHTML = `
    <span style="width:8px;height:8px;background:white;border-radius:50%;animation:autoflow-pulse 1s ease-in-out infinite;"></span>
    AutoFlow Recording
  `;

  // Add pulse animation
  const style = document.createElement('style');
  style.textContent = `
    @keyframes autoflow-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.8); }
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(indicator);
}

console.log('[AutoFlow] Content script loaded on', window.location.hostname);
