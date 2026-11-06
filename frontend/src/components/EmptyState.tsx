// Empty states shared by every data page.
export function EmptyState({
  title,
  message,
  action,
}: {
  title: string
  message: string
  action?: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center shadow-sm">
      <p className="text-base font-semibold text-navy-900">{title}</p>
      <p className="mt-1 text-sm text-slate-600">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
