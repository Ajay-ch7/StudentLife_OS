const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

export type ProfileResponse = {
  user: { id: number; email: string; full_name: string };
  profile: { id: number; timezone?: string; college?: string; degree?: string; year?: number; cgpa?: number; target_roles?: string; target_companies?: string; skills?: string; preferred_locations?: string; available_study_hours?: number; preferred_study_times?: string; notification_preferences?: string } | null;
};
export type ProfileInput = Omit<NonNullable<ProfileResponse['profile']>, 'id'> & { full_name?: string };

export type Task = { id: number; user_id: number; title: string; description: string | null; deadline: string | null; status: string; priority: string; category: string | null; estimated_effort_hours: number | null; source: string | null; is_confirmed_deadline: boolean; is_overdue: boolean };
export type CalendarEvent = { id: number; user_id: number; task_id: number | null; title: string; description: string | null; starts_at: string; ends_at: string; event_type: string; location: string | null };
export type CalendarEventInput = Omit<CalendarEvent, 'id' | 'user_id'>;
export type Conflict = { has_conflict: boolean; reasons: string[] };
export type Approval = { id: number; action_type: string; description: string; metadata_json?: string | null; expires_at?: string | null; result_json?: string | null; status: string };
export type Assignment = { id: number; course_name: string; title: string; description: string | null; due_at: string; status: string };
export type Exam = { id: number; course_name: string; title: string; starts_at: string; notes: string | null };
export type StudySession = { id: number; topic: string; task_id: number | null; planned_start: string; planned_end: string; actual_start: string | null; actual_end: string | null; status: string };
export type Opportunity = { id: number; title: string; company: string; description: string; required_skills: string | null; match_score: number | null; source: string };
export type DSAProgress = { total: number; streak: number; topics: Record<string, number>; weak_topics: string[]; problems: Array<{ id: number; title: string; topic: string; difficulty: string; solved_on: string; needs_revision: boolean }> };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export type InboxProcessResponse = {
  workflow_id: string;
  status: string;
  summary: string;
  total_extracted: number;
  tasks_created: Array<{ id: number | null; title: string; deadline: string | null; priority: string; category: string | null }>;
  skipped_duplicates: string[];
  detected_conflicts: Array<{ task_title: string; deadline: string; conflicts: Array<{ id: number; title: string; starts_at: string; ends_at: string }> }>;
  dry_run: boolean;
};

export type MorningBriefingResponse = {
  workflow_id: string;
  status: string;
  student_name: string;
  briefing: {
    greeting: string;
    quote_or_motto: string | null;
    top_priorities: string[];
    schedule_overview: string;
    urgent_alerts: string[];
    recommended_recovery_action: string | null;
  };
  formatted_text: string;
  delivery_status: string;
  mocked_delivery: boolean;
  tasks_count: number;
  events_today_count: number;
};

export const api = {
  getProfile: () => request<ProfileResponse>('/profile'),
  saveProfile: (profile: ProfileInput, id?: number) => request<ProfileResponse>(id ? `/profile/${id}` : '/profile', { method: id ? 'PUT' : 'POST', body: JSON.stringify(profile) }),
  getTasks: () => request<Task[]>('/tasks'),
  createTask: (task: Omit<Task, 'id' | 'user_id' | 'is_overdue'>) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  updateTask: (id: number, task: Partial<Omit<Task, 'id' | 'user_id' | 'is_overdue'>>) => request<Task>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(task) }),
  deleteTask: (id: number) => request<void>(`/tasks/${id}`, { method: 'DELETE' }),
  getCalendar: () => request<CalendarEvent[]>('/calendar'),
  checkCalendarConflicts: (event: CalendarEventInput) => request<Conflict>('/calendar/conflicts', { method: 'POST', body: JSON.stringify(event) }),
  createCalendarEvent: (event: CalendarEventInput) => request<CalendarEvent>('/calendar/events', { method: 'POST', body: JSON.stringify(event) }),
  getApprovals: () => request<Approval[]>('/approvals'),
  createApproval: (approval: { action_type: string; description: string; metadata_json?: string; expires_at?: string }) => request<Approval>('/approvals', { method: 'POST', body: JSON.stringify(approval) }),
  approve: (id: number) => request<Approval>(`/approvals/${id}/approve`, { method: 'PUT', body: '{}' }),
  reject: (id: number) => request<Approval>(`/approvals/${id}/reject`, { method: 'PUT', body: '{}' }),
  getAssignments: () => request<Assignment[]>('/academic/assignments'),
  getExams: () => request<Exam[]>('/academic/exams'),
  getStudySessions: () => request<StudySession[]>('/academic/study-sessions'),
  requestRecovery: () => request<{ approval_request_id: number | null }>('/focus/recovery', { method: 'POST', body: '{}' }),
  startFocusSession: (id: number) => request<StudySession>(`/focus/sessions/${id}/start`, { method: 'PUT', body: '{}' }),
  endFocusSession: (id: number) => request<StudySession>(`/focus/sessions/${id}/end`, { method: 'PUT', body: '{}' }),
  getOpportunities: () => request<Opportunity[]>('/opportunities'),
  getDsa: () => request<DSAProgress>('/dsa'),
  getDsaRecommendations: () => request<{ topics: string[]; recommendation: string }>('/dsa/recommendations'),
  processInbox: (content: string, source_type = 'email') => request<InboxProcessResponse>('/inbox/process', { method: 'POST', body: JSON.stringify({ content, source_type }) }),
  previewInbox: (content: string, source_type = 'email') => request<InboxProcessResponse>('/inbox/preview', { method: 'POST', body: JSON.stringify({ content, source_type }) }),
  generateBriefing: (send_notification = false, chat_id?: string) => request<MorningBriefingResponse>('/workflows/morning-briefing', { method: 'POST', body: JSON.stringify({ send_notification, chat_id }) }),
  getNotifications: () => request<Array<{ id: number; type: string; message: string; metadata: string | null; created_at: string }>>('/notifications'),
};