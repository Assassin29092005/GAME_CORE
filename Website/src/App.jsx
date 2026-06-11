import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./useAuth.jsx";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Download from "./pages/Download.jsx";

function Guard({ children }) {
  const { user, demo, loading } = useAuth();
  if (loading) {
    return (
      <div className="boot">
        <span className="boot-mark" />
        ESTABLISHING UPLINK…
      </div>
    );
  }
  if (!user && !demo) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <Layout />
          </Guard>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/download" element={<Download />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
