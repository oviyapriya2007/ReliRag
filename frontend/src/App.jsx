import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

import AppShell from './components/AppShell'

import Documents from './pages/Documents'
import Ask from './pages/Ask'
import Evaluation from './pages/Evaluation'
import Comparison from './pages/Comparison'
import Analytics from './pages/Analytics'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/documents" element={<Documents />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="/comparison" element={<Comparison />} />
          <Route path="/analytics" element={<Analytics />} />

          <Route path="*" element={<Navigate to="/documents" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App