import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { ProjectLayout } from "./layouts/ProjectLayout";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { WorkflowPage } from "./pages/WorkflowPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { ChatPage } from "./pages/ChatPage";
import { CodePage } from "./pages/CodePage";
import { TestsPage } from "./pages/TestsPage";
import { SecurityPage } from "./pages/SecurityPage";
import { TraceabilityPage } from "./pages/TraceabilityPage";
import { DeliveryPage } from "./pages/DeliveryPage";
import { ActivityPage } from "./pages/ActivityPage";
import { useAuth } from "./store/auth";
import { Loading } from "./components/ui";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { user, loading } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={loading ? <Loading /> : user ? <Navigate to="/projects" replace /> : <LoginPage />}
      />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectLayout />}>
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview" element={<ProjectOverviewPage />} />
          <Route path="workflow" element={<WorkflowPage />} />
          <Route path="approvals" element={<ApprovalsPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="code" element={<CodePage />} />
          <Route path="tests" element={<TestsPage />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="trace" element={<TraceabilityPage />} />
          <Route path="delivery" element={<DeliveryPage />} />
          <Route path="activity" element={<ActivityPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
