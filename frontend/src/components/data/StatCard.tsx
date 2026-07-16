import type { ComponentType } from 'react';
import { Card } from '../ui/Card';
import { cn } from '../../utils/cn';

interface StatCardProps {
  label: string;
  value: string;
  subtitle?: string;
  borderColor?: 'red' | 'green' | 'amber' | 'blue' | 'purple';
  icon?: ComponentType<{ className?: string; size?: number }>;
  onClick?: () => void;
}

export function StatCard({ label, value, subtitle, borderColor, icon: Icon, onClick }: StatCardProps) {
  const body = (
    <>
      <div className="flex items-start justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">{label}</p>
        {Icon && <Icon className="text-gray-300" size={18} />}
      </div>
      <p className="mt-2 text-3xl font-bold text-gray-800">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-gray-500">{subtitle}</p>}
    </>
  );
  return (
    <Card
      borderColor={borderColor}
      padding="md"
      className={cn(onClick && 'transition-shadow hover:shadow-md')}
    >
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className="w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          {body}
        </button>
      ) : (
        <div>{body}</div>
      )}
    </Card>
  );
}
