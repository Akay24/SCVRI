export default function WorkspaceLoading() {
  return (
    <div className="animate-pulse space-y-4 p-4">
      {/* Page header skeleton */}
      <div className="h-8 w-48 rounded-md bg-slate-200" />
      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 rounded-lg bg-slate-200" />
        ))}
      </div>
      {/* Chart row */}
      <div className="grid grid-cols-2 gap-4">
        <div className="h-56 rounded-lg bg-slate-200" />
        <div className="h-56 rounded-lg bg-slate-200" />
      </div>
      {/* Table skeleton */}
      <div className="rounded-lg bg-slate-200">
        <div className="h-10 rounded-t-lg bg-slate-300" />
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-10 border-t border-slate-300" />
        ))}
      </div>
    </div>
  );
}
