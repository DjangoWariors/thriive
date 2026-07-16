import {useState, useEffect, useRef} from 'react';
import {useLocation, useNavigate} from 'react-router';
import {
    Menu,
    Search,
    ChevronDown,
    Calendar,
    LogOut,
    User2,
    Settings,
} from 'lucide-react';
import {useAuth} from '../../hooks/useAuth';
import {NotificationBell} from '../ui/NotificationBell';
import {pickDefaultPeriod, usePeriodSelector} from '../../hooks/usePeriodSelector';
import {useTargetPeriods} from '../../hooks/useTargets';
import {Avatar} from '../ui/Avatar';
import {cn} from '../../utils/cn';



const TITLE_MAP: [string, string][] = [
    ['/kpi/builder', 'KPI Builder'],
    ['/kpi/definitions', 'KPI Configuration'],
    ['/targets', 'Target Setting'],
    ['/achievements', 'Achievement'],
    ['/incentives/payouts', 'Payouts'],
    ['/exceptions', 'Exceptions'],
    ['/network', 'Network'],
    ['/admin/users', 'User Management'],
    ['/admin/roles', 'Roles & Permissions'],
    ['/admin/audit', 'Audit Trail'],
    ['/reports', 'Reports'],
    ['/settings', 'Settings'],
    ['/', 'Dashboard'],
];

function usePageTitle(): string {
    const {pathname} = useLocation();
    const entry = TITLE_MAP.find(([path]) =>
        path === '/' ? pathname === '/' : pathname === path || pathname.startsWith(`${path}/`),
    );
    return entry?.[1] ?? 'Thriive IMS';
}



function PeriodSelector() {
    const {selectedPeriodId, setSelectedPeriodId} = usePeriodSelector();
    const {data: periods} = useTargetPeriods();
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;

        function onClickOutside(e: MouseEvent) {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        }

        document.addEventListener('mousedown', onClickOutside);
        return () => document.removeEventListener('mousedown', onClickOutside);
    }, [open]);

    const list = periods?.results ?? [];
    const selected = list.find((p) => p.id === selectedPeriodId);
    // Calendar order: each fiscal-year root, then its months beneath it.
    const calendar = [...list].sort((a, b) => a.path.localeCompare(b.path));

    // Targets are planned monthly — default to the current month, not the annual root.
    useEffect(() => {
        if (selectedPeriodId === null && list.length > 0) {
            const fallback = pickDefaultPeriod(list);
            if (fallback) setSelectedPeriodId(fallback.id);
        }
    }, [selectedPeriodId, list, setSelectedPeriodId]);

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    'flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors',
                    'border-gray-200 bg-white text-gray-600 hover:border-primary hover:text-primary',
                )}
            >
                <Calendar size={14}/>
                <span className="hidden sm:inline">
          {selected ? selected.name : 'Select Period'}
        </span>
                <ChevronDown size={13}/>
            </button>

            {open && (
                <div
                    className="absolute right-0 mt-1.5 max-h-72 w-56 overflow-y-auto rounded-xl border border-gray-100 bg-white py-1 shadow-lg z-50">
                    {calendar.length === 0 ? (
                        <p className="px-4 py-3 text-xs text-gray-400 text-center">
                            No periods configured yet.
                        </p>
                    ) : (
                        calendar.map((p) => (
                            <button
                                key={p.id}
                                onClick={() => {
                                    setSelectedPeriodId(p.id);
                                    setOpen(false);
                                }}
                                style={{paddingLeft: `${16 + p.depth * 14}px`}}
                                className={cn(
                                    'flex w-full items-center justify-between pr-4 py-2 text-sm transition-colors hover:bg-gray-50',
                                    p.id === selectedPeriodId ? 'text-primary font-medium' : 'text-gray-700',
                                    p.period_type !== 'monthly' && 'font-medium',
                                )}
                            >
                                <span className="truncate">{p.name}</span>
                                <span className="ml-2 text-[10px] uppercase tracking-wide text-gray-500">{p.status}</span>
                            </button>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}



function UserMenu() {
    const [open, setOpen] = useState(false);
    const {user, logout} = useAuth();
    const navigate = useNavigate();
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;

        function onClickOutside(e: MouseEvent) {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        }

        document.addEventListener('mousedown', onClickOutside);
        return () => document.removeEventListener('mousedown', onClickOutside);
    }, [open]);

    const fullName =
        [user?.first_name, user?.last_name].filter(Boolean).join(' ') || 'User';
    const role = user?.active_roles[0]?.name ?? '';

    function handleLogout() {
        void logout().then(() => navigate('/login', {replace: true}));
    }

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-gray-100 transition-colors"
            >
                <Avatar name={fullName} size="sm"/>
                <div className="hidden md:block text-left">
                    <p className="text-sm font-medium text-gray-900 leading-tight">{fullName}</p>
                    {role && <p className="text-xs text-gray-500 leading-tight">{role}</p>}
                </div>
                <ChevronDown size={13} className="hidden md:block text-gray-400"/>
            </button>

            {open && (
                <div
                    className="absolute right-0 mt-2 w-52 rounded-xl border border-gray-100 bg-white py-1 shadow-lg z-50"
                    role="menu"
                >
                    <div className="border-b border-gray-100 px-4 py-2.5">
                        <p className="text-sm font-medium text-gray-900">{fullName}</p>
                        {role && <p className="text-xs text-gray-500">{role}</p>}
                    </div>

                    <button
                        onClick={() => {
                            setOpen(false);
                            navigate('/settings?tab=profile');
                        }}
                        className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                        role="menuitem"
                    >
                        <User2 size={15} className="text-gray-400"/>
                        Profile
                    </button>
                    <button
                        onClick={() => {
                            setOpen(false);
                            navigate('/settings');
                        }}
                        className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                        role="menuitem"
                    >
                        <Settings size={15} className="text-gray-400"/>
                        Settings
                    </button>

                    <div className="my-1 border-t border-gray-100"/>

                    <button
                        onClick={handleLogout}
                        className="flex w-full items-center gap-3 px-4 py-2 text-sm text-danger hover:bg-danger-50 transition-colors"
                        role="menuitem"
                    >
                        <LogOut size={15}/>
                        Sign out
                    </button>
                </div>
            )}
        </div>
    );
}


interface HeaderProps {
    onMobileMenuToggle: () => void;
}

export function Header({onMobileMenuToggle}: HeaderProps) {
    const title = usePageTitle();

    return (
        <header
            className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4 shadow-sm lg:px-6">

            <div className="flex items-center gap-3">
                <button
                    onClick={onMobileMenuToggle}
                    aria-label="Open menu"
                    className="flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors lg:hidden"
                >
                    <Menu size={20}/>
                </button>
                <h1 className="text-base font-semibold text-gray-900">{title}</h1>
            </div>


            <div
                className="hidden md:flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm w-64">
                <Search size={14} className="shrink-0 text-gray-400"/>
                <input
                    type="text"
                    placeholder="Search KPIs, reps, targets..."
                    className="flex-1 bg-transparent text-gray-700 placeholder:text-gray-400 focus:outline-none"
                />
            </div>


            <div className="flex items-center gap-2">
                <PeriodSelector/>

                <NotificationBell/>

                <UserMenu/>
            </div>
        </header>
    );
}
