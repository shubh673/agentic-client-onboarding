import { Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { MyApplications } from "@/pages/MyApplications";
import { NewApplication } from "@/pages/NewApplication";
import { ApplicationDetail } from "@/pages/ApplicationDetail";
import { ManualReview } from "@/pages/ManualReview";

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden bg-muted/40">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<MyApplications />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/applications/:id" element={<ApplicationDetail />} />
          <Route path="/manual-review" element={<ManualReview />} />
          <Route path="*" element={<MyApplications />} />
        </Routes>
      </main>
    </div>
  );
}
