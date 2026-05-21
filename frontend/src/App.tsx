import { Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthProvider } from "@/lib/auth";
import { MyApplications } from "@/pages/MyApplications";
import { NewApplication } from "@/pages/NewApplication";
import { ApplicationDetail } from "@/pages/ApplicationDetail";
import { ManualReview } from "@/pages/ManualReview";
import { Chatbot } from "@/pages/Chatbot";
import { Login } from "@/pages/Login";
import { Signup } from "@/pages/Signup";

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="flex h-screen overflow-hidden bg-muted/40">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route
          path="/"
          element={
            <ProtectedLayout>
              <MyApplications />
            </ProtectedLayout>
          }
        />
        <Route
          path="/new"
          element={
            <ProtectedLayout>
              <NewApplication />
            </ProtectedLayout>
          }
        />
        <Route
          path="/applications/:id"
          element={
            <ProtectedLayout>
              <ApplicationDetail />
            </ProtectedLayout>
          }
        />
        <Route
          path="/manual-review"
          element={
            <ProtectedLayout>
              <ManualReview />
            </ProtectedLayout>
          }
        />
        <Route
          path="/chatbot"
          element={
            <ProtectedLayout>
              <Chatbot />
            </ProtectedLayout>
          }
        />
        <Route
          path="*"
          element={
            <ProtectedLayout>
              <MyApplications />
            </ProtectedLayout>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
