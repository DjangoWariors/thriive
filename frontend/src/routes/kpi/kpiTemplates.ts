import {
    TrendingUp, Store, Receipt, ListOrdered, LineChart, BadgeCheck,
    Target, Percent, Sigma, Gauge, type LucideIcon,
} from 'lucide-react';

// Templates come from the backend (`/api/v1/kpis/templates/`, editable in admin).
// The backend stores a kebab-case lucide icon name; resolve it to a component here.
const TEMPLATE_ICONS = new Map<string, LucideIcon>([
    ['trending-up', TrendingUp],
    ['store', Store],
    ['receipt', Receipt],
    ['list-ordered', ListOrdered],
    ['line-chart', LineChart],
    ['badge-check', BadgeCheck],
    ['target', Target],
    ['percent', Percent],
    ['sigma', Sigma],
    ['gauge', Gauge],
]);

/** Resolve a stored template icon name to a component, falling back to a neutral gauge. */
export function resolveTemplateIcon(name?: string | null): LucideIcon {
    return (name && TEMPLATE_ICONS.get(name)) || Gauge;
}
