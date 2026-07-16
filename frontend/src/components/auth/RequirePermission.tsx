import {Navigate, Outlet} from 'react-router';
import {useAuth} from '../../hooks/useAuth';
import {useRBAC} from '../../hooks/useRBAC';

/**
 * Route guard: renders nested routes only if the current user has any level
 * above 'none' for `permission`; otherwise redirects to /403. Mirrors the
 * permission check the Sidebar uses to show/hide nav links.
 */
export function RequirePermission({permission}: {permission: string}) {
    const {can} = useRBAC();
    return can(permission) ? <Outlet/> : <Navigate to="/403" replace/>;
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
