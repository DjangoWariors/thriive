import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import Dashboard from './index';
import { achievementService } from '../../services/achievementService';
import { kpiService } from '../../services/kpiService';
import { useAuthStore } from '../../stores/authStore';
import type { DashboardData } from '../../types/achievement';
import type { User } from '../../types/auth';

vi.mock('../../services/achievementService', () => ({
  achievementService: {
    dashboard: vi.fn(),
    compute: vi.fn(),
    acknowledgeAlert: vi.fn(),
    territory: vi.fn(),
  },
}));
vi.mock('../../services/kpiService', () => ({
  kpiService: { list: vi.fn() },
}));
vi.mock('../../services/incentiveService', () => ({
  incentiveService: { listCycles: vi.fn() },
}));

function seedUser(permissions: Record<string, string>) {
  const user: User = {
    id: 1, email: 'a@x.com', mobile: null, employee_id: null,
    first_name: 'Asha', last_name: 'K', designation: '', department: '',
    is_superuser: false,
    active_roles: [{ id: 1, code: 'r', name: 'r', permissions }],
    entity_info: null, portal_type: 'admin', date_joined: '2026-01-01',
  };
  useAuthStore.setState({ user, isAuthenticated: true });
}

function dashboardData(overrides: Partial<DashboardData> = {}): DashboardData {
  return {
    entity: { id: 1, name: 'National', code: 'NSM', type: 'NSM' },
    summary: {
      overall_achievement_pct: '85.00', projected_pct: '92.00',
      primary_target: '100000', primary_achieved: '85000', primary_kpi_name: 'Primary Sales',
      estimated_payout: '12500.00', payout_kind: 'estimate', active_entities: 4, open_alerts: 0,
    },
    kpi_cards: [{
      id: 11, kpi_code: 'PRIMARY', kpi_name: 'Primary Sales', unit: 'INR', weight_pct: null,
      target: '100000', achieved: '85000', pct: '85.00', projected_pct: '92.00',
      required_run_rate: '1500', gap: '15000', growth_pct: null, multiplier: null,
      is_provisional: true,
    }],
    child_ranking: null, trend: [], channel_mix: [], alerts: [],
    modules: { incentives: true, exceptions: true },
    ...overrides,
  };
}

function renderDashboard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/?period=1']}>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(kpiService.list).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
});

describe('admin dashboard', () => {
  it('renders summary tiles with an estimate payout subtitle', async () => {
    seedUser({ achievement_view: 'view_all' });
    vi.mocked(achievementService.dashboard).mockResolvedValue(dashboardData());
    renderDashboard();

    expect(await screen.findByText('Estimated Payout')).toBeInTheDocument();
    expect(screen.getByText('Estimate — updates nightly')).toBeInTheDocument();
    expect(screen.getByText('Overall Achievement')).toBeInTheDocument();
    expect(screen.getByText(/Welcome back, Asha/)).toBeInTheDocument();
  });

  it('labels a finalized payout from payout_kind', async () => {
    seedUser({ achievement_view: 'view_all' });
    const data = dashboardData();
    data.summary.payout_kind = 'final';
    vi.mocked(achievementService.dashboard).mockResolvedValue(data);
    renderDashboard();

    expect(await screen.findByText('Finalized for this period')).toBeInTheDocument();
    expect(screen.getByText('Payout')).toBeInTheDocument();
    expect(screen.queryByText('Estimated Payout')).not.toBeInTheDocument();
  });

  it('offers Retry on error to everyone, Run computation only with the compute grant', async () => {
    seedUser({ achievement_view: 'view_all' });
    vi.mocked(achievementService.dashboard).mockRejectedValue(new Error('boom'));
    const { unmount } = renderDashboard();

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Run computation/ })).not.toBeInTheDocument();
    unmount();

    seedUser({ achievement_view: 'view_all', achievement_compute: 'full' });
    renderDashboard();
    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Run computation/ })).toBeInTheDocument();
  });

  it('retries the fetch when Retry is clicked', async () => {
    seedUser({ achievement_view: 'view_all' });
    vi.mocked(achievementService.dashboard).mockRejectedValue(new Error('boom'));
    renderDashboard();

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await screen.findByRole('button', { name: 'Retry' });
    expect(vi.mocked(achievementService.dashboard).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('shows the empty state when nothing is computed yet', async () => {
    seedUser({ achievement_view: 'view_all' });
    vi.mocked(achievementService.dashboard).mockResolvedValue(
      dashboardData({ kpi_cards: [], child_ranking: null }),
    );
    renderDashboard();

    expect(await screen.findByText('No achievements yet')).toBeInTheDocument();
  });
});
