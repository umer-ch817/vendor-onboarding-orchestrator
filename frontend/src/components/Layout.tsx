/** Application shell with persistent sidebar and header. */

import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderKanban,
  FileText,
  AlertTriangle,
  CheckSquare,
  History,
  Settings,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import './Layout.css';

interface LayoutProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

const NAV_GROUPS = [
  {
    label: 'Core',
    items: [
      { path: '/', label: 'Dashboard', icon: LayoutDashboard },
      { path: '/cases', label: 'Vendor Cases', icon: FolderKanban },
      { path: '/documents', label: 'Documents', icon: FileText },
    ],
  },
  {
    label: 'Review Queues',
    items: [
      { path: '/risk', label: 'Risk Review', icon: AlertTriangle },
      { path: '/exceptions', label: 'Exception Queue', icon: AlertTriangle },
      { path: '/approvals', label: 'Approval Queue', icon: CheckSquare },
    ],
  },
  {
    label: 'Audit & Config',
    items: [
      { path: '/audit', label: 'Audit Timeline', icon: History },
      { path: '/settings', label: 'Settings', icon: Settings },
    ],
  },
] as const;

export function Layout({ collapsed = false, onToggleCollapse }: LayoutProps) {
  return (
    <div className={`app-shell ${collapsed ? 'collapsed' : ''}`}>
      <header className="app-header">
        <div className="flex items-center gap-3">
          {onToggleCollapse && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={onToggleCollapse}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </button>
          )}
          <h1 className="header-title">
            {collapsed ? 'VO' : 'Vendor Onboarding'}
          </h1>
        </div>
        <div className="header-actions">
          <span className="text-xs text-muted font-mono">
            Demo Dataset
          </span>
        </div>
      </header>

      <aside className="app-sidebar">
        <nav>
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="nav-section">
              <div className="nav-label">
                {collapsed ? group.label[0] : group.label}
              </div>
              {group.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-item ${isActive ? 'active' : ''}`
                  }
                  title={collapsed ? item.label : undefined}
                >
                  <item.icon size={18} aria-hidden="true" />
                  {!collapsed && <span>{item.label}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}