"use client";

import { useState, FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAppStore } from "@/store/useAppStore";
import { Role } from "@/types/navigation";

const inputCls =
  "w-full rounded-md border border-stroke bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none placeholder:text-ink-3";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const setUser = useAppStore((s) => s.setUser);

  const [step, setStep] = useState<"credentials" | "mfa">("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const redirectTo = params.get("from") ?? "/dashboard";

  async function handleCredentials(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? data.error ?? "Login failed");
        return;
      }
      if (data.mfaRequired) {
        setSessionToken(data.sessionToken);
        setStep("mfa");
        return;
      }
      setUser({ id: data.userId, tenantId: data.tenantId, role: data.role as Role });
      router.replace(redirectTo);
    } catch {
      setError("Network error — please try again");
    } finally {
      setLoading(false);
    }
  }

  async function handleMfa(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/mfa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionToken, code: mfaCode }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? data.error ?? "MFA verification failed");
        return;
      }
      setUser({ id: data.userId, tenantId: data.tenantId, role: data.role as Role });
      router.replace(redirectTo);
    } catch {
      setError("Network error — please try again");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4">
      <div className="w-full max-w-sm">
        {/* Wordmark */}
        <div className="mb-8 text-center">
          <span className="text-2xl font-black tracking-tight text-ink">
            SCV<span className="text-accent">RI</span>
          </span>
          <p className="mt-1 text-sm text-ink-3">Supply Chain Visibility &amp; Risk Intelligence</p>
        </div>

        <div className="rounded-xl border border-stroke bg-card p-8 shadow-sm">
          {step === "credentials" ? (
            <>
              <h1 className="mb-6 text-lg font-semibold text-ink">Sign in to your workspace</h1>
              <form onSubmit={handleCredentials} className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink-3">Email</label>
                  <input
                    type="email"
                    required
                    autoComplete="email"
                    autoFocus
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink-3">Password</label>
                  <input
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className={inputCls}
                  />
                </div>
                {error && (
                  <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-400">
                    {error}
                  </p>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  {loading ? "Signing in…" : "Sign in"}
                </button>
              </form>
            </>
          ) : (
            <>
              <h1 className="mb-2 text-lg font-semibold text-ink">Two-factor authentication</h1>
              <p className="mb-6 text-sm text-ink-3">Enter the 6-digit code from your authenticator app.</p>
              <form onSubmit={handleMfa} className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink-3">Authentication code</label>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="\d{6}"
                    maxLength={6}
                    required
                    autoFocus
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="000000"
                    className={inputCls + " tracking-[0.4em] text-center text-lg"}
                  />
                </div>
                {error && (
                  <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-400">
                    {error}
                  </p>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  {loading ? "Verifying…" : "Verify"}
                </button>
                <button
                  type="button"
                  onClick={() => { setStep("credentials"); setError(""); setMfaCode(""); }}
                  className="w-full text-center text-xs text-ink-3 hover:text-ink"
                >
                  ← Back to sign in
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
