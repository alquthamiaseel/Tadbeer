// ---------------------------------------------------------------------------
// ComingSoon
// ---------------------------------------------------------------------------
// A placeholder page for sidebar links that don't have real content yet
// (Project Overview, Requirements, Diagrams, Timeline, Settings). This
// keeps every sidebar link working today, without having to build out
// pages that weren't asked for yet - each one can be replaced with a
// real page later without touching the sidebar or routing.
// ---------------------------------------------------------------------------
export default function ComingSoon({ title }) {
  return (
    <div>
      <h1 className="text-3xl font-bold text-slate-900">{title}</h1>
      <div className="mt-6 flex h-64 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white">
        <p className="text-slate-400">This page is coming soon.</p>
      </div>
    </div>
  )
}
