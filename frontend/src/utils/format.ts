export function formatCurrency(value: number | string): string {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    if (isNaN(num)) return '₹0';
    const abs = Math.abs(num);
    if (abs >= 10_000_000) return `₹${(num / 10_000_000).toFixed(2)}Cr`;
    if (abs >= 100_000) return `₹${(num / 100_000).toFixed(2)}L`;
    if (abs >= 1_000) return `₹${(num / 1_000).toFixed(1)}K`;
    return `₹${num.toLocaleString('en-IN')}`;
}

/** Number formatter driven by a KPI's display unit: currency gets ₹, anything else
 * (outlets, volume…) a plain locale number at the KPI's precision. */
export function makeUnitFormatter(unit?: string, decimalPlaces?: number) {
    const currency = !unit || unit === '₹' || unit.toUpperCase() === 'INR';
    const digits = currency ? 0 : Math.min(decimalPlaces ?? 0, 4);
    return (value: string | null): string => {
        if (value === null || value === '') return '—';
        const num = Number(value);
        const text = Math.abs(num).toLocaleString('en-IN', {
            minimumFractionDigits: 0, maximumFractionDigits: digits,
        });
        // Sign before the ₹ — "−₹3", never "₹-3".
        return `${num < 0 ? '-' : ''}${currency ? `₹${text}` : text}`;
    };
}

/** Plain Indian-locale integer for plan numbers; '-' when the value is missing. */
export function formatInr(value: string | null | undefined): string {
    if (value === null || value === undefined || value === '') return '-';
    return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export function formatPct(value: number | string, decimals = 2): string {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    if (isNaN(num)) return '0%';
    return `${num.toFixed(decimals)}%`;
}

export function formatNumber(value: number | string): string {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    if (isNaN(num)) return '0';
    return new Intl.NumberFormat('en-IN').format(num);
}

export function formatDate(value: string | Date): string {
    const date = typeof value === 'string' ? new Date(value) : value;
    return new Intl.DateTimeFormat('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
    }).format(date);
}

export function formatRelative(value: string | Date): string {
    const date = typeof value === 'string' ? new Date(value) : value;
    const diffMs = Date.now() - date.getTime();
    const diffMins = Math.floor(diffMs / 60_000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return formatDate(date);
}
