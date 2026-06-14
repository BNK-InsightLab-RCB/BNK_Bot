import { FormEvent, useState } from "react";
import { Send, UserCog } from "lucide-react";
import type { ChatResponse, UserRole } from "../api";

interface ChatPanelProps {
  loading: boolean;
  onAsk: (question: string, userRole: UserRole) => Promise<void>;
  lastResponse: ChatResponse | null;
}

const samples = [
  "고객조회 화면에서 저장이 안돼요.",
  "고객번호 넣었는데 고객이 조회되지 않아요.",
  "저장 권한이 없다고 나오는데 어떻게 해야 하나요?",
  "해지 고객 수정이 안되는 이유가 뭐예요?",
];

export function ChatPanel({ loading, onAsk, lastResponse }: ChatPanelProps) {
  const [question, setQuestion] = useState(samples[0]);
  const [role, setRole] = useState<UserRole>("branch");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || loading) return;
    await onAsk(question.trim(), role);
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-head">
        <div>
          <h1>영업점 운영지원 RAG</h1>
          <p>화면 오류와 업무 처리 문제를 소스 분석 근거로 답변합니다.</p>
        </div>
        <div className="confidence" title="검색 근거 기반 확신도">
          {lastResponse ? Math.round(lastResponse.confidence * 100) : "--"}%
        </div>
      </div>

      <form onSubmit={submit} className="ask-form">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={5}
          placeholder="문의 내용을 입력하세요"
        />
        <div className="form-row">
          <label className="role-select">
            <UserCog size={18} aria-hidden="true" />
            <select value={role} onChange={(event) => setRole(event.target.value as UserRole)}>
              <option value="branch">branch</option>
              <option value="it">it</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <button type="submit" disabled={loading || !question.trim()} title="질문 보내기">
            <Send size={18} aria-hidden="true" />
            <span>{loading ? "분석 중" : "전송"}</span>
          </button>
        </div>
      </form>

      <div className="sample-row">
        {samples.map((sample) => (
          <button key={sample} type="button" onClick={() => setQuestion(sample)}>
            {sample}
          </button>
        ))}
      </div>
    </section>
  );
}
