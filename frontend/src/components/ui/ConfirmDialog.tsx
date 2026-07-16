import { Modal } from './Modal';
import { Button } from './Button';

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  variant?: 'danger' | 'warning';
  className?: string;
}

export function ConfirmDialog({
  open,
  onClose,
  title = 'Confirm',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  onConfirm,
  variant = 'danger',
  className,
}: ConfirmDialogProps) {
  const handleConfirm = () => {
    onConfirm();
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title={title} size="sm" className={className}>
      <p className="text-sm text-gray-600">{message}</p>
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" size="sm" onClick={onClose}>
          {cancelLabel}
        </Button>
        <Button
          variant={variant === 'danger' ? 'danger' : 'primary'}
          size="sm"
          onClick={handleConfirm}
          className={
            variant === 'warning'
              ? 'bg-warning hover:bg-warning/90 focus:ring-warning/30'
              : ''
          }
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
