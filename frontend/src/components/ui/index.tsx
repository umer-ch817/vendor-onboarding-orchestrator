/** Small presentational primitives shared across pages. */

import React from 'react';
import {
  AlertCircle,
  Inbox,
  Loader2,
  LucideIcon,
  X,
} from 'lucide-react';
import './ui.css';

// ==================== Badge ====================

export type BadgeTone =
  | 'critical'
  | 'high'
  | 'medium'
  | 'low'
  | 'neutral'
  | 'info'
  | 'success';

export function Badge({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: BadgeTone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

/** Human-readable label for a snake_case enum value. */
export function humanize(value?: string | null): string {
  if (!value) return '—';
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

// ==================== Card ====================

export function Card({
  title,
  subtitle,
  actions,
  children,
  padded = true,
  className = '',
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  padded?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'card-body' : ''}>{children}</div>
    </section>
  );
}

// ==================== PageHeader ====================

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        {breadcrumb && <div className="page-breadcrumb">{breadcrumb}</div>}
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

// ==================== MetricCard ====================

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
  definition,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: LucideIcon;
  tone?: BadgeTone;
  definition?: string;
}) {
  return (
    <div className={`metric-card metric-${tone}`} title={definition}>
      <div className="metric-card-top">
        <span className="metric-label">{label}</span>
        {Icon && <Icon size={16} className="metric-icon" aria-hidden="true" />}
      </div>
      <div className="metric-value">{value}</div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  );
}

// ==================== State views ====================

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state-view">
      <Loader2 size={22} className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title = 'Nothing here',
  description,
  action,
  icon: Icon = Inbox,
}: {
  title?: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="state-view state-empty">
      <Icon size={26} aria-hidden="true" />
      <strong>{title}</strong>
      {description && <span className="state-description">{description}</span>}
      {action && <div className="state-action">{action}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-view state-error">
      <AlertCircle size={22} aria-hidden="true" />
      <span>{message}</span>
      {onRetry && (
        <button className="btn btn-secondary btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

// ==================== Tabs ====================

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: Array<{ id: T; label: string; count?: number }>;
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={value === tab.id}
          className={`tab ${value === tab.id ? 'active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="tab-count">{tab.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

// ==================== Modal ====================

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  width = 560,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        style={{ maxWidth: width }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}

// ==================== Definition list ====================

export function DefinitionList({
  items,
}: {
  items: Array<{ label: string; value: React.ReactNode }>;
}) {
  return (
    <dl className="definition-list">
      {items.map((item) => (
        <div className="definition-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ==================== Progress bar ====================

export function ProgressBar({
  value,
  max = 100,
  tone = 'neutral',
  label,
}: {
  value: number;
  max?: number;
  tone?: 'neutral' | 'danger' | 'warning' | 'success';
  label?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="progress-wrap">
      <div className="progress-track">
        <div
          className={`progress-fill progress-${tone}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {label && <span className="progress-label">{label}</span>}
    </div>
  );
}
