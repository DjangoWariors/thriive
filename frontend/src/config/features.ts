/**
 * Frontend feature switches. Everything gated off a switch stays wired
 * (routes, nav items, builder options) — flip to true to restore it.
 */

/** External Metrics: admin page, sidebar item and the 'external' KPI type in the builder. */
export const EXTERNAL_METRICS_ENABLED = false;

/** Subtree realignment: the "Realign a subtree" action and its staged-run review on plan detail. */
export const REALIGN_ENABLED = false;

/** The "Transfer person" action (same role, new seat/manager) on people screens. */
export const PERSON_TRANSFER_ENABLED = true;

/** The "Change Role" action (promote/demote to another type) on people screens.
 * Parked as confusing; UX rethink pending (single "Move / Promote" chooser). */
export const CHANGE_ROLE_ENABLED = false;

/** Role-in-territory (owner / stand-in / supervisor) on the Owners register.
 * Off = plain ownership view; the UI only creates owner assignments anyway.
 * NOTE before enabling: computation resolves territories role-agnostically, so
 * API-created supervisor/stand-in rows would inflate that person's achievements
 * (kpi_engine/calculator.py, achievements/services.py) — fix credit to owner-only first. */
export const TERRITORY_ROLES_ENABLED = false;
