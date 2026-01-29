import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from '@/components/ui/toast'
import { BatchPage } from '@/pages/BatchPage'

function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/batch" replace />} />
          <Route path="/batch" element={<BatchPage />} />
        </Routes>
      </ToastProvider>
    </BrowserRouter>
  )
}

export default App
