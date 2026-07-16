import { toast } from 'sonner';

/**
 * Single entry point for toast notifications across the app.
 *
 * Always import from here — never `import {toast} from 'sonner'` directly — so
 * defaults (duration, styling, future icons) stay controlled in one place.
 */
export const notify = {
  success: (message: string) => toast.success(message),
  error: (message: string) => toast.error(message),
  info: (message: string) => toast.info(message),
  warning: (message: string) => toast.warning(message),
  promise: toast.promise,
  dismiss: toast.dismiss,
};
