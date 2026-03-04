import { InputHTMLAttributes } from "react";

export const SearchInput = (props: InputHTMLAttributes<HTMLInputElement>) => (
  <input aria-label="Global search" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" {...props} />
);

export const Filters = ({ children }: { children: React.ReactNode }) => <div className="flex flex-wrap gap-2">{children}</div>;
