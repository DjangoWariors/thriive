import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus, Trash2 } from 'lucide-react';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { Spinner } from '../../components/ui/Spinner';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import {TableSkeleton} from '../../components/ui/Skeleton';
import {
  useSystemSettings,
  useUpdateSetting,
  useFeatureFlags,
  useCreateFeatureFlag,
  useUpdateFeatureFlag,
  useDeleteFeatureFlag,
} from '../../hooks/useSettings';
import { useAuth } from '../../hooks/useAuth';
import type { FeatureFlag, FeatureFlagScope, SystemSetting } from '../../types/settings';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const CATEGORY_ORDER: SystemSetting['category'][] = [
  'financial',
  'tds',
  'locale',
  'branding',
  'security',
  'feature',
];

const CATEGORY_LABELS: Record<SystemSetting['category'], string> = {
  financial: 'Financial',
  tds: 'TDS',
  locale: 'Locale',
  branding: 'Branding',
  security: 'Security',
  feature: 'Feature',
};

const MASK = '••••••';

export function SystemTab() {
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const { data: settings, isLoading } = useSystemSettings();

  if (isLoading || !settings) {
    return (
      <TableSkeleton/>
    );
  }

  const byCategory = CATEGORY_ORDER.map((cat) => ({
    cat,
    rows: settings.filter((s) => s.category === cat),
  })).filter((g) => g.rows.length > 0);

  return (
    <div className="space-y-6">
      {byCategory.map(({ cat, rows }) => (
        <Card key={cat} title={CATEGORY_LABELS[cat]} padding="none">
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-gray-100">
              {rows.map((s) => (
                <SettingRow key={s.id} setting={s} isSuperuser={isSuperuser} />
              ))}
            </tbody>
          </table>
        </Card>
      ))}

      <FeatureFlagsSection />
    </div>
  );
}

function SettingRow({ setting, isSuperuser }: { setting: SystemSetting; isSuperuser: boolean }) {
  const update = useUpdateSetting();
  const masked = setting.is_sensitive && !isSuperuser;
  const [value, setValue] = useState(() => stringify(setting.value));
  const [error, setError] = useState<string | null>(null);

  const dirty = !masked && value !== stringify(setting.value);

  const save = () => {
    setError(null);
    let parsed: unknown;
    try {
      parsed = parseByType(value, setting.value_type);
    } catch {
      setError('Invalid value for this type');
      return;
    }
    update.mutate(
      { id: setting.id, value: parsed },
      {
        onSuccess: () => notify.success(`${setting.key} updated`),
        onError: (e) => setError(apiErrorMessage(e, 'Could not update setting')),
      },
    );
  };

  return (
    <tr>
      <td className="px-6 py-3 align-top">
        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{setting.key}</code>
        {setting.description && <p className="mt-1 text-xs text-gray-500">{setting.description}</p>}
      </td>
      <td className="px-4 py-3">
        {masked ? (
          <span className="text-sm text-gray-400">{MASK} (hidden)</span>
        ) : setting.value_type === 'bool' ? (
          <Select
            options={[
              { value: 'true', label: 'Enabled' },
              { value: 'false', label: 'Disabled' },
            ]}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        ) : (
          <Input
            value={value}
            type={setting.value_type === 'number' ? 'number' : 'text'}
            onChange={(e) => setValue(e.target.value)}
            error={error ?? undefined}
          />
        )}
      </td>
      <td className="px-4 py-3 text-right align-top">
        <Button size="sm" variant="outline" onClick={save} loading={update.isPending} disabled={masked || !dirty}>
          Save
        </Button>
      </td>
    </tr>
  );
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function parseByType(raw: string, type: SystemSetting['value_type']): unknown {
  if (type === 'number') {
    const n = Number(raw);
    if (Number.isNaN(n)) throw new Error('not a number');
    return n;
  }
  if (type === 'bool') return raw === 'true';
  if (type === 'json') return JSON.parse(raw);
  return raw;
}

// ── Feature flags ────────────────────────────────────────────────────────────

const flagSchema = z.object({
  code: z.string().min(1, 'Code is required').regex(/^[a-z0-9_]+$/, 'Use a–z, 0–9, underscore'),
  description: z.string(),
  scope: z.enum(['global', 'role', 'entity_type']),
  scope_value: z.string(),
});
type FlagFormValues = z.infer<typeof flagSchema>;

function FeatureFlagsSection() {
  const { data: flags, isLoading } = useFeatureFlags();
  const updateFlag = useUpdateFeatureFlag();
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<FeatureFlag | null>(null);
  const del = useDeleteFeatureFlag();

  const toggle = (flag: FeatureFlag) => {
    updateFlag.mutate(
      { id: flag.id, payload: { is_enabled: !flag.is_enabled } },
      { onError: (e) => notify.error(apiErrorMessage(e, 'Could not update flag')) },
    );
  };

  const confirmDelete = () => {
    if (!deleting) return;
    del.mutate(deleting.id, {
      onSuccess: () => {
        notify.success(`${deleting.code} removed`);
        setDeleting(null);
      },
      onError: (e) => {
        notify.error(apiErrorMessage(e, 'Could not remove flag'));
        setDeleting(null);
      },
    });
  };

  return (
    <Card
      title="Feature flags"
      subtitle="Toggle capabilities on or off, optionally for one role or entity type."
      padding="none"
      actions={
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setFormOpen(true)}>
          Add flag
        </Button>
      }
    >
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-6 py-3">Code</th>
              <th className="px-4 py-3">Scope</th>
              <th className="px-4 py-3 text-center">Enabled</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(flags ?? []).map((f) => (
              <tr key={f.id} className="hover:bg-gray-50">
                <td className="px-6 py-3">
                  <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">{f.code}</code>
                  {f.description && <p className="mt-1 text-xs text-gray-500">{f.description}</p>}
                </td>
                <td className="px-4 py-3 text-gray-600">
                  {f.scope}
                  {f.scope_value ? `: ${f.scope_value}` : ''}
                </td>
                <td className="px-4 py-3 text-center">
                  <input
                    type="checkbox"
                    className="h-4 w-4 cursor-pointer accent-primary"
                    checked={f.is_enabled}
                    onChange={() => toggle(f)}
                    aria-label={`Toggle ${f.code}`}
                  />
                </td>
                <td className="px-4 py-3 text-right">
                  <Button variant="ghost" size="sm" onClick={() => setDeleting(f)}>
                    <Trash2 className="h-4 w-4 text-danger" />
                  </Button>
                </td>
              </tr>
            ))}
            {(flags ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-6 py-6 text-center text-sm text-gray-500">
                  No feature flags configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <Modal open={formOpen} onClose={() => setFormOpen(false)} title="Add feature flag" size="md">
        <FlagForm onDone={() => setFormOpen(false)} />
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
        title="Remove feature flag"
        message={`Remove flag ${deleting?.code ?? ''}? Code referencing it will fall back to disabled.`}
        confirmLabel="Remove"
        variant="danger"
      />
    </Card>
  );
}

function FlagForm({ onDone }: { onDone: () => void }) {
  const create = useCreateFeatureFlag();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FlagFormValues>({
    resolver: zodResolver(flagSchema),
    defaultValues: { code: '', description: '', scope: 'global', scope_value: '' },
  });

  const scope = watch('scope') as FeatureFlagScope;

  const onSubmit = handleSubmit((values) => {
    setServerError(null);
    create.mutate(
      {
        code: values.code.trim(),
        description: values.description.trim(),
        is_enabled: false,
        scope: values.scope,
        scope_value: values.scope === 'global' ? '' : values.scope_value.trim(),
      },
      {
        onSuccess: () => {
          notify.success('Feature flag created');
          onDone();
        },
        onError: (e) => setServerError(apiErrorMessage(e, 'Could not create flag')),
      },
    );
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Input label="Code" {...register('code')} error={errors.code?.message} placeholder="e.g. partner_portal" />
      <Input label="Description" {...register('description')} placeholder="Optional" />
      <Select
        label="Scope"
        options={[
          { value: 'global', label: 'Global' },
          { value: 'role', label: 'Role' },
          { value: 'entity_type', label: 'Entity Type' },
        ]}
        {...register('scope')}
      />
      {scope !== 'global' && (
        <Input
          label={scope === 'role' ? 'Role code' : 'Entity type code'}
          {...register('scope_value')}
          error={errors.scope_value?.message}
        />
      )}

      {serverError && <p className="text-sm text-danger">{serverError}</p>}

      <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={create.isPending}>
          Create flag
        </Button>
      </div>
    </form>
  );
}
