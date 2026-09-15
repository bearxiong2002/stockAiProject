import { create } from 'zustand'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'stockpanel-theme'

function initialMode(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* 隐私模式等场景忽略 */
  }
  return 'light'
}

/** 应用到 <html data-theme="...">，global.css 的 CSS 变量随之切换 */
export function applyTheme(mode: ThemeMode): void {
  document.documentElement.dataset.theme = mode
}

interface ThemeStore {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  toggle: () => void
}

const startMode = initialMode()
applyTheme(startMode)

export const useThemeStore = create<ThemeStore>((set, get) => ({
  mode: startMode,
  setMode: (mode) => {
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* 忽略持久化失败 */
    }
    applyTheme(mode)
    set({ mode })
  },
  toggle: () => get().setMode(get().mode === 'dark' ? 'light' : 'dark')
}))
