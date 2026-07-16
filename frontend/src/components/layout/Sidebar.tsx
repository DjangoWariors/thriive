import {NavLink} from 'react-router';
import type {LucideIcon} from 'lucide-react';
import {
    LayoutDashboard,
    Target,
    Crosshair,
    TrendingUp,
    DollarSign,
    CalendarClock,
    AlertTriangle,
    BarChart3,
    FileText,
    Settings,
    ChevronLeft,
    ChevronRight,
    Network,
    Layers,
    Users,
    Shield,
    Package,
    Boxes,
    Scale,
    Receipt,
    Award,
    Wallet,
    Inbox,
    Radio,
    PlugZap,
    KeyRound,
    CloudUpload,
} from 'lucide-react';
import {cn} from '../../utils/cn';
import {EXTERNAL_METRICS_ENABLED} from '../../config/features';
import {useRBAC} from '../../hooks/useRBAC';
import {usePendingCount} from '../../hooks/useWorkflows';
import {Tooltip} from '../ui/Tooltip';



type NavLeaf = {
    label: string;
    icon: LucideIcon;
    href: string;
    permission?: string;
    badge?: boolean;
};

type NavSection = {
    group: string;
    items: NavLeaf[];
};

type NavEntry = NavLeaf | NavSection;

function isNavSection(entry: NavEntry): entry is NavSection {
    return 'group' in entry;
}



const NAV_ITEMS: NavEntry[] = [
    {label: 'Dashboard', icon: LayoutDashboard, href: '/'},
    {
        group: 'CONFIGURATION',
        items: [
            {label: 'KPIs', icon: Target, href: '/kpi/definitions', permission: 'kpi_definitions'},
            {label: 'Sales Data', icon: Receipt, href: '/kpi/transactions', permission: 'kpi_definitions'},
            ...(EXTERNAL_METRICS_ENABLED
                ? [{label: 'External Metrics', icon: Radio, href: '/admin/external-metrics', permission: 'kpi_definitions'}]
                : []),
            {label: 'Target Setting', icon: Crosshair, href: '/targets', permission: 'target_management'},
            {label: 'SIP Schemes', icon: Award, href: '/incentives/schemes', permission: 'scheme_management'},
            {label: 'SIP Structure', icon: Layers, href: '/incentives/sip-structures', permission: 'scheme_management'},
            {label: 'Variable Pay', icon: Wallet, href: '/incentives/variable-pay', permission: 'scheme_management'},
        ],
    },
    {
        group: 'OPERATIONS',
        items: [
            {label: 'Achievement', icon: TrendingUp, href: '/achievements', permission: 'achievement_view'},
            {label: 'Payout Cycles', icon: CalendarClock, href: '/incentives/cycles', permission: 'final_payout'},
            {label: 'Payouts', icon: DollarSign, href: '/incentives/payouts', permission: 'final_payout'},
            {
                label: 'Exceptions',
                icon: AlertTriangle,
                href: '/exceptions',
                permission: 'exception_management',
            },
            {
                label: 'Approvals',
                icon: Inbox,
                href: '/workflows/pending',
                permission: 'workflow_management',
                badge: true,
            },
        ],
    },
    {
        group: 'ANALYTICS',
        items: [
            {label: 'Reports', icon: BarChart3, href: '/reports', permission: 'report_generation'},
            {label: 'Audit Trail', icon: FileText, href: '/admin/audit', permission: 'audit_logs'},
        ],
    },
    {
        group: 'NETWORK & PEOPLE',
        items: [
            {label: 'Network', icon: Network, href: '/network', permission: 'hierarchy_management'},
        ],
    },
    {
        group: 'MASTER DATA',
        items: [
            {label: 'Products', icon: Package, href: '/master/skus', permission: 'master_data'},
            {label: 'SKU Groups', icon: Boxes, href: '/master/sku-groups', permission: 'master_data'},
            {label: 'Unit Conversions', icon: Scale, href: '/master/uom-conversions', permission: 'master_data'},
        ],
    },
    {
        group: 'ADMIN',
        items: [
            {label: 'Users', icon: Users, href: '/admin/users', permission: 'user_management'},
            {label: 'Roles', icon: Shield, href: '/admin/roles', permission: 'role_management'},
            {label: 'Integration Monitor', icon: PlugZap, href: '/admin/integration-monitor', permission: 'integration_monitor'},
            {label: 'API Keys', icon: KeyRound, href: '/admin/api-keys', permission: 'system_admin'},
            {label: 'Delivery Targets', icon: CloudUpload, href: '/admin/delivery-targets', permission: 'system_admin'},
        ],
    },
    {label: 'Settings', icon: Settings, href: '/settings'},
];



function NavItem({item, collapsed, badgeCount = 0}: { item: NavLeaf; collapsed: boolean; badgeCount?: number }) {
    const {can} = useRBAC();
    if (item.permission && !can(item.permission)) return null;
    const showBadge = Boolean(item.badge) && badgeCount > 0;

    const link = (
        <NavLink
            to={item.href}
            end={item.href === '/'}
            className={({isActive}) =>
                cn(
                    'flex items-center gap-3 rounded-lg py-2.5 px-3 text-sm font-medium transition-colors',
                    collapsed && 'justify-center px-2',
                    isActive
                        ? 'bg-primary text-white shadow-sm'
                        : 'text-gray-600 hover:bg-primary-50 hover:text-primary',
                )
            }
        >
            <item.icon size={18} className="shrink-0"/>
            {!collapsed && <span className="truncate">{item.label}</span>}
            {!collapsed && showBadge && (
                <span
                    className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
          {badgeCount > 99 ? '99+' : badgeCount}
        </span>
            )}
        </NavLink>
    );

    if (collapsed) {
        return (
            <Tooltip content={item.label} side="right" className="block w-full">
                {link}
            </Tooltip>
        );
    }

    return link;
}


interface SidebarProps {
    collapsed: boolean;
    onToggle: () => void;
    mobileOpen: boolean;
    onMobileClose: () => void;
}

export function Sidebar({collapsed, onToggle, mobileOpen, onMobileClose}: SidebarProps) {
    const {can} = useRBAC();
    const canApprove = can('workflow_management');
    const {data: pendingCount = 0} = usePendingCount(canApprove);
    const badgeFor = (item: NavLeaf) =>
        item.badge && canApprove ? pendingCount : 0;
    return (
        <>

            {mobileOpen && (
                <div
                    className="fixed inset-0 z-30 bg-black/50 lg:hidden"
                    onClick={onMobileClose}
                    aria-hidden="true"
                />
            )}


            <aside
                className={cn(
                    'fixed inset-y-0 left-0 z-40 flex flex-col bg-white border-r border-gray-200 shadow-sm',
                    'transition-all duration-200 ease-in-out',
                    collapsed ? 'w-16' : 'w-60',
                    mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
                )}
            >

                <div className="flex h-14 shrink-0 items-center justify-between bg-primary px-3 text-white">
                    {collapsed ? (
                        <span className="mx-auto text-xl">🚀</span>
                    ) : (
                        <span className="flex items-center gap-2 text-lg font-bold tracking-tight">
              <span className="text-xl">🚀</span> Thriive
            </span>
                    )}
                    <button
                        onClick={onToggle}
                        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                        className={cn(
                            'hidden lg:flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
                            'text-white/70 hover:bg-white/15 hover:text-white transition-colors',
                            collapsed && 'mx-auto',
                        )}
                    >
                        {collapsed ? <ChevronRight size={15}/> : <ChevronLeft size={15}/>}
                    </button>
                </div>

                {/* Nav */}
                <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
                    {NAV_ITEMS.map((entry) => {
                        if (isNavSection(entry)) {
                            const visibleItems = entry.items.filter(
                                (item) => !item.permission || can(item.permission),
                            );
                            // Hide the whole section — including its header — when the
                            // user can reach none of its items.
                            if (visibleItems.length === 0) return null;
                            return (
                                <div key={entry.group}>
                                    {!collapsed && (
                                        <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-500">
                                            {entry.group}
                                        </p>
                                    )}
                                    <div className="space-y-0.5">
                                        {visibleItems.map((item) => (
                                            <NavItem key={item.href} item={item} collapsed={collapsed}
                                                     badgeCount={badgeFor(item)}/>
                                        ))}
                                    </div>
                                </div>
                            );
                        }
                        return <NavItem key={entry.href} item={entry} collapsed={collapsed}/>;
                    })}
                </nav>


                {!collapsed && (
                    <div className="shrink-0 border-t border-gray-100 px-4 py-3">
                        <p className="text-[10px] text-gray-400">Thriive IMS · Powered by CraziBrain</p>
                    </div>
                )}
            </aside>
        </>
    );
}
