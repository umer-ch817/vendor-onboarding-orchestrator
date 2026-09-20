/** Charts.
 *
 * There are deliberately no charting libraries here. The only figures worth
 * drawing are small distributions, and a handful of divs renders them with no
 * dependency, no canvas, and no bundle cost -- while inheriting the design
 * tokens the rest of the app already uses.
 *
 * They are also deliberately quiet: fills are translucent and tracks are near
 * invisible, because a dashboard's job is to be scanned. A chart that shouts
 * competes with the worklist above it.
 */

import { Card, EmptyState } from './index';
import './Charts.css';

export type ChartTone = 'neutral' | 'danger' | 'warning' | 'success';

export interface ColumnDatum {
  key: string;
  label: string;
  value: number;
  tone?: ChartTone;
}

/** Vertical columns. Best for an ordered set of buckets -- especially bands
 *  of time, where the left-to-right reading is the point. */
export function ColumnChart({
  title,
  subtitle,
  data,
  emptyHint,
}: {
  title: string;
  subtitle?: string;
  data: ColumnDatum[];
  emptyHint?: string;
}) {
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const max = Math.max(1, ...data.map((d) => d.value));

  if (total === 0) {
    return (
      <Card title={title} subtitle={subtitle}>
        <EmptyState
          title="Nothing here yet"
          description={emptyHint || 'This chart fills in once there is data.'}
        />
      </Card>
    );
  }

  return (
    <Card title={title} subtitle={subtitle}>
      <div className="column-chart">
        {data.map((d) => (
          <div className="column" key={d.key} title={`${d.label}: ${d.value}`}>
            <span className="column-value">{d.value}</span>
            <div className="column-track">
              <div
                className={`column-fill column-${d.tone || 'neutral'}`}
                style={{ height: `${(d.value / max) * 100}%` }}
              />
            </div>
            <span className="column-label">{d.label}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
