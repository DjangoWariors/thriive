import {Outlet, useLocation, useNavigate} from 'react-router';
import {Tabs} from '../../components/ui/Tabs';
import {HowThisWorks} from '../../components/ui/HowThisWorks';

const SETUP_TABS = [
    {label: 'Role Types', value: '/network/setup/role-types'},
    {label: 'Sales Channels', value: '/network/setup/channels'},
];

export default function NetworkSetupLayout() {
    const {pathname} = useLocation();
    const navigate = useNavigate();
    const active = SETUP_TABS.find((t) => pathname.startsWith(t.value))?.value
        ?? '/network/setup/role-types';

    return (
        <div className="p-6">
            <HowThisWorks storageKey="network-setup-help" className="mb-4">
                Setting up for the first time? Work left to right across the workspace:
                <strong> Role Types</strong> first (the kinds of people and partners you have, and what
                each can do), then add your <strong>People &amp; Partners</strong> under one another,
                map out your <strong>Territories</strong>, and finally hand each territory to its owner
                on <strong>Territory Owners</strong>. From then on, sales land with the right person on
                their own. Channels (GT, MT, …) tag people and schemes by how products reach customers.
            </HowThisWorks>
            <Tabs
                tabs={SETUP_TABS}
                activeTab={active}
                onChange={(value) => navigate(value)}
                className="mb-4"
            />
            <Outlet/>
        </div>
    );
}
