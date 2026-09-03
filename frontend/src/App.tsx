export default function App() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Student Life OS</p>
          <h1>Local-first student productivity dashboard</h1>
        </div>
      </header>

      <section className="grid">
        <div className="card">
          <h2>Today</h2>
          <ul>
            <li>DBMS assignment due tomorrow</li>
            <li>Project meeting at 5:00 PM</li>
            <li>DSA revision block scheduled</li>
          </ul>
        </div>

        <div className="card">
          <h2>Opportunities</h2>
          <ul>
            <li>Salesforce internship match: 86%</li>
            <li>Skill gap: data structures + SQL</li>
          </ul>
        </div>

        <div className="card">
          <h2>Study plan</h2>
          <ul>
            <li>ML revision: 45 min</li>
            <li>DBMS practice: 60 min</li>
            <li>System design review: 30 min</li>
          </ul>
        </div>
      </section>
    </main>
  );
}
