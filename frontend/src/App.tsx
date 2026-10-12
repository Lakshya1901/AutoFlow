import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { DashboardPage } from '@/pages/Dashboard'
import { RecordingsPage } from '@/pages/Recordings'
import { RecordingDetailPage } from '@/pages/RecordingDetail'
import { WorkflowsPage } from '@/pages/Workflows'
import { WorkflowEditorPage } from '@/pages/WorkflowEditor'
import { RunHistoryPage } from '@/pages/RunHistory'
import { SettingsPage } from '@/pages/Settings'

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/recordings" element={<RecordingsPage />} />
        <Route path="/recordings/:sessionId" element={<RecordingDetailPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/workflows/:workflowId" element={<WorkflowEditorPage />} />
        <Route path="/workflows/:workflowId/runs" element={<RunHistoryPage />} />
        <Route path="/runs" element={<RunHistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
