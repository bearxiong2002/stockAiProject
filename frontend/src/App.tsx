import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import BackendGate from './components/BackendGate'
import MarketOverview from './pages/MarketOverview'
import StockAnalysis from './pages/StockAnalysis'
import Portfolio from './pages/Portfolio'
import Watchlist from './pages/Watchlist'
import Settings from './pages/Settings'

export default function App() {
  return (
    <BackendGate>
      <Layout>
        <Routes>
          <Route path="/" element={<MarketOverview />} />
          <Route path="/analysis" element={<StockAnalysis />} />
          <Route path="/analysis/:code" element={<StockAnalysis />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BackendGate>
  )
}
