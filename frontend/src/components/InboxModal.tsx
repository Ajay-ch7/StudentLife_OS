import { useState } from 'react';
import { api, type InboxProcessResponse } from '../api/client';

type Props = {
  isOpen: boolean;
  onClose: () => void;
  onTasksUpdated: () => void;
};

export default function InboxModal({ isOpen, onClose, onTasksUpdated }: Props) {
  const [content, setContent] = useState('');
  const [sourceType, setSourceType] = useState('email');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<InboxProcessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleProcess(dryRun: boolean) {
    if (!content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const response = dryRun
        ? await api.previewInbox(content, sourceType)
        : await api.processInbox(content, sourceType);
      setResult(response);
      if (!dryRun && response.tasks_created.length > 0) {
        onTasksUpdated();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to process inbox content.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Autonomous Ingestion</p>
            <h2>AI Inbox & Document Extractor</h2>
          </div>
          <button className="btn-close" onClick={onClose} aria-label="Close modal">×</button>
        </div>

        <p className="muted">
          Paste an email, assignment announcement, or syllabus excerpt. The local AI agent will safely extract actionable tasks, verify deadlines, and detect calendar conflicts.
        </p>

        <div className="form-group" style={{ marginTop: '1rem' }}>
          <label htmlFor="source-type">Source Category</label>
          <select
            id="source-type"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            disabled={loading}
          >
            <option value="email">Course Email / Announcement</option>
            <option value="syllabus">Syllabus / Schedule Document</option>
            <option value="chat">Discord / Slack Study Group</option>
            <option value="assignment">Assignment Handout</option>
          </select>
        </div>

        <div className="form-group" style={{ marginTop: '0.75rem' }}>
          <label htmlFor="inbox-content">Content / Message Snippet</label>
          <textarea
            id="inbox-content"
            rows={6}
            placeholder="e.g. 'CS301 Assignment 2 on BCNF Normalization is due next Tuesday at 11:59 PM. Please submit through Canvas.'"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={loading}
          />
        </div>

        {error && <div className="notice error" style={{ marginTop: '0.75rem' }}>{error}</div>}

        <div className="modal-actions" style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleProcess(true)}
            disabled={loading || !content.trim()}
          >
            {loading ? 'Analyzing...' : 'Preview Extraction'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => handleProcess(false)}
            disabled={loading || !content.trim()}
          >
            {loading ? 'Processing...' : 'Extract & Save Tasks'}
          </button>
        </div>

        {result && (
          <div className="extraction-results" style={{ marginTop: '1.25rem', padding: '1rem', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)' }}>
            <h3 style={{ fontSize: '1rem', margin: '0 0 0.5rem 0' }}>Extraction Summary</h3>
            <p style={{ margin: '0 0 0.75rem 0', color: 'var(--text-muted)' }}>{result.summary}</p>
            
            {result.tasks_created.length > 0 ? (
              <div>
                <strong>{result.dry_run ? 'Tasks Detected (Preview)' : 'Tasks Created in Database'}:</strong>
                <ul style={{ margin: '0.5rem 0 0 0', paddingLeft: '1.25rem' }}>
                  {result.tasks_created.map((t, i) => (
                    <li key={i} style={{ marginBottom: '0.25rem' }}>
                      <strong>{t.title}</strong> — <span className="muted">{t.priority} priority</span>
                      {t.deadline && <span> • Due: {new Date(t.deadline).toLocaleDateString()}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="muted">No new tasks created.</p>
            )}

            {result.skipped_duplicates.length > 0 && (
              <p style={{ margin: '0.5rem 0 0 0', color: '#e0af68', fontSize: '0.85rem' }}>
                ℹ️ Skipped {result.skipped_duplicates.length} duplicate task(s): {result.skipped_duplicates.join(', ')}
              </p>
            )}

            {result.detected_conflicts.length > 0 && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'rgba(247, 118, 142, 0.1)', border: '1px solid rgba(247, 118, 142, 0.3)', borderRadius: '4px' }}>
                <strong style={{ color: '#f7768e' }}>⚠️ Calendar Conflict Detected:</strong>
                {result.detected_conflicts.map((c, i) => (
                  <div key={i} style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>
                    Deadline for &apos;{c.task_title}&apos; overlaps with: {c.conflicts.map(ev => ev.title).join(', ')}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
