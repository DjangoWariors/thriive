import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { authService } from '../../services/auth';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const schema = z
  .object({
    old_password: z.string().min(1, 'Enter your current password'),
    new_password: z.string().min(8, 'Use at least 8 characters'),
    confirm: z.string().min(1, 'Confirm your new password'),
  })
  .refine((v) => v.new_password === v.confirm, {
    path: ['confirm'],
    message: 'Passwords do not match',
  });

type FormValues = z.infer<typeof schema>;

export function PasswordTab() {
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { old_password: '', new_password: '', confirm: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    setSaving(true);
    try {
      await authService.changePassword(values.old_password, values.new_password);
      notify.success('Password changed');
      reset();
    } catch (e) {
      setServerError(apiErrorMessage(e, 'Could not change password'));
    } finally {
      setSaving(false);
    }
  });

  return (
    <Card title="Change password" subtitle="Choose a strong password you don't use elsewhere.">
      <form onSubmit={onSubmit} className="max-w-md space-y-4">
        <Input
          label="Current password"
          type="password"
          autoComplete="current-password"
          {...register('old_password')}
          error={errors.old_password?.message}
        />
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          {...register('new_password')}
          error={errors.new_password?.message}
        />
        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          {...register('confirm')}
          error={errors.confirm?.message}
        />

        {serverError && <p className="text-sm text-danger">{serverError}</p>}

        <div className="flex justify-end border-t border-gray-100 pt-4">
          <Button type="submit" loading={saving}>
            Update password
          </Button>
        </div>
      </form>
    </Card>
  );
}
