const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

export type ProfileResponse = {
  user: { id: number; email: string; full_name: string };
  profile: { id: number; timezone?: string; college?: string; degree?: string; year?: number; cgpa?: number; target_roles?: string; target_companies?: string; skills?: string; preferred_locations?: string; available_study_hours?: number; preferred_study_times?: string; notification_preferences?: string } | null;
};
export type ProfileInput = Omit<NonNullable<ProfileResponse['profile']>, 'id'> & { full_name?: string };

export type Task = { id: number; title: string; deadline: string | null; status: string; priority: string };
export type CalendarEvent = { id: number; title: string; starts_at: string; ends_at: string; event_type: string };
export type Approval = { id: number; action_type: string; description: string; status: string };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const api = {
  getProfile: () => request<ProfileResponse>('/profile'),
  saveProfile: (profile: ProfileInput, id?: number) => request<ProfileResponse>(id ? `/profile/${id}` : '/profile', { method: id ? 'PUT' : 'POST', body: JSON.stringify(profile) }),
  getTasks: () => request<Task[]>('/tasks'),
  getCalendar: () => request<CalendarEvent[]>('/calendar'),
  getApprovals: () => request<Approval[]>('/approvals'),
};