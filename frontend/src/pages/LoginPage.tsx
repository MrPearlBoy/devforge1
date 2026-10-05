import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { ApiError } from "../services/api";
import { ErrorNote } from "../components/ui";

const DEMO = { email: "demo@devforge.dev", password: "devforge123" };

export function LoginPage() {
  const { signIn, signUp } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await signIn(email, password);
      else await signUp(email, password, fullName);
      navigate("/projects", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function useDemo() {
    setBusy(true);
    setError("");
    try {
      await signIn(DEMO.email, DEMO.password);
      navigate("/projects", { replace: true });
    } catch {
      setError("The demo account does not exist yet. Run `python scripts/seed_demo.py` in backend/.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-forge-900 via-forge-700 to-slate-900 px-4 py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-2xl bg-white shadow-2xl md:grid-cols-2">
        <div className="hidden flex-col justify-between bg-forge-900 p-8 text-forge-50 md:flex">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-forge-200">DevForge</p>
            <h1 className="mt-3 text-2xl font-semibold leading-snug">
              Six AI agents.
              <br />
              One human in control of every stage.
            </h1>
            <ul className="mt-6 space-y-3 text-sm text-forge-100">
              {[
                "Requirement → Architecture → Code → Tests → Security → Documentation",
                "Human approval gates recorded with comments and timestamps",
                "Traceability from REQ-001 to the README",
                "Generated code runs only inside a sandbox",
              ].map((line) => (
                <li key={line} className="flex gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-forge-300" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-forge-200/80">
            Final-year project · mock and live AI modes · SQLite or PostgreSQL
          </p>
        </div>

        <div className="p-8">
          <div className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1">
            {(["login", "register"] as const).map((option) => (
              <button
                key={option}
                onClick={() => setMode(option)}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  mode === option ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                }`}
              >
                {option === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="label" htmlFor="full_name">
                  Full name
                </label>
                <input
                  id="full_name"
                  className="input"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Ada Lovelace"
                />
              </div>
            )}
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                className="input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                className="input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="at least 8 characters"
              />
            </div>
            <ErrorNote message={error} />
            <button className="btn-primary w-full" disabled={busy} type="submit">
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <button className="btn-secondary mt-3 w-full" onClick={() => void useDemo()} disabled={busy}>
            Use the seeded demo account
          </button>
          <p className="mt-4 text-center text-[11px] text-slate-500">
            Passwords are hashed with PBKDF2-SHA256 (240 000 iterations); sessions use signed JWTs.
          </p>
        </div>
      </div>
    </div>
  );
}
