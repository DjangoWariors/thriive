export interface AppNotification {
  id: number;
  code: string;
  category: string;
  title: string;
  body: string;
  link: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}
