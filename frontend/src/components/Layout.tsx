import { ReactNode, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Menu, MenuProps, Tooltip } from 'antd'
import {
  BulbOutlined,
  DashboardOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SettingOutlined,
  StarOutlined,
  WalletOutlined
} from '@ant-design/icons'
import { useBackendStore } from '@/stores/backend'
import { useThemeStore } from '@/stores/theme'

const MENU_ITEMS: MenuProps['items'] = [
  { key: '/', icon: <DashboardOutlined />, label: '大盘概览' },
  { key: '/analysis', icon: <LineChartOutlined />, label: '股票分析' },
  { key: '/portfolio', icon: <WalletOutlined />, label: '持仓管理' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' }
]

/** 路由 → 浏览器标签页标题 */
const PAGE_TITLES: Record<string, string> = {
  '/': '大盘概览',
  '/analysis': '股票分析',
  '/portfolio': '持仓管理',
  '/watchlist': '自选股',
  '/settings': '设置'
}

function pageTitle(pathname: string): string {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname]
  for (const [path, title] of Object.entries(PAGE_TITLES)) {
    if (path !== '/' && pathname.startsWith(path)) return title
  }
  return '大盘概览'
}

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const health = useBackendStore((s) => s.health)
  const mode = useThemeStore((s) => s.mode)
  const toggleTheme = useThemeStore((s) => s.toggle)
  const [collapsed, setCollapsed] = useState(false)

  // 动态标签页标题
  useEffect(() => {
    document.title = `${pageTitle(location.pathname)} · StockPanel`
  }, [location.pathname])

  return (
    <div className="app-shell">
      <div className="app-body">
        <aside className={`app-sidebar${collapsed ? ' collapsed' : ''}`}>
          <div className="app-sidebar-header">
            {!collapsed && <div className="app-sidebar-logo">StockPanel</div>}
            <Tooltip title={collapsed ? '展开侧边栏' : '收起侧边栏'} placement="right">
              <span
                className="app-sidebar-collapse"
                style={collapsed ? { margin: '0 auto' } : undefined}
                onClick={() => setCollapsed((v) => !v)}
              >
                {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              </span>
            </Tooltip>
          </div>
          <Menu
            theme={mode === 'dark' ? 'dark' : 'light'}
            mode="inline"
            inlineCollapsed={collapsed}
            selectedKeys={[location.pathname]}
            items={MENU_ITEMS}
            style={{ borderInlineEnd: 'none', background: 'transparent' }}
            onClick={({ key }) => navigate(key)}
          />
          <div className="app-sidebar-footer">
            <Tooltip title={mode === 'dark' ? '切换到亮色主题' : '切换到暗色主题'}>
              <span className="app-sidebar-collapse" onClick={toggleTheme}>
                {mode === 'dark' ? <BulbOutlined /> : <MoonOutlined />}
              </span>
            </Tooltip>
            {!collapsed && health ? (
              <span className="backend-version">
                {mode === 'dark' ? '暗色' : '亮色'} · v{health.version}
              </span>
            ) : null}
          </div>
        </aside>
        <main className="app-content">{children}</main>
      </div>
    </div>
  )
}
