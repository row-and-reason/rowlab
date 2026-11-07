/** The thin toolbar at the top of each column: a title on the left, actions on the right. */
export function PaneHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-11 shrink-0 items-center gap-2 border-b bg-card px-3 text-sm">{children}</div>
  );
}
