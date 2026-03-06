import { PropsWithChildren } from "react";

export const Modal = ({ title, children }: PropsWithChildren<{ title: string }>) => (
  <div role="dialog" aria-label={title} className="rounded-lg border border-stroke bg-card p-4 shadow-xl">
    <h3 className="mb-2 font-semibold text-ink">{title}</h3>
    {children}
  </div>
);

export const Drawer = ({ title, children }: PropsWithChildren<{ title: string }>) => (
  <aside aria-label={title} className="h-full w-full max-w-md border-l border-stroke bg-card p-4 shadow-xl">
    <h3 className="mb-3 font-semibold text-ink">{title}</h3>
    {children}
  </aside>
);

export const Dropdown = ({ children }: PropsWithChildren) => (
  <div className="rounded-md border border-stroke bg-card p-2">{children}</div>
);
