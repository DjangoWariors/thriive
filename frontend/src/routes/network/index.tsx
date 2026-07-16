import {Outlet, useLocation, useNavigate} from 'react-router';
import {Tabs} from '../../components/ui/Tabs';

/** One workspace for the whole network: people, territories, ownership and the
 * setup catalogues — tabs are URL-driven so every view deep-links and redirects. */
const TABS = [
    {label: 'People & Partners', value: '/network/people'},
    {label: 'Territories', value: '/network/territories'},
    {label: 'Territory Owners', value: '/network/owners'},
    {label: 'Setup', value: '/network/setup'},
];

export function activeNetworkTab(pathname: string): string {
    const match = TABS.find((t) => pathname === t.value || pathname.startsWith(`${t.value}/`));
    return match?.value ?? '/network/people';
}

export default function NetworkWorkspaceLayout() {
    const {pathname} = useLocation();
    const navigate = useNavigate();

    return (
        // Escapes AdminLayout's p-6 so the workspace owns the full viewport below
        // the header; each tab page brings its own padding.
        <div className="-m-6 flex flex-col overflow-hidden" style={{height: 'calc(100vh - 4rem)'}}>
            <div className="shrink-0 border-b border-gray-200 bg-white px-6 pt-3">
                <div className="mb-1 flex items-baseline gap-3">
                    <h1 className="text-lg font-bold text-gray-900">Network</h1>
                    <p className="hidden text-xs text-gray-400 sm:block">
                        Your people, the places they cover, and who owns what — one place.
                    </p>
                </div>
                <Tabs
                    tabs={TABS}
                    activeTab={activeNetworkTab(pathname)}
                    onChange={(value) => navigate(value)}
                    className="border-b-0"
                />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
                <Outlet/>
            </div>
        </div>
    );
}
