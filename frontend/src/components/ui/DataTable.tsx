/** Reusable data table with sorting, pagination, and row selection. */

import React, { useMemo, useState } from 'react';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import './DataTable.css';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T, index: number) => React.ReactNode;
  sortable?: boolean;
  width?: string;
  align?: 'left' | 'center' | 'right';
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (row: T) => string | number;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  sortable?: boolean;
  defaultSort?: { key: string; direction: 'asc' | 'desc' };
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    onChange: (page: number, pageSize: number) => void;
  };
  selection?: {
    selected: Set<string | number>;
    onChange: (selected: Set<string | number>) => void;
    getRowKey: (row: T) => string | number;
  };
  rowClassName?: (row: T) => string;
}

function SortIcon({ direction }: { direction: 'asc' | 'desc' | 'none' }) {
  if (direction === 'asc') return <ChevronUp size={14} />;
  if (direction === 'desc') return <ChevronDown size={14} />;
  return <ChevronsUpDown size={14} className="text-muted" />;
}

function SelectAllCheckbox({
  data,
  getRowKey,
  selected,
  onChange,
}: {
  data: any[];
  getRowKey: (row: any) => string | number;
  selected: Set<string | number>;
  onChange: (selected: Set<string | number>) => void;
}) {
  const keys = data.map(getRowKey);
  const allSelected = keys.length > 0 && keys.every((k) => selected.has(k));
  const someSelected = keys.some((k) => selected.has(k));

  const handleClick = () => {
    const next = new Set(selected);
    if (allSelected) {
      keys.forEach((k) => next.delete(k));
    } else {
      keys.forEach((k) => next.add(k));
    }
    onChange(next);
  };

  return (
    <input
      type="checkbox"
      checked={allSelected}
      // `indeterminate` is a DOM property with no JSX attribute equivalent;
      // it has to be set on the element itself.
      ref={(el) => {
        if (el) el.indeterminate = someSelected && !allSelected;
      }}
      onChange={handleClick}
      className="table-checkbox"
      aria-label={allSelected ? 'Deselect all' : 'Select all'}
    />
  );
}

export function DataTable<T>({
  columns,
  data,
  keyExtractor,
  loading = false,
  emptyMessage = 'No data',
  onRowClick,
  sortable = true,
  defaultSort,
  pagination,
  selection,
  rowClassName,
}: DataTableProps<T>) {
  const [sortConfig, setSortConfig] = useState<{
    key: string;
    direction: 'asc' | 'desc';
  } | null>(defaultSort || null);

  const sortedData = useMemo(() => {
    if (!sortConfig || !sortable) return data;
    const { key, direction } = sortConfig;
    const column = columns.find((c) => c.key === key);
    if (!column?.sortable) return data;

    return [...data].sort((a, b) => {
      const aVal = (a as any)[key];
      const bVal = (b as any)[key];
      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      const cmp = aVal < bVal ? -1 : 1;
      return direction === 'asc' ? cmp : -cmp;
    });
  }, [data, sortConfig, columns, sortable]);

  const handleSort = (key: string) => {
    const column = columns.find((c) => c.key === key);
    if (!column?.sortable) return;

    setSortConfig((prev) => {
      if (prev?.key === key && prev.direction === 'asc') {
        return { key, direction: 'desc' };
      }
      return { key, direction: 'asc' };
    });
  };

  const displayedData = pagination ? sortedData : sortedData;

  if (loading) {
    return (
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} style={{ width: col.width }}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={columns.length} className="text-center text-muted py-8">
                Loading...
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="table-container">
      <table className="table">
        <thead>
          <tr>
            {selection && (
              <th style={{ width: '40px' }}>
                <SelectAllCheckbox
                  data={displayedData}
                  getRowKey={selection.getRowKey}
                  selected={selection.selected}
                  onChange={selection.onChange}
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  width: col.width,
                  textAlign: col.align || 'left',
                  cursor: sortable && col.sortable ? 'pointer' : 'default',
                }}
                onClick={() => handleSort(col.key)}
                className={sortable && col.sortable ? 'sortable' : ''}
              >
                <div className="th-content">
                  <span>{col.header}</span>
                  {sortable && col.sortable && (
                    <SortIcon
                      direction={
                        sortConfig?.key === col.key
                          ? sortConfig.direction
                          : 'none'
                      }
                    />
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayedData.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (selection ? 1 : 0)}
                className="text-center text-muted py-8"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            displayedData.map((row, index) => (
              <tr
                key={keyExtractor(row)}
                onClick={() => onRowClick?.(row)}
                className={`${rowClassName?.(row) || ''} ${
                  onRowClick ? 'clickable' : ''
                }`}
              >
                {selection && (
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={selection.selected.has(selection.getRowKey(row))}
                      onChange={(e) => {
                        e.stopPropagation();
                        const next = new Set(selection.selected);
                        const key = selection.getRowKey(row);
                        if (e.target.checked) next.add(key);
                        else next.delete(key);
                        selection.onChange(next);
                      }}
                      className="table-checkbox"
                    />
                  </td>
                )}
                {columns.map((col) => (
                  <td
                    key={col.key}
                    style={{
                      textAlign: col.align || 'left',
                    }}
                  >
                    {col.render
                      ? col.render(row, index)
                      : String((row as any)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {pagination && (
        <div className="table-pagination">
          <div className="pagination-info">
            Showing {((pagination.page - 1) * pagination.pageSize) + 1} to{' '}
            {Math.min(pagination.page * pagination.pageSize, pagination.total)} of{' '}
            {pagination.total}
          </div>
          <div className="pagination-controls">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() =>
                pagination.onChange(pagination.page - 1, pagination.pageSize)
              }
              disabled={pagination.page <= 1}
            >
              Previous
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() =>
                pagination.onChange(pagination.page + 1, pagination.pageSize)
              }
              disabled={pagination.page * pagination.pageSize >= pagination.total}
            >
              Next
            </button>
            <select
              className="form-select"
              style={{ width: 'auto', padding: '4px 28px 4px 8px' }}
              value={pagination.pageSize}
              onChange={(e) =>
                pagination.onChange(1, Number(e.target.value))
              }
            >
              {[10, 20, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} per page
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}