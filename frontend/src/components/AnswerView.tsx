import { AlertCircle, CheckCircle2, ClipboardList, Wrench } from "lucide-react";
import type { ChatResponse } from "../api";

interface AnswerViewProps {
  response: ChatResponse | null;
}

const sectionIcons: Record<string, JSX.Element> = {
  "[가능한 원인]": <AlertCircle size={18} aria-hidden="true" />,
  "[먼저 확인할 사항]": <CheckCircle2 size={18} aria-hidden="true" />,
  "[계속 오류가 발생하는 경우]": <ClipboardList size={18} aria-hidden="true" />,
  "[IT부서 전달용 정보]": <Wrench size={18} aria-hidden="true" />,
};

export function AnswerView({ response }: AnswerViewProps) {
  if (!response) {
    return (
      <section className="panel answer-empty">
        <h2>답변</h2>
        <p>샘플 색인 후 질문을 전송하세요.</p>
      </section>
    );
  }

  const sections = splitSections(response.answer);

  return (
    <section className="panel answer-view">
      <h2>답변</h2>
      <div className="sections">
        {sections.map((section) => (
          <article key={section.title} className="answer-section">
            <h3>
              {sectionIcons[section.title] ?? null}
              <span>{section.title.replace("[", "").replace("]", "")}</span>
            </h3>
            <p>{section.body}</p>
          </article>
        ))}
      </div>
      {Object.keys(response.it_summary).length > 0 && (
        <div className="it-summary">
          <h3>IT 요약</h3>
          <dl>
            {Object.entries(response.it_summary).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{Array.isArray(value) ? value.join(", ") : String(value ?? "-")}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}

function splitSections(answer: string) {
  const matches = answer.split(/(?=\[[^\]]+\])/g).filter(Boolean);
  return matches.map((chunk) => {
    const firstLine = chunk.split("\n")[0].trim();
    return {
      title: firstLine,
      body: chunk.replace(firstLine, "").trim(),
    };
  });
}
