export type UserRole = "branch" | "it" | "admin";

export interface SourceCitation {
  doc_id: string;
  title: string;
  source_path?: string;
  line_range: string;
  reason: string;
  api_path?: string | null;
  class_name?: string | null;
  method_name?: string | null;
  sql_id?: string | null;
  tables?: string[];
}

export interface ChatResponse {
  answer: string;
  branch_guide: {
    possible_causes?: string[];
    checklist?: string[];
    it_contact_summary?: string;
  };
  it_summary: Record<string, unknown>;
  confidence: number;
  sources: SourceCitation[];
}

export async function askQuestion(question: string, userRole: UserRole): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      user_role: userRole,
      include_sources: true,
    }),
  });
  if (!response.ok) {
    throw new Error(`chat failed: ${response.status}`);
  }
  return response.json();
}

export async function ingestSample(): Promise<{ status: string; indexed_count: number }> {
  const response = await fetch("/api/ingest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_dir: "backend/examples/bank_sample",
      reset_index: true,
      generate_summaries: false,
    }),
  });
  if (!response.ok) {
    throw new Error(`ingest failed: ${response.status}`);
  }
  return response.json();
}
