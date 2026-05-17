import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./routes/Dashboard";
import Ask from "./routes/Ask";
import Documents from "./routes/Documents";
import DocumentDetail from "./routes/DocumentDetail";
import Entities from "./routes/Entities";
import Relations from "./routes/Relations";
import Ingest from "./routes/Ingest";
import Settings from "./routes/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="ask" element={<Ask />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/:id" element={<DocumentDetail />} />
        <Route path="entities" element={<Entities />} />
        <Route path="relations" element={<Relations />} />
        <Route path="ingest" element={<Ingest />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
