import { Navigate, Route, Routes } from "react-router-dom";

import { Header } from "@/components/Header";
import { ChatPage } from "@/pages/ChatPage";
import { ComparePage } from "@/pages/ComparePage";
import { GraphPage } from "@/pages/GraphPage";
import { PapersPage } from "@/pages/PapersPage";

// 04_FRONTEND_SPECIFICATION.md §4.1: header fills its own height, main
// content area fills the rest with no outer scroll — each page manages
// its own internal scrolling once it has real content (FE-002/003/GRAPH).
export default function App() {
  return (
    <div className="flex h-screen flex-col">
      <Header />
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/papers" element={<PapersPage />} />
          <Route path="/compare" element={<ComparePage />} />
        </Routes>
      </main>
    </div>
  );
}
