import { useState } from "react";
import { askQuestion, ingestSample, type ChatResponse, type UserRole } from "./api";
import { AdminPanel } from "./components/AdminPanel";
import { AnswerView } from "./components/AnswerView";
import { ChatPanel } from "./components/ChatPanel";
import { SourceList } from "./components/SourceList";
import "./styles.css";

export default function App() {
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestStatus, setIngestStatus] = useState("");
  const [error, setError] = useState("");

  async function handleAsk(question: string, userRole: UserRole) {
    setLoading(true);
    setError("");
    try {
      setResponse(await askQuestion(question, userRole));
    } catch (event) {
      setError(event instanceof Error ? event.message : "chat failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleIngest() {
    setIngesting(true);
    setError("");
    try {
      const result = await ingestSample();
      setIngestStatus(`${result.status} / ${result.indexed_count} docs`);
    } catch (event) {
      setError(event instanceof Error ? event.message : "ingest failed");
    } finally {
      setIngesting(false);
    }
  }

  return (
    <main className="app-shell">
      <div className="workspace">
        <div className="left-rail">
          <ChatPanel loading={loading} onAsk={handleAsk} lastResponse={response} />
          <AdminPanel ingesting={ingesting} ingestStatus={ingestStatus} onIngest={handleIngest} />
          {error && <div className="error-banner">{error}</div>}
        </div>
        <div className="content">
          <AnswerView response={response} />
          <SourceList sources={response?.sources ?? []} />
        </div>
      </div>
    </main>
  );
}
