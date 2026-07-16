import { Card } from '../ui/Card';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { ProgressBar } from '../ui/ProgressBar';
import { EmptyState } from '../ui/EmptyState';
import { Trophy } from 'lucide-react';
import { formatCurrency, formatPct } from '../../utils/format';
import type { RankRow } from '../../types/achievement';

const MEDAL = ['🥇', '🥈', '🥉'];

interface LeaderboardProps {
  rows: RankRow[];
  title?: string;
  showPayout?: boolean;
  onRowClick?: (row: RankRow) => void;
}

export function Leaderboard({ rows, title = 'Leaderboard', showPayout = false, onRowClick }: LeaderboardProps) {
  return (
    <Card title={title} padding="none">
      {rows.length === 0 ? (
        <EmptyState icon={Trophy} title="No ranking" description="Direct reports appear here once computed." />
      ) : (
        <div className="divide-y divide-gray-100">
          {rows.map((row) => (
            <button
              key={row.entity_id}
              onClick={() => onRowClick?.(row)}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-gray-50"
            >
              <span className="w-6 shrink-0 text-center text-sm font-semibold text-gray-500">
                {row.rank <= 3 ? MEDAL[row.rank - 1] : row.rank}
              </span>
              <Avatar name={row.entity_name} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">{row.entity_name}</p>
                <p className="truncate text-xs text-gray-500">{row.entity_code}</p>
              </div>
              {row.channel && <Badge variant="default" size="sm">{row.channel}</Badge>}
              <div className="w-24 shrink-0">
                <p className="text-right text-sm font-semibold text-gray-800">{formatPct(row.achievement_pct)}</p>
                <ProgressBar value={Number(row.achievement_pct)} size="sm" />
              </div>
              {showPayout && row.payout !== null && (
                <span className="w-20 shrink-0 text-right text-sm font-medium text-success">
                  {formatCurrency(row.payout)}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}
