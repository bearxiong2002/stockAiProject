import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App'
import { useThemeStore } from './stores/theme'
import './styles/global.css'

dayjs.locale('zh-cn')

const TOKENS = {
  dark: {
    colorPrimary: '#e0524d',
    colorBgBase: '#0f1115',
    colorBgContainer: '#161a20',
    colorBgElevated: '#1d222a',
    colorBorder: '#2a2f38',
    colorText: '#d8dde6',
    borderRadius: 6
  },
  light: {
    colorPrimary: '#d93b36',
    colorBgBase: '#f5f6f8',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#e2e5ea',
    colorText: '#1f2430',
    borderRadius: 6
  }
}

function Root() {
  const mode = useThemeStore((s) => s.mode)
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: TOKENS[mode]
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
)
