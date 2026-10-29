export interface UserRef {
  id: string;
  display_name?: string | null;
  email?: string | null;
}

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  role: 'viewer' | 'admin';
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: { field: string; message: string }[] | null;
}
