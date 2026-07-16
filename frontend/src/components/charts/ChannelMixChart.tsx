import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { PieChart as PieIcon } from 'lucide-react';
import { formatPct } from '../../utils/format';
import type { ChannelMixSlice } from '../../types/achievement';

const COLORS = ['#8B1A1A', '#A52422', '#15803D', '#B45309', '#1d4ed8', '#7c3aed'];

interface ChannelMixChartProps {
  data: ChannelMixSlice[];
}

export function ChannelMixChart({ data }: ChannelMixChartProps) {
  const chartData = data.map((s) => ({ name: s.channel, value: Number(s.pct) }));

  return (
    <Card title="Channel Mix" padding="md">
      {chartData.length === 0 ? (
        <EmptyState icon={PieIcon} title="No channel data" />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={2}
              label={(e: { name?: string; value?: number }) => `${e.name} ${formatPct(e.value ?? 0, 0)}`}
              labelLine={false}
            >
              {chartData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v: number) => formatPct(v)} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
