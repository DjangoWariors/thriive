import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from './Button';

interface PaginationProps {
  count: number;
  page: number;
  pageSize?: number;
  onPageChange: (page: number) => void;
  className?: string;
}


export function Pagination({ count, page, pageSize = 25, onPageChange, className }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(count / pageSize));
  if (count <= pageSize) return null;

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, count);

  return (
    <div
      className={
        'flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm text-gray-600 ' +
        (className ?? '')
      }
    >
      <span>
        Showing <strong>{from}</strong>–<strong>{to}</strong> of <strong>{count}</strong>
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          icon={<ChevronLeft className="h-4 w-4" />}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Prev
        </Button>
        <span className="px-1 text-xs text-gray-500">
          Page {page} of {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          iconRight={<ChevronRight className="h-4 w-4" />}
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
