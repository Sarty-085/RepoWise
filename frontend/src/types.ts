export interface AnalysisSummary {
  total_files: number;
  total_lines: number;
  total_symbols: number;
  total_routes: number;
  total_edges: number;
  language_counts: Record<string, number>;
  frameworks: string[];
  entrypoints: string[];
  hub_files: string[];
  top_folders: Record<string, number>;
  redacted_secrets_total: number;
  parse_errors: { path: string; error: string }[];
}

export interface RepoRecord {
  id: string;
  name: string;
  source_type: string;
  source_url: string;
  commit_sha: string;
  status: 'queued' | 'scanning' | 'indexing' | 'completed' | 'failed';
  progress: number;
  error?: string | null;
  created_at: string;
  completed_at?: string | null;
  summary: AnalysisSummary;
  routes?: { route: string; handler: string; path: string; start_line: number; end_line: number }[];
}

export interface FileItem {
  path: string;
  language: string;
  size_bytes: number;
  line_count: number;
  content_hash: string;
  is_test: boolean;
  is_entrypoint: boolean;
  symbol_count: number;
  redacted_secrets: number;
}

export interface SymbolItem {
  name: string;
  qualified_name: string;
  kind: string;
  path: string;
  start_line: number;
  end_line: number;
  signature: string;
  docstring: string;
}

export interface GraphNodeData {
  id: string;
  label: string;
  folder: string;
  type: 'file' | 'entrypoint' | 'test';
  language: string;
  size_bytes: number;
  line_count: number;
  symbol_count: number;
  imported_by_count: number;
  imports_count: number;
}

export interface GraphEdgeData {
  source: string;
  target: string;
  kind: string;
  evidence_level: 'observed' | 'inferred';
  evidence: { file: string; start_line: number; end_line: number };
}

export interface Citation {
  path: string;
  start_line: number;
  end_line: number;
  symbol: string;
  label: 'observed' | 'inferred';
  snippet?: string;
}

export interface QAResponse {
  question: string;
  short_answer: string;
  flow_explanation: string[];
  citations: Citation[];
  rejected_citations: string[];
  evidence_level: 'observed' | 'inferred' | 'unknown';
  uncertainties: string[];
  generation_mode: string;
}

export interface HandoverCapsule {
  folder: string;
  primary_owner: string;
  concentration_pct: number;
  risk_score: number;
  evidence_level: 'observed';
  summary: string;
  key_symbols: {
    name: string;
    kind: string;
    signature: string;
    citation: string;
    path: string;
    start_line: number;
    end_line: number;
    docstring: string;
  }[];
  commit_evidence: { sha: string; author: string; date: string; message: string }[];
  open_questions_for_owner: string[];
}

export interface HistoryResponse {
  available: boolean;
  commits: {
    sha: string;
    author: string;
    committed_at: string;
    message: string;
    files: string[];
  }[];
  total_commits_scanned?: number;
  contributors: { author: string; commits: number; share: number }[];
  concentrated_files: {
    path: string;
    primary_owner: string;
    owner_commits: number;
    total_commits: number;
    ownership_share: number;
    dependent_files: number;
    is_concentrated: boolean;
  }[];
  folder_risks: {
    folder: string;
    primary_owner: string;
    concentration: number;
    total_commits: number;
    flagged_files_count: number;
    dependent_files_count: number;
    risk_score: number;
  }[];
  handover_capsules: HandoverCapsule[];
  note: string;
}

export interface ImpactResponse {
  target_path: string;
  impact_score: number;
  priority_label: 'High' | 'Medium' | 'Low';
  formula: string;
  factors: {
    normalized_dependent_count: number;
    critical_module_flag: number;
    normalized_indirect_reach: number;
    test_gap_flag: number;
  };
  direct_dependents: string[];
  indirect_dependents: string[];
  outgoing_imports: string[];
  dependency_paths: {
    dependent: string;
    hops: number;
    chain: string[];
    evidence?: { file: string; start_line: number; end_line: number };
  }[];
  related_tests: { path: string; reason: string; evidence_level: 'observed' | 'inferred' }[];
  affected_routes: { route: string; handler: string; path: string; start_line: number; end_line: number }[];
  limitations: string[];
}

export interface AutopilotCite {
  path: string;
  start_line: number;
  end_line: number;
  symbol: string;
  citation: string;
}

export interface AutopilotResponse {
  days: {
    day: number;
    title: string;
    goal: string;
    contact_expert: string;
    reading_list: AutopilotCite[];
    verification_step: string;
  }[];
  starter_issue: {
    source: string;
    number: number | null;
    title: string;
    url: string;
    labels: string[];
    matched_citations: AutopilotCite[];
  };
  missions: {
    id: string;
    order: number;
    title: string;
    objective: string;
    why_it_matters: string;
    files_to_inspect: AutopilotCite[];
    hint: string;
  }[];
  disclaimer: string;
}
