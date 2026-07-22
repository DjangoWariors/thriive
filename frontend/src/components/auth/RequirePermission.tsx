import {Navigate, Outlet} from 'react-router';
import {useAuth} from '../../hooks/useAuth';
import {useRBAC} from '../../hooks/useRBAC';
import type {PermLevel} from '../../hooks/useRBAC';

/**
 * Route guard: renders nested routes only if the current user has any level
 * above 'none' for `permission` (or at least `minLevel`, when given); otherwise
 * redirects to /403. Mirrors the permission check the Sidebar uses to show/hide
 * nav links. `minLevel` gates org-wide payout screens (cycles) to view_all+.
 */
export function RequirePermission(
    {permission, minLevel}: {permission: string; minLevel?: Exclude<PermLevel, null>},
) {
    const {can, canAtLeast} = useRBAC();
    const ok = minLevel ? canAtLeast(permission, minLevel) : can(permission);
    return ok ? <Outlet/> : <Navigate to="/403" replace/>;
}

/**
 * Route guard for planning-admin screens (calendar, recipes, change caps, new plan):
 * requires `permission` AND an HO user — one not placed in the org tree. Mirrors the
 * backend's `is_planning_admin`; field users (ASMs…) work inside plans, never on them.
 */
export function RequirePlanningAdmin({permission}: {permission: string}) {
    const {user} = useAuth();
    const {can} = useRBAC();
    return can(permission) && !user?.entity_info ? <Outlet/> : <Navigate to="/403" replace/>;
}
