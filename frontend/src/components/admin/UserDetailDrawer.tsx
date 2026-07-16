import {useEffect} from 'react';
import {createPortal} from 'react-dom';
import {Link} from 'react-router';
import {X, ChevronRight, Pencil, Building2} from 'lucide-react';
import type {User} from '../../types/auth';
import {useEntityAncestors} from '../../hooks/useEntities';
import {Avatar} from '../ui/Avatar';
import {Badge} from '../ui/Badge';
import {Button} from '../ui/Button';
import {Spinner} from '../ui/Spinner';
import {formatDate, formatRelative} from '../../utils/format';

interface UserDetailDrawerProps {
    user: User | null;
    open: boolean;
    onClose: () => void;
    /** When omitted (e.g. read-only viewer), the Edit action is hidden. */
    onEdit?: (user: User) => void;
}

export function UserDetailDrawer({user, open, onClose, onEdit}: UserDetailDrawerProps) {
    useEffect(() => {
        if (!open) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, [open, onClose]);

    if (!open || !user) return null;

    const body = document.body;
    if (!body) return null;

    const fullName = `${user.first_name} ${user.last_name}`.trim() || user.email || '—';

    return createPortal(
        <div className="fixed inset-0 z-50">
            <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true"/>
            <div
                className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-xl animate-in slide-in-from-right duration-200"
                role="dialog"
                aria-modal="true"
                aria-label="User details"
            >
                {/* Header */}
                <div className="flex items-start justify-between border-b border-gray-100 px-6 py-4">
                    <div className="flex items-center gap-3">
                        <Avatar name={fullName} size="lg"/>
                        <div>
                            <h2 className="text-lg font-semibold text-gray-900">{fullName}</h2>
                            <p className="text-sm text-gray-500">{user.designation || '—'}</p>
                            <div className="mt-1">
                                {user.is_active === false ? (
                                    <Badge variant="default">Inactive</Badge>
                                ) : (
                                    <Badge variant="success">Active</Badge>
                                )}
                            </div>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="ml-4 rounded-lg p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                        aria-label="Close"
                    >
                        <X className="h-5 w-5"/>
                    </button>
                </div>

                {/* Body */}
                <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
                    <Section title="Contact">
                        <Field label="Email" value={user.email}/>
                        <Field label="Mobile" value={user.mobile}/>
                        <Field label="Employee ID" value={user.employee_id}/>
                        <Field label="Department" value={user.department}/>
                        <Field label="Joined" value={user.date_joined ? formatDate(user.date_joined) : null}/>
                        <Field
                            label="Last login"
                            value={user.last_login ? formatRelative(user.last_login) : 'Never'}
                        />
                    </Section>

                    <Section title="Roles">
                        {user.active_roles.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                                {user.active_roles.map((r) => (
                                    <Badge key={r.code} variant="info">
                                        {r.name}
                                    </Badge>
                                ))}
                            </div>
                        ) : (
                            <p className="text-sm text-gray-400">No active roles assigned.</p>
                        )}
                    </Section>

                    <HierarchySection user={user}/>
                </div>

                {/* Footer */}
                <div className="flex justify-end gap-3 border-t border-gray-100 px-6 py-4">
                    <Button variant="outline" onClick={onClose}>
                        Close
                    </Button>
                    {onEdit && (
                        <Button icon={<Pencil className="h-4 w-4"/>} onClick={() => onEdit(user)}>
                            Edit
                        </Button>
                    )}
                </div>
            </div>
        </div>,
        body,
    );
}



function HierarchySection({user}: { user: User }) {
    const entity = user.entity_info;
    const {data: ancestors, isLoading} = useEntityAncestors(entity?.id ?? 0);

    if (!entity) {
        return (
            <Section title="Hierarchy">
                <p className="text-sm text-gray-400">
                    Not linked to any entity (standalone admin / staff account).
                </p>
            </Section>
        );
    }


    const chain = ancestors ? [...ancestors].reverse() : [];

    return (
        <Section title="Hierarchy">
            <div className="rounded-lg border border-gray-200 p-3">
                <div className="flex items-center gap-2">
                    <Building2 className="h-4 w-4 text-primary"/>
                    <Link
                        to={`/network/people/${entity.id}`}
                        className="font-medium text-primary hover:underline"
                    >
                        {entity.name}
                    </Link>
                    {entity.type && <Badge variant="purple">{entity.type}</Badge>}
                </div>
                <p className="mt-1 break-all text-xs text-gray-500">{entity.path}</p>
            </div>

            <div className="mt-3">
                <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                    Reports to
                </p>
                {isLoading ? (
                    <Spinner size="sm"/>
                ) : chain.length === 0 ? (
                    <p className="text-sm text-gray-400">Top of the hierarchy — no parent.</p>
                ) : (
                    <div className="flex flex-wrap items-center gap-1 text-sm">
                        {chain.map((node, i) => (
                            <span key={node.id} className="flex items-center gap-1">
                {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-gray-300"/>}
                                <Link
                                    to={`/network/people/${node.id}`}
                                    className="text-gray-600 hover:text-primary hover:underline"
                                >
                  {node.name}
                </Link>
              </span>
                        ))}
                    </div>
                )}
            </div>
        </Section>
    );
}



function Section({title, children}: { title: string; children: React.ReactNode }) {
    return (
        <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h3>
            {children}
        </div>
    );
}

function Field({label, value}: { label: string; value: string | null | undefined }) {
    return (
        <div className="flex justify-between gap-4 py-1 text-sm">
            <span className="text-gray-500">{label}</span>
            <span className="text-right font-medium text-gray-900">{value || '—'}</span>
        </div>
    );
}
