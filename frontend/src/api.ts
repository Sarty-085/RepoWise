import type {
  AutopilotResponse,
  FileItem,
  GraphEdgeData,
  GraphNodeData,
  HistoryResponse,
  ImpactResponse,
  QAResponse,
  RepoRecord,
} from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      if (err.detail) detail = err.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listRepos: () => request<RepoRecord[]>('/api/v1/repositories'),
  createRepo: (url: string) =>
    request<RepoRecord>('/api/v1/repositories', {
      method: 'POST',
      body: JSON.stringify({ url, run_async: false }),
    }),
  selfAnalyze: () =>
    request<RepoRecord>('/api/v1/repositories/self-analyze', {
      method: 'POST',
    }),
  getAnalysis: (id: string) => request<RepoRecord>(`/api/v1/analyses/${id}`),
  getFiles: (id: string) =>
    request<{ files: FileItem[]; excluded: { path: string; reason: string }[] }>(
      `/api/v1/analyses/${id}/files`
    ),
  getFileContent: (id: string, path: string) =>
    request<{
      path: string;
      line_count: number;
      lines: string[];
      symbols: { name: string; kind: string; start_line: number; end_line: number; signature: string }[];
    }>(`/api/v1/analyses/${id}/file-content?path=${encodeURIComponent(path)}`),
  getGraph: (id: string) =>
    request<{ nodes: GraphNodeData[]; edges: GraphEdgeData[]; hub_files: string[] }>(
      `/api/v1/analyses/${id}/graph`
    ),
  getHistory: (id: string) => request<HistoryResponse>(`/api/v1/analyses/${id}/history`),
  getImpact: (id: string, path: string) =>
    request<ImpactResponse>(`/api/v1/analyses/${id}/impact?path=${encodeURIComponent(path)}`),
  getAutopilot: (id: string) => request<AutopilotResponse>(`/api/v1/analyses/${id}/autopilot`),
  askQuestion: (id: string, question: string) =>
    request<QAResponse>(`/api/v1/analyses/${id}/questions`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  checkMission: (id: string, mission_id: string, answer: string) =>
    request<{ mission_id: string; passed: boolean; feedback: string; matched_evidence: string[] }>(
      `/api/v1/analyses/${id}/missions/check`,
      {
        method: 'POST',
        body: JSON.stringify({ mission_id, answer }),
      }
    ),
  deleteRepo: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/repositories/${id}`, {
      method: 'DELETE',
    }),
};
