export type Activity = {
  id: number;
  request_id: string;
  operation_id: string;
  kind: string;
  label: string;
  status: "started" | "completed" | "failed";
  detail: unknown;
  created_at: string;
};
export type Candidate = {
  task_id: string;
  title: string;
  owner: string;
  state: string;
  version: number;
  score: number;
  similarity: number | null;
  components: Record<string, number>;
  ownership_supported: boolean;
  conflicts: string[];
  contacts: { name: string; email: string }[];
  start_date: string | null;
  threads: { id: string }[];
  evidence: unknown[];
};
export type Draft = {
  id: string;
  recipient: string;
  thread_id: string;
  body: string;
  status: string;
};
export type Order = {
  id: string;
  merchant: string;
  items: string;
  status: string;
};
export type Trace = {
  request_id: string;
  conversation_id: string;
  mode: string;
  path: string;
  decision: string;
  routing_status?: string;
  clarification?: { kind: string; options: Record<string, unknown>[] };
  verification?: {
    engine: string;
    checks: Record<string, boolean>;
    actual_margin: number | null;
    required_margin: number;
    rejected_conflicts: number;
    note: string;
  };
  response: string;
  task_id: string | null;
  owner: string;
  candidates: Candidate[];
  timings_ms: Record<string, number>;
  execution: {
    status: string;
    drafts?: Draft[];
    orders?: Order[];
    error?: string;
  };
  broader_search: boolean;
  retrieval_error?: string;
  new_agent_created: boolean;
  usage: {
    model: string;
    tokens: number;
    cost_bound: number;
    usage: string;
    status: string;
  }[];
  current_drafts?: Draft[];
  current_orders?: Order[];
  orders?: Order[];
  activity?: Activity[];
  threshold: number;
  ambiguity_margin: number;
};
export type Sample = { label: string; text: string; [key: string]: unknown };
export type Status = {
  mode: string;
  model: string;
  tasks: number;
  vectors: number;
  pending_index: number;
  samples: Sample[];
};
