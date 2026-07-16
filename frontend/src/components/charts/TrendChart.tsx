import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { TrendingUp } from 'lucide-react';
import { formatCurrency } from '../../utils/format';
import type { TrendPoint } from '../../types/achievement';

interface TrendChartProps {
  data: TrendPoint[];
  title?: string;
}

export function TrendChart({ data, title = 'Target vs Achieved' }: TrendChartProps) {
  const chartData = data.map((p) => ({
    label: p.label,
    Target: Number(p.target),
    Achieved: Number(p.achieved),
  }));

  return (
    <Card title={title} padding="md">
      {chartData.length === 0 ? (
        <EmptyState icon={TrendingUp} title="No trend data" description="Snapshots appear once achievements are computed." />
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <YAxis tickFormatter={(v) => formatCurrency(v)} tick={{ fontSize: 11 }} stroke="#9ca3af" width={70} />
            <Tooltip formatter={(v: number) => formatCurrency(v)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line type="monotone" dataKey="Target" stroke="#9ca3af" strokeDasharray="5 5" dot={false} />
            <Line type="monotone" dataKey="Achieved" stroke="#8B1A1A" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
