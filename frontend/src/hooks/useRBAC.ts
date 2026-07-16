import {useAuthStore} from '../stores/authStore';

export type PermLevel =
    | 'full'
    | 'view_all'
    | 'view_edit'
    | 'team'
    | 'own_only'
    | 'view_readonly'
    | null;


const LEVEL_RANK: Record<string, number> = {
    full: 6,
    view_all: 5,
    view_edit: 4,
    team: 3,
    own_only: 2,
    view_readonly: 1,
    none: 0,
};

export function useRBAC() {
    const user = useAuthStore((state) => state.user);

    function permLevel(resource: string): PermLevel {
        if (!user) return null;


        if (user.is_superuser) return 'full';


        let bestRank = 0;
        let bestLevel = 'none';

        for (const role of user.active_roles) {
            const level = role.permissions[resource] ?? 'none';
            const rank = LEVEL_RANK[level] ?? 0;
            if (rank > bestRank) {
                bestRank = rank;
                bestLevel = level;
            }
        }

        return bestRank > 0 ? (bestLevel as PermLevel) : null;
    }

    function can(resource: string): boolean {
        return permLevel(resource) !== null;
    }

    function canAny(...resources: string[]): boolean {
        return resources.some((r) => can(r));
    }

    // Levels that permit writes. Mirrors RBACPermission.has_object_permission:
    // view_all / view_readonly are read-only; the rest write (within their scope).
    const WRITE_LEVELS = new Set<string>(['full', 'view_edit', 'team', 'own_only']);

    function canWrite(resource: string): boolean {
        const level = permLevel(resource);
        return level !== null && WRITE_LEVELS.has(level);
    }

    return {can, canAny, canWrite, permLevel};
}
