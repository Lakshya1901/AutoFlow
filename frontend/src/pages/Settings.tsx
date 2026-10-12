import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Zap, ExternalLink, CheckCircle, AlertTriangle } from 'lucide-react'
import { aiApi } from '@/lib/api'

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="glass-card p-6">
      <h3 className="text-sm font-semibold mb-5" style={{ color: 'oklch(90% 0.008 265)' }}>
        {title}
      </h3>
      {children}
    </div>
  )
}

function SettingRow({ label, description, children }: {
  label: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-6 py-3 border-b last:border-0"
      style={{ borderColor: 'oklch(25% 0.020 265 / 0.3)' }}>
      <div>
        <p className="text-sm font-medium" style={{ color: 'oklch(85% 0.008 265)' }}>{label}</p>
        {description && (
          <p className="text-xs mt-0.5" style={{ color: 'oklch(55% 0.015 265)' }}>{description}</p>
        )}
      </div>
      <div className="flex-shrink-0">
        {children}
      </div>
    </div>
  )
}

export function SettingsPage() {
  const [apiUrl, setApiUrl] = useState(import.meta.env.VITE_API_URL ?? 'http://localhost:8000')

  const { data: aiHealth, isLoading: aiLoading, refetch: checkAI } = useQuery({
    queryKey: ['ai-health'],
    queryFn: aiApi.health,
    enabled: false, // Manual only
    retry: false,
  })

  const handleCheckAI = async () => {
    await checkAI()
  }

  return (
    <div className="space-y-6 max-w-2xl animate-fade-in">
      <div>
        <h2 className="text-lg font-semibold" style={{ color: 'oklch(97% 0.005 265)' }}>Settings</h2>
        <p className="text-sm mt-0.5" style={{ color: 'oklch(55% 0.015 265)' }}>
          Configure AutoFlow backend, AI provider, and integration settings.
        </p>
      </div>

      {/* Backend Connection */}
      <SettingsSection title="Backend Connection">
        <SettingRow
          label="API URL"
          description="The URL where your AutoFlow backend is running"
        >
          <input
            type="text"
            value={apiUrl}
            onChange={(e) => setApiUrl(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-sm w-56 outline-none"
            style={{
              background: 'oklch(12% 0.014 265)',
              border: '1px solid oklch(30% 0.020 265 / 0.5)',
              color: 'oklch(90% 0.008 265)',
            }}
          />
        </SettingRow>
      </SettingsSection>

      {/* AI Provider */}
      <SettingsSection title="AI Provider">
        <div className="mb-4 p-3 rounded-lg" style={{ background: 'oklch(14% 0.016 265 / 0.8)', border: '1px solid oklch(28% 0.020 265 / 0.3)' }}>
          <p className="text-xs" style={{ color: 'oklch(65% 0.015 265)' }}>
            AI provider is configured via environment variables in your <code style={{ color: 'oklch(72% 0.22 195)' }}>.env</code> file.
            Set <code style={{ color: 'oklch(72% 0.22 195)' }}>AI_PROVIDER</code> to one of: <code>ollama</code> (default), <code>openai</code>, <code>anthropic</code>, <code>gemini</code>, <code>groq</code>.
          </p>
        </div>

        <SettingRow
          label="AI Provider Health"
          description="Test if your configured AI provider is reachable"
        >
          <div className="flex items-center gap-2">
            {aiHealth && (
              <div className="flex items-center gap-1.5">
                {aiHealth.status === 'healthy'
                  ? <CheckCircle size={14} style={{ color: 'oklch(68% 0.20 145)' }} />
                  : <AlertTriangle size={14} style={{ color: 'oklch(62% 0.24 25)' }} />}
                <span className="text-xs" style={{ color: aiHealth.status === 'healthy' ? 'oklch(68% 0.20 145)' : 'oklch(62% 0.24 25)' }}>
                  {aiHealth.status === 'healthy' ? `${aiHealth.provider} · ${aiHealth.model}` : 'Unreachable'}
                </span>
              </div>
            )}
            <button
              onClick={handleCheckAI}
              disabled={aiLoading}
              className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              style={{
                background: 'oklch(58% 0.26 265 / 0.15)',
                border: '1px solid oklch(58% 0.26 265 / 0.25)',
                color: 'oklch(72% 0.16 265)',
              }}
            >
              {aiLoading ? 'Checking…' : 'Check Health'}
            </button>
          </div>
        </SettingRow>
      </SettingsSection>

      {/* Chrome Extension */}
      <SettingsSection title="Chrome Extension">
        <div className="flex items-start gap-3 p-3 rounded-lg"
          style={{ background: 'oklch(58% 0.26 265 / 0.08)', border: '1px solid oklch(58% 0.26 265 / 0.15)' }}>
          <Zap size={20} style={{ color: 'oklch(68% 0.16 265)', marginTop: 2 }} />
          <div>
            <p className="text-sm font-medium" style={{ color: 'oklch(85% 0.008 265)' }}>
              AutoFlow Recorder Extension
            </p>
            <p className="text-xs mt-1" style={{ color: 'oklch(58% 0.015 265)' }}>
              Load the extension from <code style={{ color: 'oklch(72% 0.22 195)' }}>extension/</code> folder as an unpacked extension in Chrome Developer Mode.
            </p>
            <a
              href="chrome://extensions"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs mt-2"
              style={{ color: 'oklch(68% 0.16 265)' }}
            >
              Open Chrome Extensions <ExternalLink size={11} />
            </a>
          </div>
        </div>
      </SettingsSection>

      {/* Docker Setup */}
      <SettingsSection title="Infrastructure">
        <div className="p-3 rounded-lg font-mono text-xs overflow-x-auto"
          style={{ background: 'oklch(10% 0.012 265)', border: '1px solid oklch(25% 0.020 265 / 0.3)', color: 'oklch(72% 0.22 195)' }}>
          <pre>{`# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f backend`}</pre>
        </div>
      </SettingsSection>
    </div>
  )
}
