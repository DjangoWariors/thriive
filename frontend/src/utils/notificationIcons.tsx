import {
    Award, AlertTriangle, Clock, DollarSign, FileCheck, Gift,
    Info, ShieldCheck, TrendingUp, Wallet,
    type LucideIcon,
} from 'lucide-react';


const CATEGORY_ICONS: Record<string, LucideIcon> = {
    earning: Gift,
    redemption: Gift,
    kyc: ShieldCheck,
    claim: FileCheck,
    badge: Award,
    wallet: Wallet,
    achievement: TrendingUp,
    payout: DollarSign,
    exception: AlertTriangle,
    approval: Clock,
};


const CATEGORY_COLOR: Record<string, string> = {
    earning: 'text-green-600',
    redemption: 'text-green-600',
    kyc: 'text-blue-600',
    claim: 'text-blue-600',
    badge: 'text-amber-500',
    wallet: 'text-amber-500',
    achievement: 'text-primary',
    payout: 'text-green-600',
    exception: 'text-red-600',
    approval: 'text-blue-600',
};


export function NotificationIcon({category, className}: {category?: string | null; className?: string}) {
    const Icon = (category && CATEGORY_ICONS[category]) || Info;
    const color = (category && CATEGORY_COLOR[category]) || 'text-gray-400';
    return <Icon className={`${className ?? ''} ${color}`.trim()}/>;
}
