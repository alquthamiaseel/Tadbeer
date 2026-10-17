// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------
// One of the 4 small summary cards at the top of the dashboard (e.g.
// "Active Projects", "Approved Items"...). `value` is optional so a stat
// with no real data behind it yet can still render as icon + label only,
// instead of a misleading fake number.
// ---------------------------------------------------------------------------
export default function StatCard({ icon: Icon, label, iconColorClass, value }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6">
      <div
        className={`mb-4 flex h-11 w-11 items-center justify-center rounded-xl ${iconColorClass}`}
      >
        <Icon className="h-5 w-5" />
      </div>
      {value !== undefined && <p className="text-2xl font-bold text-slate-900">{value}</p>}
      <p className="font-medium text-slate-500">{label}</p>
    </div>
  )
}
