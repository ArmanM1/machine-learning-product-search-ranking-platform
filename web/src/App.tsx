import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { ComparisonPage } from './pages/ComparisonPage'
import { EvaluationPage } from './pages/EvaluationPage'
import { ExperimentPage } from './pages/ExperimentPage'
import { FailuresPage } from './pages/FailuresPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OverviewPage } from './pages/OverviewPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ComparisonPage />} />
        <Route path="compare" element={<ComparisonPage />} />
        <Route path="evidence" element={<OverviewPage />} />
        <Route path="overview" element={<Navigate replace to="/evidence" />} />
        <Route path="evaluation" element={<EvaluationPage />} />
        <Route path="failures" element={<FailuresPage />} />
        <Route path="experiment" element={<ExperimentPage />} />
        <Route path="experiments/:runId" element={<ExperimentPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
