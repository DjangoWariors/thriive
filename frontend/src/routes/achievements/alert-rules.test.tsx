import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import AlertRulesPage from './alert-rules';
import { achievementService } from '../../services/achievementService';
import type { AlertRule } from '../../types/achievement';

vi.mock('../../services/achievementService', () => ({
  achievementService: {
    listAlertRules: vi.fn(),
    createAlertRule: vi.fn(),
    updateAlertRule: vi.fn(),
  },
}));
vi.mock('../../services/entityService', () => ({
  entityService: { listTypes: vi.fn(), listChannels: vi.fn() },
}));
vi.mock('../../services/kpiService', () => ({
  kpiService: { list: vi.fn() },
}));

import { entityService } from '../../services/entityService';
import { kpiService } from '../../services/kpiService';

const rule: AlertRule = {
  id: 3, name: 'Target at risk', code: 'AT_RISK', metric: 'projected_pct',
  comparator: 'lt', threshold: '90.0000', scope_entity_types: ['ASE'], scope_channels: [],
  kpi: null, severity: 'critical', recipient_role: '',
  message_template: '{entity}: {metric} is {value}', is_enabled: true, version: 2, is_current: true,
};

const emptyPage = { count: 0, next: null, previous: null, results: [] };

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/achievements/alert-rules']}>
        <AlertRulesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(entityService.listTypes).mockResolvedValue(emptyPage as never);
  vi.mocked(entityService.listChannels).mockResolvedValue(emptyPage as never);
  vi.mocked(kpiService.list).mockResolvedValue(emptyPage as never);
});

describe('alert rules page', () => {
  it('renders configured rules with their condition and severity', async () => {
    vi.mocked(achievementService.listAlertRules).mockResolvedValue({
      count: 1, next: null, previous: null, results: [rule],
    });
    renderPage();

    expect(await screen.findByText('AT_RISK')).toBeInTheDocument();
    expect(screen.getByText('Target at risk')).toBeInTheDocument();
    expect(screen.getByText(/Projected month-end % .* 90/)).toBeInTheDocument();
    expect(screen.getByText('critical')).toBeInTheDocument();
  });

  it('creates a rule from the modal form', async () => {
    vi.mocked(achievementService.listAlertRules).mockResolvedValue({
      count: 0, next: null, previous: null, results: [],
    });
    vi.mocked(achievementService.createAlertRule).mockResolvedValue(rule);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /New rule/ }));
    expect(await screen.findByText('New alert rule')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('e.g. Target at risk'), {
      target: { value: 'Pacing below plan' },
    });
    fireEvent.change(screen.getByPlaceholderText('AT_RISK'), {
      target: { value: 'below plan' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create rule' }));

    await waitFor(() => expect(achievementService.createAlertRule).toHaveBeenCalled());
    const payload = vi.mocked(achievementService.createAlertRule).mock.calls[0][0];
    expect(payload).toMatchObject({
      name: 'Pacing below plan',
      code: 'BELOW_PLAN',
      metric: 'projected_pct',
      comparator: 'lt',
      is_enabled: true,
    });
  });
});
