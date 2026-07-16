import {useState} from 'react';
import {Outlet, useLocation} from 'react-router';
import {cn} from '../../utils/cn';
import {ErrorBoundary} from '../ui/ErrorBoundary';
import {Sidebar} from './Sidebar';
import {Header} from './Header';

export function AdminLayout() {
    const [collapsed, setCollapsed] = useState(false);
    const [mobileOpen, setMobileOpen] = useState(false);
    const location = useLocation();

    return (
        <div className="flex h-screen overflow-hidden bg-gray-50">
            <Sidebar
                collapsed={collapsed}
                onToggle={() => setCollapsed((v) => !v)}
                mobileOpen={mobileOpen}
                onMobileClose={() => setMobileOpen(false)}
            />


            <div
                className={cn(
                    'flex flex-1 flex-col overflow-hidden transition-all duration-200 ease-in-out',
                    'ml-0',
                    collapsed ? 'lg:ml-16' : 'lg:ml-60',
                )}
            >
                <Header onMobileMenuToggle={() => setMobileOpen((v) => !v)}/>

                <main className="flex-1 overflow-auto p-6">
                    <ErrorBoundary key={location.pathname}>
                        <Outlet/>
                    </ErrorBoundary>
                </main>
            </div>
        </div>
    );
}
