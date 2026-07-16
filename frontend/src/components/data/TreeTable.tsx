import { Fragment, type ReactNode, useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import { cn } from '../../utils/cn';

export interface TreeColumn<T> {
  key: string;
  header: string;
  align?: 'left' | 'right' | 'center';
  /** Cell content. The first column also gets the expand chevron + indentation. */
  render: (node: T, depth: number) => ReactNode;
}

interface TreeTableProps<T> {
  roots: T[];
  getId: (node: T) => number | string;
  getChildren: (node: T) => T[];
  columns: TreeColumn<T>[];
  /** Rows shallower than this depth start expanded. Default: top two levels. */
  defaultExpandedDepth?: number;
  rowClassName?: (node: T) => string | undefined;
}

const ALIGN: Record<string, string> = { left: 'text-left', right: 'text-right', center: 'text-center' };

export function TreeTable<T>({
  roots,
  getId,
  getChildren,
  columns,
  defaultExpandedDepth = 2,
  rowClassName,
}: TreeTableProps<T>) {
  // Only stores rows the user has toggled away from their default open/closed state.
  const [overrides, setOverrides] = useState<Map<string, boolean>>(new Map());
  const idOf = (n: T) => String(getId(n));
  const isOpen = (id: string, depth: number) =>
    overrides.has(id) ? (overrides.get(id) as boolean) : depth < defaultExpandedDepth;

  const toggle = (id: string, depth: number) =>
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(id, !isOpen(id, depth));
      return next;
    });

  const rows: { node: T; depth: number }[] = [];
  const walk = (node: T, depth: number) => {
    rows.push({ node, depth });
    const kids = getChildren(node) ?? [];
    if (kids.length && isOpen(idOf(node), depth)) kids.forEach((k) => walk(k, depth + 1));
  };
  roots.forEach((r) => walk(r, 0));

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={cn('px-4 py-3', ALIGN[c.align ?? 'left'])}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map(({ node, depth }) => {
            const id = idOf(node);
            const hasKids = (getChildren(node) ?? []).length > 0;
            const open = isOpen(id, depth);
            return (
              <tr key={id} className={cn('hover:bg-gray-50', rowClassName?.(node))}>
                {columns.map((c, ci) => (
                  <td key={c.key} className={cn('px-4 py-2.5', ALIGN[c.align ?? 'left'])}>
                    {ci === 0 ? (
                      <div className="flex items-center" style={{ paddingLeft: `${depth * 18}px` }}>
                        {hasKids ? (
                          <button type="button" onClick={() => toggle(id, depth)}
                            className="mr-1 text-gray-400 hover:text-primary" aria-label={open ? 'Collapse' : 'Expand'}>
                            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>
                        ) : (
                          <span className="mr-1 inline-block w-4" />
                        )}
                        {c.render(node, depth)}
                      </div>
                    ) : (
                      <Fragment>{c.render(node, depth)}</Fragment>
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
