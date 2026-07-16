import {NavLink, Outlet, useLocation} from 'react-router';
import {Home, IndianRupee, User} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';
import {useAuth} from '../../hooks/useAuth';
import {Avatar} from '../ui/Avatar';
import {ErrorBoundary} from '../ui/ErrorBoundary';
import {NotificationBell} from '../ui/NotificationBell';
import {cn} from '../../utils/cn';



type BottomTab = { label: string; icon: LucideIcon; href: string };

// RFP-scoped partner portal: my targets & achievements, my payouts, my profile.
const BOTTOM_TABS: BottomTab[] = [
    {label: 'Home', icon: Home, href: '/'},
    {label: 'Payouts', icon: IndianRupee, href: '/my-payouts'},
    {label: 'Profile', icon: User, href: '/profile'},
];



export function PartnerLayout() {
    const {user} = useAuth();
    const location = useLocation();

    const entityName = user?.entity_info?.name ?? 'Partner Portal';
    const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || 'User';

    return (
        <div className="flex h-screen flex-col bg-gray-50">

            <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
                <div>
                    <p className="text-sm font-semibold text-gray-900 leading-tight">{entityName}</p>
                    <p className="text-xs text-gray-500 leading-tight">{fullName}</p>
                </div>
                <div className="flex items-center gap-1">
                    <NotificationBell/>
                    <Avatar name={fullName} size="sm"/>
                </div>
            </header>


            <main className="flex-1 overflow-auto pb-[calc(4rem+env(safe-area-inset-bottom))]">
                <ErrorBoundary key={location.pathname}>
                    <Outlet/>
                </ErrorBoundary>
            </main>

            <nav
                className="fixed bottom-0 left-0 right-0 z-30 flex items-stretch border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)]">
                {BOTTOM_TABS.map((tab) => (
                    <NavLink
                        key={tab.href}
                        to={tab.href}
                        end={tab.href === '/'}
                        className={({isActive}) =>
                            cn(
                                'flex h-16 flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors',
                                isActive ? 'text-primary' : 'text-gray-400 hover:text-gray-600',
                            )
                        }
                    >
                        <tab.icon size={20}/>
                        <span>{tab.label}</span>
                    </NavLink>
                ))}
            </nav>
        </div>
    );
}
