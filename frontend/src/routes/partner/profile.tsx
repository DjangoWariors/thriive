import {useNavigate} from 'react-router';
import {LogOut, Store} from 'lucide-react';
import {useAuth} from '../../hooks/useAuth';
import {Avatar} from '../../components/ui/Avatar';
import {Button} from '../../components/ui/Button';
import {Card} from '../../components/ui/Card';

/** Partner profile — who I am and where I sit in the network. */
export default function PartnerProfilePage() {
    const {user, logout} = useAuth();
    const navigate = useNavigate();
    const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || 'User';

    async function signOut() {
        await logout();
        navigate('/login');
    }

    return (
        <div className="space-y-4 p-4">
            <h1 className="text-lg font-bold text-gray-900">My Profile</h1>

            <Card>
                <div className="flex items-center gap-3">
                    <Avatar name={fullName} size="lg"/>
                    <div>
                        <p className="font-semibold text-gray-900">{fullName}</p>
                        <p className="text-xs text-gray-500">{user?.email || user?.mobile || '—'}</p>
                    </div>
                </div>
            </Card>

            {user?.entity_info && (
                <Card>
                    <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        <Store className="h-3.5 w-3.5"/> My business
                    </p>
                    <dl className="space-y-1.5 text-sm">
                        <div className="flex justify-between">
                            <dt className="text-gray-500">Name</dt>
                            <dd className="font-medium text-gray-900">{user.entity_info.name}</dd>
                        </div>
                        <div className="flex justify-between">
                            <dt className="text-gray-500">Code</dt>
                            <dd className="font-medium text-gray-900">{user.entity_info.code}</dd>
                        </div>
                        <div className="flex justify-between">
                            <dt className="text-gray-500">Type</dt>
                            <dd className="font-medium text-gray-900">{user.entity_info.type}</dd>
                        </div>
                    </dl>
                </Card>
            )}

            <Button variant="outline" className="w-full" icon={<LogOut className="h-4 w-4"/>}
                    onClick={() => void signOut()}>
                Sign out
            </Button>
        </div>
    );
}
