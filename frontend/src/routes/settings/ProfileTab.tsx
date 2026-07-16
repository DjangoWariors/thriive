import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { useAuth } from '../../hooks/useAuth';
import { authService } from '../../services/auth';
import { notify } from '../../utils/notify';
import { apiErrorMessage } from '../../utils/apiError';

const schema = z.object({
  first_name: z.string().min(1, 'First name is required'),
  last_name: z.string(),
  designation: z.string(),
  department: z.string(),
});

type FormValues = z.infer<typeof schema>;

export function ProfileTab() {
  const { user, fetchUser } = useAuth();
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      first_name: user?.first_name ?? '',
      last_name: user?.last_name ?? '',
      designation: user?.designation ?? '',
      department: user?.department ?? '',
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    setSaving(true);
    try {
      await authService.updateMe({
        first_name: values.first_name.trim(),
        last_name: values.last_name.trim(),
        designation: values.designation.trim(),
        department: values.department.trim(),
      });
      await fetchUser();
      notify.success('Profile updated');
    } catch (e) {
      setServerError(apiErrorMessage(e, 'Could not update profile'));
    } finally {
      setSaving(false);
    }
  });

  return (
    <Card title="Your profile" subtitle="Update your display details. Email, mobile and login ID are managed by an administrator.">
      <form onSubmit={onSubmit} className="max-w-xl space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="First name" {...register('first_name')} error={errors.first_name?.message} />
          <Input label="Last name" {...register('last_name')} />
          <Input label="Designation" {...register('designation')} />
          <Input label="Department" {...register('department')} />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 text-sm text-gray-500">
          <div>
            <span className="block text-xs font-medium uppercase text-gray-400">Email</span>
            {user?.email || '—'}
          </div>
          <div>
            <span className="block text-xs font-medium uppercase text-gray-400">Mobile</span>
            {user?.mobile || '—'}
          </div>
        </div>

        {serverError && <p className="text-sm text-danger">{serverError}</p>}

        <div className="flex justify-end border-t border-gray-100 pt-4">
          <Button type="submit" loading={saving} disabled={!isDirty}>
            Save changes
          </Button>
        </div>
      </form>
    </Card>
  );
}
