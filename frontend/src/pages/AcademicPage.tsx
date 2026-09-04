import type { Task } from '../api/client';

const ASSIGNMENT_CATEGORIES = new Set(['assignment']);
const EXAM_CATEGORIES = new Set(['exam']);
const STUDY_CATEGORIES = new Set(['study', 'project', 'academic']);

type Props = { tasks: Task[] };

export default function AcademicPage({ tasks }: Props) {
  const assignments = tasks.filter((t) => t.category && ASSIGNMENT_CATEGORIES.has(t.category.toLowerCase()));
  const exams = tasks.filter((t) => t.category && EXAM_CATEGORIES.has(t.category.toLowerCase()));
  const studyItems = tasks.filter((t) => t.category && STUDY_CATEGORIES.has(t.category.toLowerCase()));

  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Academic command center</p>
          <h2>Academic work</h2>
        </div>
        <span className="muted">{studyItems.length} study items</span>
      </div>

      <div className="grid">
        <div className="card">
          <div className="card-heading">
            <h2>Assignments</h2>
            <span className="number">{assignments.length}</span>
          </div>
          {assignments.length ? assignments.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.priority} priority
                {item.deadline ? ` · due ${new Date(item.deadline).toLocaleDateString()}` : ' · no deadline'}
              </span>
            </p>
          )) : <p className="empty-state muted">No assignments found.</p>}
        </div>

        <div className="card">
          <div className="card-heading">
            <h2>Exams</h2>
            <span className="number">{exams.length}</span>
          </div>
          {exams.length ? exams.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.priority} priority
                {item.deadline ? ` · ${new Date(item.deadline).toLocaleDateString()}` : ' · no date set'}
              </span>
            </p>
          )) : <p className="empty-state muted">No exams found.</p>}
        </div>

        <div className="card">
          <div className="card-heading">
            <h2>Study plan</h2>
            <span className="number">{studyItems.length}</span>
          </div>
          {studyItems.length ? studyItems.map((item) => (
            <p key={item.id}>
              <strong>{item.title}</strong><br />
              <span className="muted">
                {item.status}
                {item.deadline ? ` · ${new Date(item.deadline).toLocaleDateString()}` : ''}
              </span>
            </p>
          )) : <p className="empty-state muted">No study items found.</p>}
        </div>
      </div>
    </section>
  );
}