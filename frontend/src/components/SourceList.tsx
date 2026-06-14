import { FileText } from "lucide-react";
import type { SourceCitation } from "../api";

interface SourceListProps {
  sources: SourceCitation[];
}

export function SourceList({ sources }: SourceListProps) {
  return (
    <section className="panel source-list">
      <h2>근거</h2>
      {sources.length === 0 ? (
        <p>표시할 근거가 없습니다.</p>
      ) : (
        <ul>
          {sources.map((source) => (
            <li key={source.doc_id}>
              <FileText size={18} aria-hidden="true" />
              <div>
                <strong>{source.title}</strong>
                {source.source_path && (
                  <span>
                    {source.source_path}:{source.line_range}
                  </span>
                )}
                <p>{source.reason}</p>
                {source.tables && source.tables.length > 0 && (
                  <small>{source.tables.join(", ")}</small>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
