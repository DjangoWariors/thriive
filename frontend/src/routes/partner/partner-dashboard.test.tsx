import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import PartnerDashboard from './dashboard';
import { achievementService } from '../../services/achievementService';
import { targetService } from '../../services/targetService';

vi.mock('../../services/achievementService', () => ({
  achievementService: { dashboard: vi.fn() },
}));
vi.mock('../../services/targetService', () => ({
  targetService: { listPeriods: vi.fn() },
}));

const period = {
  id: 7, name: 'This month', code: 'NOW', period_type: 'monthly',
  start_date: '2000-01-01', end_date: '2099-12-31',
};

function renderPartner() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <PartnerDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(targetService.listPeriods).mockResolvedValue({
    count: 1, next: null, previous: null, results: [period],
  } as never);
});

describe('partner dashboard', () => {
  it('shows an error card with Retry when the fetch fails (not the empty state)', async () => {
    vi.mocked(achievementService.dashboard).mockRejectedValue(new Error('boom'));
    renderPartner();

    expect(await screen.findByText("Couldn't load your performance")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText('No targets for this period')).not.toBeInTheDocument();
  });

  it('refetches when Retry is clicked', async () => {
    vi.mocked(achievementService.dashboard).mockRejectedValue(new Error('boom'));
    renderPartner();

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(vi.mocked(achievementService.dashboard).mock.calls.length).toBeGreaterThanOrEqual(2),
    );
  });
});
