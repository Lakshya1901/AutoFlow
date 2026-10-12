import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.floor((ms % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60_000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str
  return str.slice(0, maxLen) + '…'
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    active: 'oklch(68% 0.20 145)',
    recording: 'oklch(62% 0.24 25)',
    processing: 'oklch(74% 0.20 80)',
    completed: 'oklch(68% 0.20 145)',
    failed: 'oklch(62% 0.24 25)',
    cancelled: 'oklch(55% 0.015 265)',
    draft: 'oklch(60% 0.015 265)',
    paused: 'oklch(74% 0.20 80)',
    archived: 'oklch(50% 0.012 265)',
    queued: 'oklch(70% 0.18 210)',
    running: 'oklch(72% 0.22 195)',
    waiting_for_approval: 'oklch(74% 0.20 80)',
  }
  return colors[status] ?? 'oklch(60% 0.015 265)'
}

export function getActionTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    navigate: '🌐',
    tab_switch: '📑',
    click: '👆',
    input: '⌨️',
    form_submit: '📤',
    download: '⬇️',
    upload: '⬆️',
    copy: '📋',
    paste: '📌',
    search: '🔍',
    open_email: '📧',
    send_email: '📬',
    download_attachment: '📎',
    archive_document: '📁',
    login: '🔐',
    unknown: '❓',
  }
  return icons[type] ?? '⚡'
}
