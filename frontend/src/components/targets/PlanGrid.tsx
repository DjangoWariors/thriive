import { Fragment, useState } from 'react';
import { ChevronDown, ChevronRight, Info, Pencil } from 'lucide-react';
import { useGrid } from '../../hooks/useTargets';
import { makeUnitFormatter } from '../../utils/format';
import type { GridOwner, GridRow } from '../../types/target';
import { Avatar } from '../ui/Avatar';
import { Badge } from '../ui/Badge';
import { InfoTooltip } from '../ui/InfoTooltip';
import { StatusBadge } from '../ui/StatusBadge';
import { Tooltip } from '../ui/Tooltip';

const PAGE_SIZE = 200;

export interface PlanGridProps {
  planId: number;
  kpiId: number;
  rootParentId?: number;
  /** KPI display unit ('₹', 'outlets', …) and precision — drives every number cell. */
  unit?: string;
  decimalPlaces?: number;
  /** Hide the review column until a cascade exists. */
  showReview?: boolean;
  /** Row-level edit affordance; the page decides what "edit" means (modify vs review-adjust). */
  canEdit: (row: GridRow) => boolean;
  onEdit: (row: GridRow) => void;
  onExplain: (row: GridRow) => void;
  /** Click on the accountable person — the page opens the person drawer. */
  onOwner: (owner: GridOwner) => void;
}

interface Ctx extends Required<Pick<PlanGridProps, 'planId' | 'kpiId' | 'canEdit' | 'onEdit' | 'onExplain' | 'onOwner' | 'showReview'>> {
  fmt: (value: string | null) => string;
}

/**
 * The lazy planning grid: each level is one API call; expanding a territory fetches its
 * children on demand ("load more" appends further pages) — no response ever carries a
 * whole subtree, so it scales to very large geographies.
 */
export function PlanGrid({
  planId, kpiId, rootParentId, unit, decimalPlaces,
  showReview = true, canEdit, onEdit, onExplain, onOwner,
}: PlanGridProps) {
  // page: 1 keeps this key identical to the first LevelPage's, so the header and the
  // first child level share one request instead of fetching the same page twice.
  const { data, isLoading } = useGrid(planId, {
    kpi: kpiId, parent: rootParentId, page: 1, page_size: PAGE_SIZE,
  });
  const ctx: Ctx = {
    planId, kpiId, showReview, canEdit, onEdit, onExplain, onOwner,
    fmt: makeUnitFormatter(unit, decimalPlaces),
  };
  const columns = showReview ? 10 : 9;
  const unitSuffix = unit && unit !== '₹' ? ` (${unit})` : '';

  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase text-gray-500">
        <tr className="[&>th]:sticky [&>th]:top-0 [&>th]:z-10 [&>th]:border-b [&>th]:border-gray-200 [&>th]:bg-gray-50 [&>th]:px-4 [&>th]:py-3">
          <th>Territory</th>
          <th>
            <span className="inline-flex items-center gap-1">Owner
              <InfoTooltip content="Who is accountable for this territory today, resolved through assignments. Grey = inherited from the territory above. Vacant = no owner anywhere up the chain. Click to see the person's full derived target." /></span>
          </th>
          <th className="text-right">Target{unitSuffix}</th>
          <th className="text-right">
            <span className="inline-flex items-center gap-1">Base
              <InfoTooltip content="The territory's history over the recipe window — the denominator for growth." /></span>
          </th>
          <th className="text-right">
            <span className="inline-flex items-center gap-1">Growth
              <InfoTooltip content="Target vs base. What this plan asks the territory to grow." /></span>
          </th>
          <th className="text-right">
            <span className="inline-flex items-center gap-1">Share
              <InfoTooltip content="This territory's slice of its parent's target." /></span>
          </th>
          <th className="text-right">
            <span className="inline-flex items-center gap-1 whitespace-nowrap">Bottom-up
              <InfoTooltip content="What the children currently sum to. Amber when it no longer matches the territory's own number." /></span>
          </th>
          {showReview && <th className="text-center">Review</th>}
          <th className="text-center">Status</th>
          <th className="text-right" aria-label="Actions" />
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {isLoading ? (
          <SkeletonRows depth={0} columns={columns} />
        ) : data ? (
          data.total === 0 && data.parent.allocation_id === null ? (
            // Masked parent + zero visible children: the plan doesn't cover any
            // territory this user owns.
            <tr>
              <td colSpan={columns} className="px-4 py-6 text-center text-gray-400">
                This plan does not cover your territory.
              </td>
            </tr>
          ) : (
            <Row row={data.parent} depth={0} ctx={ctx} startExpanded />
          )
        ) : (
          <tr><td colSpan={columns} className="px-4 py-6 text-center text-gray-400">No data.</td></tr>
        )}
      </tbody>
    </table>
  );
}

function SkeletonRows({ depth, columns, count = 3 }: { depth: number; columns: number; count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <tr key={i} className="animate-pulse">
          <td className="px-4 py-2.5" style={{ paddingLeft: `${16 + depth * 20}px` }}>
            <div className="h-3.5 w-40 rounded bg-gray-200" />
          </td>
          {Array.from({ length: columns - 1 }, (_, j) => (
            <td key={j} className="px-4 py-2.5"><div className="ml-auto h-3.5 w-14 rounded bg-gray-100" /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

function OwnerCell({ owner, onOwner }: { owner: GridOwner | null; onOwner: (owner: GridOwner) => void }) {
  if (!owner) return <Badge variant="warning">Vacant</Badge>;
  const cell = (
    <button type="button" onClick={() => onOwner(owner)}
            className="group inline-flex max-w-48 items-center gap-2 rounded text-left"
            aria-label={`Target details for ${owner.name}`}>
      <Avatar name={owner.name} size="sm" className={owner.inherited ? 'opacity-50' : ''} />
      <span className="min-w-0">
        <span className={`block truncate text-sm group-hover:text-primary group-hover:underline ${owner.inherited ? 'text-gray-400' : 'font-medium text-gray-800'}`}>
          {owner.name}
        </span>
        <span className="block truncate text-[11px] text-gray-400">{owner.type}</span>
      </span>
    </button>
  );
  return owner.inherited
    ? <Tooltip content="No direct owner — covered by the owner of a territory above">{cell}</Tooltip>
    : cell;
}

function GrowthCell({ pct }: { pct: string | null }) {
  if (pct === null) return <span className="text-gray-300">—</span>;
  const n = Number(pct);
  if (n === 0) return <span className="text-gray-500">0%</span>;
  return (
    <span className={n > 0 ? 'text-green-600' : 'text-red-600'}>
      {n > 0 ? '▲' : '▼'} {Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}%
    </span>
  );
}

function ShareCell({ pct }: { pct: string | null }) {
  if (pct === null) return <span className="text-gray-300">—</span>;
  const n = Math.max(0, Math.min(100, Number(pct)));
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-gray-100" aria-hidden="true">
        <span className="block h-full rounded-full bg-primary/60" style={{ width: `${n}%` }} />
      </span>
      <span className="tabular-nums text-gray-600">{pct}%</span>
    </span>
  );
}

function Row({ row, depth, ctx, startExpanded }: {
  row: GridRow; depth: number; ctx: Ctx; startExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(startExpanded ?? false);
  const expandable = row.children_count > 0;
  const hasGap = row.gap !== null && Number(row.gap) !== 0;
  const isRoot = depth === 0;

  return (
    <>
      <tr className={isRoot ? 'bg-gray-50/80 font-medium' : 'hover:bg-gray-50'}>
        <td className="px-4 py-2" style={{ paddingLeft: `${16 + depth * 20}px` }}>
          <span className="flex items-center gap-1.5">
            {expandable ? (
              <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}
                      className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                      aria-label={`${expanded ? 'Collapse' : 'Expand'} ${row.name}`}>
                {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
            ) : (
              <span className="w-5" aria-hidden="true" />
            )}
            <span className={isRoot ? 'font-semibold text-gray-900' : 'font-medium text-gray-900'}>{row.name}</span>
            <Badge variant="default">{row.level}</Badge>
            {expandable && !isRoot && (
              <span className="text-[11px] text-gray-400">({row.children_count})</span>
            )}
          </span>
        </td>
        <td className="px-4 py-2"><OwnerCell owner={row.owner} onOwner={ctx.onOwner} /></td>
        <td className="px-4 py-2 text-right tabular-nums">
          {row.override !== null ? (
            <Tooltip content={`Manual override — system number was ${ctx.fmt(row.original)}`}>
              <span className="inline-flex items-center gap-1 font-medium text-gray-900 underline decoration-dotted decoration-amber-400">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                {ctx.fmt(row.target)}
              </span>
            </Tooltip>
          ) : (
            <span className="font-medium text-gray-900">{ctx.fmt(row.target)}</span>
          )}
        </td>
        <td className="px-4 py-2 text-right tabular-nums text-gray-500">{ctx.fmt(row.base)}</td>
        <td className="px-4 py-2 text-right tabular-nums"><GrowthCell pct={row.growth_pct} /></td>
        <td className="px-4 py-2 text-right"><ShareCell pct={row.share_pct} /></td>
        <td className="px-4 py-2 text-right tabular-nums">
          {row.bottom_up === null ? (
            <span className="text-gray-300">—</span>
          ) : hasGap ? (
            <Tooltip content={`Children sum to ${ctx.fmt(row.bottom_up)} — ${ctx.fmt(row.gap)} off this territory's number`}>
              <span className="font-medium text-amber-600">{ctx.fmt(row.bottom_up)} ⚠</span>
            </Tooltip>
          ) : (
            <span className="text-gray-400">{ctx.fmt(row.bottom_up)}</span>
          )}
        </td>
        {ctx.showReview && (
          <td className="px-4 py-2 text-center">
            {row.review_status ? <StatusBadge status={row.review_status} /> : <span className="text-gray-300">—</span>}
          </td>
        )}
        <td className="px-4 py-2 text-center">
          {row.status ? <StatusBadge status={row.status} /> : <span className="text-gray-300">—</span>}
        </td>
        <td className="px-4 py-2 text-right">
          <span className="inline-flex items-center gap-1">
            {row.allocation_id !== null && ctx.canEdit(row) && (
              <button type="button" onClick={() => ctx.onEdit(row)} aria-label={`Edit ${row.name}`}
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-primary">
                <Pencil className="h-4 w-4" />
              </button>
            )}
            {row.allocation_id !== null && (
              <button type="button" onClick={() => ctx.onExplain(row)} aria-label={`Why this number — ${row.name}`}
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-primary">
                <Info className="h-4 w-4" />
              </button>
            )}
          </span>
        </td>
      </tr>
      {expanded && expandable && <Children parentId={row.geography_node_id} depth={depth + 1} ctx={ctx} />}
    </>
  );
}

function Children({ parentId, depth, ctx }: { parentId: number; depth: number; ctx: Ctx }) {
  const [pages, setPages] = useState(1);
  return (
    <>
      {Array.from({ length: pages }, (_, i) => (
        <LevelPage key={i} parentId={parentId} depth={depth} page={i + 1} ctx={ctx}
                   isLast={i === pages - 1} onLoadMore={() => setPages(pages + 1)} />
      ))}
    </>
  );
}

function LevelPage({ parentId, depth, page, ctx, isLast, onLoadMore }: {
  parentId: number; depth: number; page: number; ctx: Ctx; isLast: boolean; onLoadMore: () => void;
}) {
  const { data, isLoading } = useGrid(ctx.planId, {
    kpi: ctx.kpiId, parent: parentId, page, page_size: PAGE_SIZE,
  });
  const columns = ctx.showReview ? 10 : 9;
  if (isLoading) return <SkeletonRows depth={depth} columns={columns} count={2} />;
  if (!data) return null;
  const shown = page * PAGE_SIZE - (PAGE_SIZE - data.rows.length);
  return (
    <>
      {data.rows.map((child) => (
        <Fragment key={child.geography_node_id}>
          <Row row={child} depth={depth} ctx={ctx} />
        </Fragment>
      ))}
      {isLast && data.total > shown && (
        <tr>
          <td colSpan={columns} className="px-4 py-1.5" style={{ paddingLeft: `${16 + depth * 20}px` }}>
            <button type="button" onClick={onLoadMore}
                    className="text-xs font-medium text-primary hover:underline">
              Load more ({data.total - shown} of {data.total} remaining)
            </button>
          </td>
        </tr>
      )}
    </>
  );
}
