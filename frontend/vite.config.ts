import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

// 端口可由环境变量覆盖（start.sh 会注入），换机/避让占用端口时无需改本文件
const BACKEND_URL = process.env.STOCKPANEL_BACKEND_URL || 'http://localhost:18900'
const DEV_PORT = Number(process.env.STOCKPANEL_FRONTEND_PORT || 5173)

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': __dirname + 'src'
    }
  },
  server: {
    port: DEV_PORT,
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true
      }
    }
  }
})
