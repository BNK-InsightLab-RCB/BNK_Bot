import { DatabaseZap, RotateCw } from "lucide-react";

interface AdminPanelProps {
  ingesting: boolean;
  ingestStatus: string;
  onIngest: () => Promise<void>;
}

export function AdminPanel({ ingesting, ingestStatus, onIngest }: AdminPanelProps) {
  return (
    <section className="panel admin-panel">
      <div>
        <h2>색인</h2>
        <p>{ingestStatus || "대기 중"}</p>
      </div>
      <button type="button" onClick={onIngest} disabled={ingesting} title="샘플 색인 실행">
        {ingesting ? <RotateCw size={18} aria-hidden="true" /> : <DatabaseZap size={18} aria-hidden="true" />}
        <span>{ingesting ? "실행 중" : "샘플 색인"}</span>
      </button>
    </section>
  );
}
