import { PropsWithChildren } from "react";

/** Full-screen backdrop modal — pass `open` and `onClose` for lifecycle control */
export const Modal = ({
  title,
  children,
  open,
  onClose,
}: PropsWithChildren<{ title: string; open?: boolean; onClose?: () => void }>) => {
  if (open === false) return null;
  return (
    <div
      role="dialog"
      aria-label={title}
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Panel */}
      <div className="relative z-10 w-full max-w-lg rounded-xl border border-stroke bg-card p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-ink">{title}</h3>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-ink-3 transition-colors hover:bg-surface hover:text-ink"
            >
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M2 2l12 12M14 2L2 14" />
              </svg>
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
};

export const Drawer = ({ title, children }: PropsWithChildren<{ title: string }>) => (
  <aside aria-label={title} className="h-full w-full max-w-md border-l border-stroke bg-card p-4 shadow-xl">
    <h3 className="mb-3 font-semibold text-ink">{title}</h3>
    {children}
  </aside>
);

export const Dropdown = ({ children }: PropsWithChildren) => (
  <div className="rounded-md border border-stroke bg-card p-2">{children}</div>
);
