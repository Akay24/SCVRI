import { PropsWithChildren } from "react";

export const PageTitle = ({ children }: PropsWithChildren) => <h1 className="text-3xl font-semibold">{children}</h1>;
export const SectionTitle = ({ children }: PropsWithChildren) => <h2 className="text-xl font-semibold">{children}</h2>;
export const CardTitle = ({ children }: PropsWithChildren) => <h3 className="text-base font-semibold">{children}</h3>;
export const BodyText = ({ children }: PropsWithChildren) => <p className="text-sm text-slate-700">{children}</p>;
export const CaptionText = ({ children }: PropsWithChildren) => <p className="text-xs text-slate-500">{children}</p>;
