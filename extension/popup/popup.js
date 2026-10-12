// UI Elements
const views = {
  setup: document.getElementById('setup-view'),
  idle: document.getElementById('idle-view'),
  recording: document.getElementById('recording-view'),
  processing: document.getElementById('processing-view')
};

const elements = {
  apiUrl: document.getElementById('api-url'),
  saveBtn: document.getElementById('save-settings'),
  recordingName: document.getElementById('recording-name'),
  startBtn: document.getElementById('start-btn'),
  stopBtn: document.getElementById('stop-btn'),
  sessionId: document.getElementById('session-id'),
  eventCount: document.getElementById('event-count'),
  duration: document.getElementById('duration'),
  startError: document.getElementById('start-error'),
  stopError: document.getElementById('stop-error')
};

let updateInterval;

// ─── View Management ──────────────────────────────────────────────────────────

function showView(viewName) {
  Object.values(views).forEach(v => v.classList.add('hidden'));
  views[viewName].classList.remove('hidden');
}

function formatDuration(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

async function updateState() {
  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_STATE' });
    
    if (response.isRecording && response.session) {
      showView('recording');
      elements.sessionId.textContent = response.session.sessionId.slice(0, 8);
      elements.eventCount.textContent = response.session.eventCount;
      
      const duration = Date.now() - response.session.startTime;
      elements.duration.textContent = formatDuration(duration);
      
      if (!updateInterval) {
        updateInterval = setInterval(updateState, 1000);
      }
    } else {
      showView('idle');
      if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
      }
    }
  } catch (err) {
    console.error('Failed to get state:', err);
  }
}

// ─── Event Handlers ───────────────────────────────────────────────────────────

elements.startBtn.addEventListener('click', async () => {
  elements.startBtn.disabled = true;
  elements.startError.classList.add('hidden');
  
  try {
    const response = await chrome.runtime.sendMessage({ 
      type: 'START_RECORDING',
      name: elements.recordingName.value.trim() || undefined
    });
    
    if (response.success) {
      elements.recordingName.value = '';
      await updateState();
    } else {
      elements.startError.textContent = response.error || 'Failed to start recording';
      elements.startError.classList.remove('hidden');
    }
  } catch (err) {
    elements.startError.textContent = 'Extension error: ' + err.message;
    elements.startError.classList.remove('hidden');
  } finally {
    elements.startBtn.disabled = false;
  }
});

elements.stopBtn.addEventListener('click', async () => {
  elements.stopBtn.disabled = true;
  elements.stopError.classList.add('hidden');
  showView('processing');
  
  if (updateInterval) {
    clearInterval(updateInterval);
    updateInterval = null;
  }
  
  try {
    const response = await chrome.runtime.sendMessage({ type: 'STOP_RECORDING' });
    
    if (response.success) {
      // Open the AutoFlow dashboard to the recording
      const settings = await chrome.runtime.sendMessage({ type: 'GET_SETTINGS' });
      const dashboardUrl = 'http://localhost:5173/recordings/' + response.result.id;
      chrome.tabs.create({ url: dashboardUrl });
      window.close(); // Close popup
    } else {
      showView('recording');
      elements.stopError.textContent = response.error || 'Failed to stop recording';
      elements.stopError.classList.remove('hidden');
    }
  } catch (err) {
    showView('recording');
    elements.stopError.textContent = 'Extension error: ' + err.message;
    elements.stopError.classList.remove('hidden');
  } finally {
    elements.stopBtn.disabled = false;
  }
});

elements.saveBtn.addEventListener('click', async () => {
  const apiUrl = elements.apiUrl.value.trim();
  if (!apiUrl) return;
  
  await chrome.runtime.sendMessage({ 
    type: 'SAVE_SETTINGS',
    settings: { apiUrl }
  });
  
  await checkConnectionAndInit();
});

// ─── Initialization ───────────────────────────────────────────────────────────

async function checkConnectionAndInit() {
  const settings = await chrome.runtime.sendMessage({ type: 'GET_SETTINGS' });
  
  // Very basic connection check to see if backend is running
  try {
    const res = await fetch(`${settings.apiUrl}/health`);
    if (res.ok) {
      updateState();
    } else {
      showView('setup');
      elements.apiUrl.value = settings.apiUrl;
    }
  } catch {
    showView('setup');
    elements.apiUrl.value = settings.apiUrl;
  }
}

// Initial load
checkConnectionAndInit();
