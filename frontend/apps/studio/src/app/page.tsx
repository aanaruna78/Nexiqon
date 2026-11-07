const phases = [
  { name: "Platform foundation", detail: "Identity, authorization, configuration, events" },
  { name: "Knowledge plane", detail: "Ingestion, hybrid retrieval, cited answers" },
  { name: "Agent plane", detail: "Assistant builder, Answer Inspector, actions" },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-4 py-16">
      <header className="space-y-2">
        <p className="text-sm font-semibold uppercase tracking-wide text-teal-700">ThinkHiveLabs</p>
        <h1 className="text-4xl font-bold text-slate-900">Nexiqon Studio</h1>
        <p className="text-lg text-slate-600">
          Phase 0 scaffold. The design system and Studio shell arrive in Phase 1 (UX-04 to ST-02).
        </p>
      </header>
      <ol className="space-y-3">
        {phases.map((phase, index) => (
          <li key={phase.name} className="rounded-lg border border-slate-200 bg-white p-4">
            <span className="text-sm text-slate-500">Next {index + 1}</span>
            <h2 className="font-semibold text-slate-900">{phase.name}</h2>
            <p className="text-slate-600">{phase.detail}</p>
          </li>
        ))}
      </ol>
    </main>
  );
}
