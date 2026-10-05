import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import { MockBadge } from "../components/ui";

export function AppLayout() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const config = useApi(() => api.config(), []);

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-2.5">
          <Link to="/projects" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-forge-600 text-xs font-bold text-white">
              DF
            </span>
            <span className="text-sm font-semibold tracking-tight text-slate-900">DevForge</span>
          </Link>
          <span className="hidden text-xs text-slate-400 sm:inline">
            AI-assisted software engineering platform
          </span>
          <div className="ml-auto flex items-center gap-2">
            {config.data && <MockBadge mode={config.data.mode} />}
            {config.data && (
              <span
                className="hidden text-[11px] text-slate-500 md:inline"
                title="Sandbox used for generated code"
              >
                sandbox: {config.data.execution_provider}
              </span>
            )}
            <span className="hidden text-xs text-slate-600 sm:inline">{user?.full_name || user?.email}</span>
            <button
              className="btn-secondary"
              onClick={() => {
                signOut();
                navigate("/login", { replace: true });
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 bg-white px-4 py-3 text-center text-[11px] text-slate-400">
        DevForge · six agents · human approval at every stage · sandboxed execution · traceable
        artefacts
      </footer>
    </div>
  );
}
