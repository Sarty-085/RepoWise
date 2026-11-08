import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Code2,
  Compass,
  FileCode2,
  GitBranch,
  GitCommit,
  Layers,
  Radar,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  Users,
} from 'lucide-react';
import { api } from './api';
import { ArchitectureMap } from './ArchitectureMap';
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

type WorkspaceTab = 'overview' | 'map' | 'qa' | 'continuity' | 'radar' | 'autopilot' | 'explorer';

const PRESET_REPOS = [
  { label: 'pallets/click', url: 'https://github.com/pallets/click' },
  { label: 'pallets/itsdangerous', url: 'https://github.com/pallets/itsdangerous' },
];

export function App() {
  const [repos, setRepos] = useState<RepoRecord[]>([]);
  const [activeRepo, setActiveRepo] = useState<RepoRecord | null>(null);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview');

  const [urlInput, setUrlInput] = useState('');
  const [loadingIngest, setLoadingIngest] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  const [files, setFiles] = useState<FileItem[]>([]);
  const [excluded, setExcluded] = useState<{ path: string; reason: string }[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNodeData[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdgeData[]>([]);
  const [historyData, setHistoryData] = useState<HistoryResponse | null>(null);
  const [autopilotData, setAutopilotData] = useState<AutopilotResponse | null>(null);

  // Code Explorer state
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  const [fileLines, setFileLines] = useState<string[]>([]);
  const [fileSymbols, setFileSymbols] = useState<
    { name: string; kind: string; start_line: number; end_line: number; signature: string }[]
  >([]);

  // Grounded Q&A state
  const [questionInput, setQuestionInput] = useState('');
  const [asking, setAsking] = useState(false);
  const [qaHistory, setQaHistory] = useState<QAResponse[]>([]);

  // Change Radar state
  const [impactTarget, setImpactTarget] = useState<string>('');
  const [impactReport, setImpactReport] = useState<ImpactResponse | null>(null);
  const [loadingImpact, setLoadingImpact] = useState(false);

  // Mission verification state
  const [missionAnswers, setMissionAnswers] = useState<Record<string, string>>({});
  const [missionResults, setMissionResults] = useState<
    Record<string, { passed: boolean; feedback: string }>
  >({});

  useEffect(() => {
    void refreshRepositories();
  }, []);

  async function refreshRepositories() {
    try {
      const list = (await api.listRepos()).filter((r) => r.status === 'completed');
      setRepos(list);
      if (list.length > 0 && !activeRepo) {
        await loadWorkspace(list[0].id);
      } else if (list.length === 0) {
        await handleSelfAnalyze();
      }
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Failed to load workspaces');
    }
  }

  async function loadWorkspace(id: string) {
    setErrorBanner(null);
    try {
      const [analysis, fileData, graphData, histData, autoData] = await Promise.all([
        api.getAnalysis(id),
        api.getFiles(id),
        api.getGraph(id),
        api.getHistory(id),
        api.getAutopilot(id),
      ]);
      setActiveRepo(analysis);
      setFiles(fileData.files || []);
      setExcluded(fileData.excluded || []);
      setGraphNodes(graphData.nodes || []);
      setGraphEdges(graphData.edges || []);
      setHistoryData(histData && Array.isArray(histData.commits) ? histData : null);
      setAutopilotData(autoData && Array.isArray(autoData.days) ? autoData : null);

      const firstPy =
        analysis.summary?.hub_files?.[0] ||
        analysis.summary?.entrypoints?.[0] ||
        (fileData.files || []).find((f) => f.language === 'python')?.path ||
        (fileData.files || [])[0]?.path ||
        null;

      if (firstPy) {
        void loadFileViewer(id, firstPy, 1);
        void loadImpactForFile(id, firstPy);
      }
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Could not load workspace details');
    }
  }

  async function loadFileViewer(analysisId: string, path: string, line?: number) {
    setSelectedFilePath(path);
    if (line) setHighlightLine(line);
    try {
      const content = await api.getFileContent(analysisId, path);
      setFileLines(content.lines);
      setFileSymbols(content.symbols);
    } catch {
      setFileLines(['// File lines unavailable']);
      setFileSymbols([]);
    }
  }

  async function loadImpactForFile(analysisId: string, path: string) {
    setImpactTarget(path);
    setLoadingImpact(true);
    try {
      const rep = await api.getImpact(analysisId, path);
      setImpactReport(rep);
    } catch {
      setImpactReport(null);
    } finally {
      setLoadingImpact(false);
    }
  }

  async function handleIngestUrl(e: React.FormEvent) {
    e.preventDefault();
    if (!urlInput.trim()) return;
    setLoadingIngest(true);
    setErrorBanner(null);
    try {
      const created = await api.createRepo(urlInput.trim());
      const updated = await api.listRepos();
      setRepos(updated);
      setUrlInput('');
      await loadWorkspace(created.id);
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Repository ingestion failed');
    } finally {
      setLoadingIngest(false);
    }
  }

  async function handleSelfAnalyze() {
    setLoadingIngest(true);
    setErrorBanner(null);
    try {
      const created = await api.selfAnalyze();
      const updated = await api.listRepos();
      setRepos(updated);
      await loadWorkspace(created.id);
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Self-analysis failed');
    } finally {
      setLoadingIngest(false);
    }
  }

  async function handleDeleteRepo(id: string) {
    try {
      await api.deleteRepo(id);
      const updated = await api.listRepos();
      setRepos(updated);
      if (activeRepo?.id === id) {
        if (updated.length > 0) {
          await loadWorkspace(updated[0].id);
        } else {
          setActiveRepo(null);
        }
      }
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Delete failed');
    }
  }

  async function handleAskQuestion(customQuestion?: string) {
    if (!activeRepo) return;
    const q = (customQuestion ?? questionInput).trim();
    if (!q) return;
    setAsking(true);
    setErrorBanner(null);
    try {
      const ans = await api.askQuestion(activeRepo.id, q);
      setQaHistory((prev) => [ans, ...prev]);
      if (!customQuestion) setQuestionInput('');
      setActiveTab('qa');
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Failed to answer question');
    } finally {
      setAsking(false);
    }
  }

  function jumpToCitation(path: string, line?: number) {
    if (!activeRepo) return;
    void loadFileViewer(activeRepo.id, path, line);
    setActiveTab('explorer');
  }

  function jumpToImpact(path: string) {
    if (!activeRepo) return;
    void loadImpactForFile(activeRepo.id, path);
    setActiveTab('radar');
  }

  async function handleVerifyMission(missionId: string) {
    if (!activeRepo) return;
    const text = missionAnswers[missionId] || '';
    try {
      const res = await api.checkMission(activeRepo.id, missionId, text);
      setMissionResults((prev) => ({
        ...prev,
        [missionId]: { passed: res.passed, feedback: res.feedback },
      }));
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Mission check failed');
    }
  }

  const sampleQuestions = [
    'Where is validate_git_url defined and how are URLs validated?',
    'How does compute_change_impact score blast radius and related tests?',
    'How does validate_citations prevent hallucinated file paths and lines?',
    'Where is bus-factor knowledge concentration calculated from git history?',
  ];

  return (
    <div className="min-h-screen flex flex-col bg-[#0B0D10] text-[#ECEFF4]">
      {/* Sticky Translucent Header */}
      <header className="glass-bar sticky top-0 z-30">
        <div className="max-w-[1380px] mx-auto px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[#0D9488]/20 border border-[#2DD4BF]/40 flex items-center justify-center text-[#2DD4BF]">
              <Compass className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold tracking-tight text-white text-base">RepoWise</span>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#141922] border border-[#242C3A] text-[#5EEAD4]">
                  v2.0 Continuity & Onboarding
                </span>
              </div>
              <p className="text-xs text-[#94A3B8] hidden sm:block">
                Static AST analysis • Validated [path:line] citations • Bus-factor continuity
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {activeRepo && (
              <div className="hidden md:flex items-center gap-2 bg-[#12161E] border border-[#222936] rounded-lg px-3 py-1.5 text-xs">
                <GitBranch className="w-3.5 h-3.5 text-[#2DD4BF]" />
                <span className="font-medium text-white">{activeRepo.name}</span>
                <span className="text-[#64748B]">•</span>
                <span className="font-mono text-[#94A3B8]" title="Analyzed Commit SHA">
                  SHA {activeRepo.commit_sha.slice(0, 10)}
                </span>
              </div>
            )}
            <button
              type="button"
              onClick={() => void handleSelfAnalyze()}
              disabled={loadingIngest}
              className="btn-press bg-[#161B24] hover:bg-[#1E2532] border border-[#2A3342] text-xs font-medium text-[#ECEFF4] px-3 py-2 rounded-lg flex items-center gap-1.5"
            >
              <Sparkles className="w-3.5 h-3.5 text-[#2DD4BF]" />
              Analyze RepoWise Self
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-[1380px] w-full mx-auto px-6 py-6 space-y-6">
        {/* Intake Bar + Workspace Selector */}
        <section className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-center">
            <div className="lg:col-span-5 space-y-1.5">
              <h1 className="display-title text-xl sm:text-2xl font-semibold text-white">
                Onboard unfamiliar repositories with source-verified evidence.
              </h1>
              <p className="text-xs sm:text-sm text-[#94A3B8]">
                Every architectural claim cites exact lines, flags single-owner bus-factor modules,
                and calculates change blast radius without executing untrusted code.
              </p>
            </div>

            <div className="lg:col-span-7 space-y-2.5">
              <form onSubmit={(e) => void handleIngestUrl(e)} className="flex flex-col sm:flex-row gap-2">
                <input
                  type="url"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  placeholder="https://github.com/owner/repository"
                  className="flex-1 bg-[#0B0D10] border border-[#262E3B] rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#64748B] focus:outline-none focus:border-[#2DD4BF] font-mono"
                />
                <button
                  type="submit"
                  disabled={loadingIngest}
                  className="btn-press bg-[#0D9488] hover:bg-[#0F766E] disabled:opacity-50 text-white font-medium text-sm px-5 py-2.5 rounded-lg whitespace-nowrap"
                >
                  {loadingIngest ? 'Scanning Snapshot...' : 'Scan Repository'}
                </button>
              </form>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#94A3B8]">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span>Quick public targets:</span>
                  {PRESET_REPOS.map((p) => (
                    <button
                      key={p.url}
                      type="button"
                      onClick={() => setUrlInput(p.url)}
                      className="btn-press font-mono text-[11px] px-2 py-0.5 rounded bg-[#161B24] hover:bg-[#1E2532] text-[#5EEAD4] border border-[#262E3B]"
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                {repos.length > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span>Workspaces:</span>
                    {repos.map((r) => (
                      <div key={r.id} className="inline-flex items-center">
                        <button
                          type="button"
                          onClick={() => void loadWorkspace(r.id)}
                          className={`btn-press text-xs px-2.5 py-1 rounded-l-md border ${
                            activeRepo?.id === r.id
                              ? 'bg-[#0D9488]/20 border-[#2DD4BF] text-[#5EEAD4]'
                              : 'bg-[#141820] border-[#242C3A] text-[#94A3B8]'
                          }`}
                        >
                          {r.name}
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteRepo(r.id)}
                          title="Delete workspace"
                          className="btn-press px-1.5 py-1 rounded-r-md border border-l-0 border-[#242C3A] bg-[#141820] text-[#64748B] hover:text-[#F87171]"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {errorBanner && (
            <div className="mt-4 bg-[#451A1A]/60 border border-[#F87171]/40 text-[#FCA5A5] rounded-lg px-4 py-2.5 text-xs flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 text-[#F87171]" />
                <span>{errorBanner}</span>
              </div>
              <button
                type="button"
                onClick={() => setErrorBanner(null)}
                className="text-xs underline ml-4"
              >
                Dismiss
              </button>
            </div>
          )}
        </section>

        {activeRepo && (
          <>
            {/* Navigation Tabs — Instant on click/keyboard */}
            <nav
              aria-label="Workspace Views"
              className="flex flex-wrap items-center gap-1.5 border-b border-[#1E242D] pb-3"
            >
              {(
                [
                  { id: 'overview', label: '1. Codebase X-Ray', icon: Layers },
                  { id: 'map', label: '2. Architecture Map', icon: GitBranch },
                  { id: 'qa', label: '3. Grounded Q&A', icon: Search },
                  { id: 'continuity', label: '4. Bus-Factor Continuity', icon: Users },
                  { id: 'radar', label: '5. Change Radar', icon: Radar },
                  { id: 'autopilot', label: '6. 3-Day Autopilot & Missions', icon: BookOpen },
                  { id: 'explorer', label: '7. Code & Citation Viewer', icon: FileCode2 },
                ] as const
              ).map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`btn-press flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium border ${
                      isActive
                        ? 'bg-[#0D9488] border-[#14B8A6] text-white'
                        : 'bg-[#0F1217] border-[#1E242D] text-[#94A3B8] hover:text-white hover:border-[#2E3746]'
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>

            {/* TAB 1: OVERVIEW / CODEBASE X-RAY */}
            {activeTab === 'overview' && (
              <section className="panel-enter space-y-5">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                  {[
                    {
                      label: 'Indexed Files',
                      value: activeRepo.summary?.total_files ?? 0,
                      sub: `${excluded.length} paths excluded safely`,
                    },
                    {
                      label: 'Lines of Code',
                      value: (activeRepo.summary?.total_lines ?? 0).toLocaleString(),
                      sub: 'Static read-only scan',
                    },
                    {
                      label: 'Extracted Symbols',
                      value: activeRepo.summary?.total_symbols ?? 0,
                      sub: 'AST classes, defs, methods',
                    },
                    {
                      label: 'Import Edges',
                      value: activeRepo.summary?.total_edges ?? 0,
                      sub: 'Confirmed file-level links',
                    },
                    {
                      label: 'API Routes',
                      value: activeRepo.summary?.total_routes ?? 0,
                      sub: 'Observed decorator endpoints',
                    },
                    {
                      label: 'Secrets Redacted',
                      value: activeRepo.summary?.redacted_secrets_total ?? 0,
                      sub: 'Stripped before indexing',
                    },
                  ].map((stat) => (
                    <div
                      key={stat.label}
                      className="card-lift bg-[#0F1217] border border-[#1E242D] rounded-xl p-4"
                    >
                      <div className="text-xs text-[#94A3B8]">{stat.label}</div>
                      <div className="text-2xl font-semibold text-white font-mono mt-1">
                        {stat.value}
                      </div>
                      <div className="text-[11px] text-[#64748B] mt-1">{stat.sub}</div>
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                  {/* Entry points & Core Hub Modules */}
                  <div className="lg:col-span-5 bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                        <Code2 className="w-4 h-4 text-[#2DD4BF]" />
                        Entry Points & Most Depended-On Hubs
                      </h2>
                      <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#0D9488]/20 text-[#5EEAD4]">
                        Observed
                      </span>
                    </div>

                    <div className="space-y-2">
                      <div className="text-xs text-[#94A3B8] font-medium">Detected Frameworks</div>
                      <div className="flex flex-wrap gap-1.5">
                        {(activeRepo.summary.frameworks || []).length > 0 ? (
                          activeRepo.summary.frameworks.map((fw) => (
                            <span
                              key={fw}
                              className="text-xs font-mono px-2.5 py-1 rounded-md bg-[#161B24] border border-[#262E3B] text-[#ECEFF4]"
                            >
                              {fw}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-[#64748B]">Standard Library Python</span>
                        )}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="text-xs text-[#94A3B8] font-medium">Entry Points</div>
                      <div className="space-y-1.5">
                        {(activeRepo.summary.entrypoints || []).map((ep) => (
                          <div
                            key={ep}
                            className="flex items-center justify-between bg-[#141820] border border-[#1E242D] rounded-lg px-3 py-2 text-xs"
                          >
                            <button
                              type="button"
                              onClick={() => jumpToCitation(ep, 1)}
                              className="font-mono text-[#F59E0B] hover:underline text-left truncate"
                            >
                              {ep}
                            </button>
                            <button
                              type="button"
                              onClick={() => jumpToImpact(ep)}
                              className="text-[11px] text-[#94A3B8] hover:text-white font-mono"
                            >
                              Impact →
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="text-xs text-[#94A3B8] font-medium">
                        Highest In-Degree Hub Modules
                      </div>
                      <div className="space-y-1.5">
                        {(activeRepo.summary.hub_files || []).map((hub) => {
                          const node = graphNodes.find((n) => n.id === hub);
                          return (
                            <div
                              key={hub}
                              className="flex items-center justify-between bg-[#141820] border border-[#1E242D] rounded-lg px-3 py-2 text-xs"
                            >
                              <button
                                type="button"
                                onClick={() => jumpToCitation(hub, 1)}
                                className="font-mono text-[#5EEAD4] hover:underline text-left truncate"
                              >
                                {hub}
                              </button>
                              <span className="font-mono text-[11px] text-[#94A3B8]">
                                {node?.imported_by_count ?? 0} dependents
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  {/* Quick Ask + API Route Inventory */}
                  <div className="lg:col-span-7 bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <h2 className="text-sm font-semibold text-white">
                        Ask a Source-Grounded Question
                      </h2>
                      <span className="text-[11px] font-mono text-[#94A3B8]">
                        Every factual claim validated against [path:start-end]
                      </span>
                    </div>

                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={questionInput}
                        onChange={(e) => setQuestionInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void handleAskQuestion();
                        }}
                        placeholder="e.g., Where is URL validation handled and how does it block SSRF?"
                        className="flex-1 bg-[#0B0D10] border border-[#262E3B] rounded-lg px-3.5 py-2 text-sm text-white placeholder-[#64748B] focus:outline-none focus:border-[#2DD4BF]"
                      />
                      <button
                        type="button"
                        disabled={asking}
                        onClick={() => void handleAskQuestion()}
                        className="btn-press bg-[#0D9488] hover:bg-[#0F766E] text-white text-xs font-medium px-4 py-2 rounded-lg"
                      >
                        {asking ? 'Retrieving...' : 'Ask RepoWise'}
                      </button>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {sampleQuestions.map((sq) => (
                        <button
                          key={sq}
                          type="button"
                          onClick={() => void handleAskQuestion(sq)}
                          className="btn-press text-left text-xs px-2.5 py-1.5 rounded-md bg-[#141820] hover:bg-[#1C222D] border border-[#222936] text-[#94A3B8] hover:text-white"
                        >
                          {sq}
                        </button>
                      ))}
                    </div>

                    <div className="pt-2 border-t border-[#1E242D]">
                      <div className="text-xs font-medium text-[#94A3B8] mb-2">
                        Observed API Routes ({activeRepo.routes?.length ?? 0})
                      </div>
                      {activeRepo.routes && activeRepo.routes.length > 0 ? (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-52 overflow-y-auto pr-1">
                          {activeRepo.routes.map((rt, i) => (
                            <button
                              key={`${rt.route}-${i}`}
                              type="button"
                              onClick={() => jumpToCitation(rt.path, rt.start_line)}
                              className="card-lift flex items-center justify-between bg-[#141820] border border-[#1E242D] rounded-lg px-3 py-2 text-left text-xs"
                            >
                              <span className="font-mono text-[#5EEAD4] truncate">{rt.route}</span>
                              <span className="font-mono text-[10px] text-[#94A3B8] ml-2 shrink-0">
                                L{rt.start_line}
                              </span>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-[#64748B]">
                          No FastAPI/Flask route decorators observed in this repository.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* TAB 2: INTERACTIVE ARCHITECTURE MAP */}
            {activeTab === 'map' && (
              <section className="panel-enter">
                <ArchitectureMap
                  nodesData={graphNodes}
                  edgesData={graphEdges}
                  selectedPath={selectedFilePath}
                  onSelectFile={(path, line) => jumpToCitation(path, line)}
                  onInspectImpact={(path) => jumpToImpact(path)}
                />
              </section>
            )}

            {/* TAB 3: GROUNDED Q&A */}
            {activeTab === 'qa' && (
              <section className="panel-enter space-y-4">
                <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h2 className="text-base font-semibold text-white">
                        Evidence-Grounded Repository Q&A
                      </h2>
                      <p className="text-xs text-[#94A3B8]">
                        Retrieves AST code chunks via BM25 + symbol lookup, validates every{' '}
                        <code className="text-[#5EEAD4]">[path:start-end]</code> citation against the
                        indexed snapshot, and abstains when evidence is missing.
                      </p>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={questionInput}
                      onChange={(e) => setQuestionInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void handleAskQuestion();
                      }}
                      placeholder="Ask about a symbol, route, security check or module flow..."
                      className="flex-1 bg-[#0B0D10] border border-[#262E3B] rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#64748B] focus:outline-none focus:border-[#2DD4BF]"
                    />
                    <button
                      type="button"
                      disabled={asking}
                      onClick={() => void handleAskQuestion()}
                      className="btn-press bg-[#0D9488] hover:bg-[#0F766E] text-white text-sm font-medium px-5 py-2.5 rounded-lg"
                    >
                      {asking ? 'Validating Evidence...' : 'Ask Question'}
                    </button>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {sampleQuestions.map((sq) => (
                      <button
                        key={sq}
                        type="button"
                        onClick={() => void handleAskQuestion(sq)}
                        className="btn-press text-xs px-2.5 py-1 rounded bg-[#141820] border border-[#222936] text-[#94A3B8] hover:text-white"
                      >
                        {sq}
                      </button>
                    ))}
                  </div>
                </div>

                {qaHistory.length === 0 ? (
                  <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-8 text-center text-sm text-[#64748B]">
                    Select a starter question above or ask your own to inspect source-cited answers.
                  </div>
                ) : (
                  <div className="space-y-4">
                    {qaHistory.map((item, idx) => (
                      <div
                        key={`${item.question}-${idx}`}
                        className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-4"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1E242D] pb-3">
                          <div className="font-medium text-white text-sm">Q: {item.question}</div>
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-[11px] font-mono uppercase px-2.5 py-0.5 rounded font-medium ${
                                item.evidence_level === 'observed'
                                  ? 'bg-[#0D9488]/20 text-[#5EEAD4] border border-[#2DD4BF]/30'
                                  : item.evidence_level === 'inferred'
                                    ? 'bg-[#F59E0B]/20 text-[#FCD34D] border border-[#F59E0B]/30'
                                    : 'bg-[#EF4444]/20 text-[#FCA5A5] border border-[#EF4444]/30'
                              }`}
                            >
                              Evidence: {item.evidence_level}
                            </span>
                            <span className="text-[11px] font-mono text-[#64748B]">
                              {item.generation_mode}
                            </span>
                          </div>
                        </div>

                        <p className="text-sm text-[#ECEFF4] leading-relaxed">{item.short_answer}</p>

                        {item.flow_explanation.length > 0 && (
                          <div className="space-y-1.5">
                            <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                              Step-by-Step Evidence Trace
                            </div>
                            <ul className="space-y-1.5">
                              {item.flow_explanation.map((step, sIdx) => (
                                <li
                                  key={sIdx}
                                  className="text-xs text-[#CBD5E1] bg-[#141820] border border-[#1E242D] rounded-lg px-3 py-2 font-mono"
                                >
                                  {step}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {item.citations.length > 0 && (
                          <div className="space-y-2">
                            <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                              Backend-Validated Citations ({item.citations.length})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                              {item.citations.map((cit, cIdx) => (
                                <div
                                  key={`${cit.path}-${cit.start_line}-${cIdx}`}
                                  className="bg-[#12161E] border border-[#222936] rounded-lg p-3 space-y-2"
                                >
                                  <div className="flex items-center justify-between gap-2">
                                    <button
                                      type="button"
                                      onClick={() => jumpToCitation(cit.path, cit.start_line)}
                                      className="font-mono text-xs font-semibold text-[#5EEAD4] hover:underline text-left"
                                    >
                                      [{cit.path}:{cit.start_line}-{cit.end_line}]
                                    </button>
                                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#1A202C] text-[#94A3B8]">
                                      {cit.symbol} ({cit.label})
                                    </span>
                                  </div>
                                  {cit.snippet && (
                                    <pre className="text-[11px] font-mono text-[#94A3B8] bg-[#0B0D10] p-2 rounded overflow-x-auto max-h-28">
                                      {cit.snippet}
                                    </pre>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {item.uncertainties.length > 0 && (
                          <div className="bg-[#141820] border border-[#262E3B] rounded-lg px-3.5 py-2.5 text-xs text-[#94A3B8]">
                            <span className="font-semibold text-[#FCD34D]">
                              Boundaries & Uncertainties:{' '}
                            </span>
                            {item.uncertainties.join(' ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            {/* TAB 4: KNOWLEDGE CONTINUITY & BUS-FACTOR HANDOVER CAPSULES */}
            {activeTab === 'continuity' && historyData && (
              <section className="panel-enter space-y-5">
                <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <h2 className="text-base font-semibold text-white flex items-center gap-2">
                      <ShieldAlert className="w-4 h-4 text-[#F59E0B]" />
                      Knowledge Continuity & Bus-Factor Handover Capsules
                    </h2>
                    <p className="text-xs text-[#94A3B8] mt-1">{historyData.note}</p>
                  </div>
                  <div className="text-xs font-mono bg-[#141820] border border-[#242C3A] px-3 py-1.5 rounded-lg text-[#5EEAD4]">
                    {historyData.total_commits_scanned ?? 0} commits scanned •{' '}
                    {historyData.contributors.length} contributors
                  </div>
                </div>

                {/* Handover Capsules */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {historyData.handover_capsules.map((cap) => (
                    <div
                      key={cap.folder}
                      className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 flex flex-col justify-between space-y-4"
                    >
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-xs font-semibold px-2.5 py-1 rounded bg-[#F59E0B]/15 text-[#FCD34D] border border-[#F59E0B]/30">
                            Risk Score: {cap.risk_score}
                          </span>
                          <span className="text-xs font-mono text-[#94A3B8]">
                            {cap.concentration_pct}% single-owner
                          </span>
                        </div>

                        <div>
                          <h3 className="font-mono text-sm font-semibold text-white">
                            Module: {cap.folder}
                          </h3>
                          <p className="text-xs text-[#5EEAD4] mt-0.5">
                            Primary Owner: {cap.primary_owner}
                          </p>
                        </div>

                        <p className="text-xs text-[#CBD5E1] leading-relaxed">{cap.summary}</p>

                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8] mb-1.5">
                            Critical Symbols to Hand Over
                          </div>
                          <ul className="space-y-1">
                            {cap.key_symbols.map((sym) => (
                              <li
                                key={sym.citation}
                                className="flex items-center justify-between text-xs bg-[#141820] px-2.5 py-1.5 rounded"
                              >
                                <button
                                  type="button"
                                  onClick={() => jumpToCitation(sym.path, sym.start_line)}
                                  className="font-mono text-[#5EEAD4] hover:underline truncate text-left"
                                >
                                  {sym.name}
                                </button>
                                <span className="font-mono text-[10px] text-[#64748B] ml-2">
                                  L{sym.start_line}-{sym.end_line}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        {cap.commit_evidence.length > 0 && (
                          <div>
                            <div className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8] mb-1.5">
                              Observed Commit Clues
                            </div>
                            <ul className="space-y-1">
                              {cap.commit_evidence.slice(0, 3).map((cm) => (
                                <li
                                  key={cm.sha}
                                  className="text-[11px] text-[#94A3B8] bg-[#141820] px-2.5 py-1.5 rounded font-mono truncate"
                                  title={cm.message}
                                >
                                  <span className="text-[#38BDF8]">{cm.sha}</span> ({cm.date}):{' '}
                                  {cm.message}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>

                      <div className="pt-3 border-t border-[#1E242D]">
                        <div className="text-[11px] font-semibold uppercase tracking-wider text-[#FCD34D] mb-1">
                          Open Handover Questions (Unknowns)
                        </div>
                        <ul className="space-y-1 text-[11px] text-[#94A3B8] list-disc list-inside">
                          {cap.open_questions_for_owner.map((oq, i) => (
                            <li key={i}>{oq}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Recent Git Commits Table */}
                <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-3">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <GitCommit className="w-4 h-4 text-[#2DD4BF]" />
                    Recent Git History Evidence
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-[#1E242D] text-[#94A3B8]">
                          <th className="py-2 pr-3 font-medium">SHA</th>
                          <th className="py-2 pr-3 font-medium">Author</th>
                          <th className="py-2 pr-3 font-medium">Date</th>
                          <th className="py-2 pr-3 font-medium">Commit Message (Observed)</th>
                          <th className="py-2 font-medium">Files Touched</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#181D26]">
                        {historyData.commits.slice(0, 12).map((c) => (
                          <tr key={c.sha} className="hover:bg-[#141820]">
                            <td className="py-2 pr-3 font-mono text-[#5EEAD4]">{c.sha}</td>
                            <td className="py-2 pr-3 text-[#ECEFF4]">{c.author}</td>
                            <td className="py-2 pr-3 font-mono text-[#94A3B8]">
                              {c.committed_at.slice(0, 10)}
                            </td>
                            <td className="py-2 pr-3 text-[#CBD5E1]">{c.message}</td>
                            <td className="py-2 font-mono text-[#94A3B8]">{c.files.length} files</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            )}

            {/* TAB 5: CHANGE RADAR */}
            {activeTab === 'radar' && (
              <section className="panel-enter space-y-4">
                <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold text-white flex items-center gap-2">
                        <Radar className="w-4 h-4 text-[#2DD4BF]" />
                        Change Radar — Static Blast Radius & Test Prioritization
                      </h2>
                      <p className="text-xs text-[#94A3B8] mt-0.5">
                        Select any indexed module before editing to inspect direct/indirect
                        dependents, related unit tests, and every factor of the heuristic priority
                        score.
                      </p>
                    </div>

                    <select
                      aria-label="Select file for Change Radar"
                      value={impactTarget}
                      onChange={(e) => void loadImpactForFile(activeRepo.id, e.target.value)}
                      className="bg-[#0B0D10] border border-[#262E3B] rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-[#2DD4BF]"
                    >
                      {files
                        .filter((f) => f.language === 'python')
                        .map((f) => (
                          <option key={f.path} value={f.path}>
                            {f.path}
                          </option>
                        ))}
                    </select>
                  </div>

                  {loadingImpact && (
                    <div className="text-xs text-[#94A3B8] font-mono">
                      Computing dependency reach...
                    </div>
                  )}

                  {impactReport && (
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 pt-2">
                      {/* Heuristic Score & Factors */}
                      <div className="lg:col-span-5 bg-[#12161E] border border-[#222936] rounded-xl p-4 space-y-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="text-xs text-[#94A3B8]">Prioritization Heuristic</div>
                            <div className="text-2xl font-mono font-bold text-white mt-0.5">
                              {impactReport.impact_score}{' '}
                              <span
                                className={`text-xs font-sans px-2 py-0.5 rounded ml-1 ${
                                  impactReport.priority_label === 'High'
                                    ? 'bg-[#EF4444]/20 text-[#FCA5A5]'
                                    : impactReport.priority_label === 'Medium'
                                      ? 'bg-[#F59E0B]/20 text-[#FCD34D]'
                                      : 'bg-[#0D9488]/20 text-[#5EEAD4]'
                                }`}
                              >
                                {impactReport.priority_label} Priority
                              </span>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => jumpToCitation(impactReport.target_path, 1)}
                            className="btn-press text-xs font-mono bg-[#181E29] border border-[#2A3344] px-3 py-1.5 rounded-lg text-[#5EEAD4]"
                          >
                            View File
                          </button>
                        </div>

                        <div className="text-[11px] font-mono text-[#94A3B8] bg-[#0B0D10] p-2.5 rounded border border-[#1E242D]">
                          Formula: {impactReport.formula}
                        </div>

                        <div className="space-y-2 text-xs">
                          {Object.entries(impactReport.factors).map(([k, v]) => (
                            <div key={k} className="flex items-center justify-between">
                              <span className="font-mono text-[#94A3B8]">{k}</span>
                              <span className="font-mono text-white font-semibold">{v}</span>
                            </div>
                          ))}
                        </div>

                        <div className="pt-3 border-t border-[#1E242D] space-y-1 text-[11px] text-[#94A3B8]">
                          <div className="font-semibold text-[#FCD34D]">Explicit Limitations:</div>
                          {impactReport.limitations.map((lim, i) => (
                            <p key={i}>• {lim}</p>
                          ))}
                        </div>
                      </div>

                      {/* Dependents and Related Tests */}
                      <div className="lg:col-span-7 space-y-4">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="bg-[#12161E] border border-[#222936] rounded-xl p-4 space-y-2">
                            <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                              Direct Dependents ({impactReport.direct_dependents.length})
                            </div>
                            {impactReport.direct_dependents.length === 0 ? (
                              <p className="text-xs text-[#64748B]">
                                No modules directly import this file.
                              </p>
                            ) : (
                              <ul className="space-y-1">
                                {impactReport.direct_dependents.map((d) => (
                                  <li key={d}>
                                    <button
                                      type="button"
                                      onClick={() => jumpToCitation(d, 1)}
                                      className="font-mono text-xs text-[#5EEAD4] hover:underline"
                                    >
                                      {d}
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>

                          <div className="bg-[#12161E] border border-[#222936] rounded-xl p-4 space-y-2">
                            <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                              Indirect Dependents ({impactReport.indirect_dependents.length})
                            </div>
                            {impactReport.indirect_dependents.length === 0 ? (
                              <p className="text-xs text-[#64748B]">
                                No multi-hop transitive dependents.
                              </p>
                            ) : (
                              <ul className="space-y-1">
                                {impactReport.indirect_dependents.map((d) => (
                                  <li key={d}>
                                    <button
                                      type="button"
                                      onClick={() => jumpToCitation(d, 1)}
                                      className="font-mono text-xs text-[#38BDF8] hover:underline"
                                    >
                                      {d}
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </div>

                        <div className="bg-[#12161E] border border-[#222936] rounded-xl p-4 space-y-2">
                          <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                            Recommended Tests to Run ({impactReport.related_tests.length})
                          </div>
                          {impactReport.related_tests.length === 0 ? (
                            <p className="text-xs text-[#F87171]">
                              Test gap flagged: no test files import or match this module name.
                            </p>
                          ) : (
                            <ul className="space-y-1.5">
                              {impactReport.related_tests.map((t) => (
                                <li
                                  key={t.path}
                                  className="flex items-center justify-between text-xs bg-[#0F1217] px-3 py-2 rounded border border-[#1E242D]"
                                >
                                  <button
                                    type="button"
                                    onClick={() => jumpToCitation(t.path, 1)}
                                    className="font-mono text-[#5EEAD4] hover:underline"
                                  >
                                    {t.path}
                                  </button>
                                  <span className="text-[11px] text-[#94A3B8]">{t.reason}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* TAB 6: 3-DAY ONBOARDING AUTOPILOT & MISSIONS */}
            {activeTab === 'autopilot' && autopilotData && (
              <section className="panel-enter space-y-5">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {autopilotData.days.map((day) => (
                    <div
                      key={day.day}
                      className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 flex flex-col justify-between space-y-4"
                    >
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono px-2.5 py-0.5 rounded bg-[#0D9488]/20 text-[#5EEAD4]">
                            Day {day.day} Plan
                          </span>
                          <span className="text-xs text-[#94A3B8]">
                            Expert: <strong className="text-white">{day.contact_expert}</strong>
                          </span>
                        </div>
                        <h3 className="text-sm font-semibold text-white">{day.title}</h3>
                        <p className="text-xs text-[#94A3B8] leading-relaxed">{day.goal}</p>

                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8] mb-1.5">
                            Cited Reading List
                          </div>
                          <ul className="space-y-1.5">
                            {day.reading_list.map((item) => (
                              <li
                                key={item.citation}
                                className="flex items-center justify-between text-xs bg-[#141820] border border-[#1E242D] px-2.5 py-1.5 rounded"
                              >
                                <button
                                  type="button"
                                  onClick={() => jumpToCitation(item.path, item.start_line)}
                                  className="font-mono text-[#5EEAD4] hover:underline truncate text-left"
                                >
                                  {item.citation}
                                </button>
                                <span className="font-mono text-[10px] text-[#94A3B8] ml-2">
                                  {item.symbol}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>

                      <div className="pt-3 border-t border-[#1E242D] text-xs text-[#CBD5E1]">
                        <span className="text-[#2DD4BF] font-medium">Checkpoint: </span>
                        {day.verification_step}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Interactive Onboarding Missions */}
                <div className="bg-[#0F1217] border border-[#1E242D] rounded-xl p-5 space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Interactive Onboarding Missions
                    </h3>
                    <p className="text-xs text-[#94A3B8] mt-0.5">{autopilotData.disclaimer}</p>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    {autopilotData.missions.map((m) => {
                      const result = missionResults[m.id];
                      return (
                        <div
                          key={m.id}
                          className="bg-[#12161E] border border-[#222936] rounded-xl p-4 flex flex-col justify-between space-y-3"
                        >
                          <div className="space-y-2">
                            <div className="text-xs font-mono text-[#5EEAD4]">
                              Mission {m.order}
                            </div>
                            <h4 className="text-sm font-semibold text-white">{m.title}</h4>
                            <p className="text-xs text-[#CBD5E1]">{m.objective}</p>
                            <p className="text-[11px] text-[#64748B]">Hint: {m.hint}</p>
                            <div className="flex flex-wrap gap-1.5 pt-1">
                              {m.files_to_inspect.map((f) => (
                                <button
                                  key={f.citation}
                                  type="button"
                                  onClick={() => jumpToCitation(f.path, f.start_line)}
                                  className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#181E29] text-[#5EEAD4] hover:underline"
                                >
                                  Inspect {f.citation}
                                </button>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-2 pt-2">
                            <textarea
                              rows={2}
                              value={missionAnswers[m.id] || ''}
                              onChange={(e) =>
                                setMissionAnswers((prev) => ({ ...prev, [m.id]: e.target.value }))
                              }
                              placeholder="Write 1–2 sentences explaining what you found..."
                              className="w-full bg-[#0B0D10] border border-[#262E3B] rounded-lg p-2 text-xs text-white placeholder-[#64748B] focus:outline-none focus:border-[#2DD4BF]"
                            />
                            <button
                              type="button"
                              onClick={() => void handleVerifyMission(m.id)}
                              className="btn-press w-full bg-[#0D9488] hover:bg-[#0F766E] text-white text-xs font-medium py-1.5 rounded-lg"
                            >
                              Check Explanation
                            </button>
                            {result && (
                              <div
                                className={`text-xs p-2.5 rounded-lg border flex items-start gap-2 ${
                                  result.passed
                                    ? 'bg-[#0D9488]/15 border-[#2DD4BF]/40 text-[#5EEAD4]'
                                    : 'bg-[#F59E0B]/15 border-[#F59E0B]/40 text-[#FCD34D]'
                                }`}
                              >
                                <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                                <span>{result.feedback}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            )}

            {/* TAB 7: CODE & CITATION EXPLORER */}
            {activeTab === 'explorer' && (
              <section className="panel-enter grid grid-cols-1 lg:grid-cols-12 gap-4">
                <div className="lg:col-span-4 bg-[#0F1217] border border-[#1E242D] rounded-xl p-4 h-[560px] overflow-y-auto space-y-3">
                  <div className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                    Indexed Files ({files.length})
                  </div>
                  <ul className="space-y-1">
                    {files.map((f) => (
                      <li key={f.path}>
                        <button
                          type="button"
                          onClick={() => void loadFileViewer(activeRepo.id, f.path, 1)}
                          className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs font-mono flex items-center justify-between ${
                            selectedFilePath === f.path
                              ? 'bg-[#0D9488]/20 text-[#5EEAD4] border border-[#2DD4BF]/30'
                              : 'text-[#CBD5E1] hover:bg-[#161B24]'
                          }`}
                        >
                          <span className="truncate">{f.path}</span>
                          <span className="text-[10px] text-[#64748B] ml-2 shrink-0">
                            {f.line_count}L
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="lg:col-span-8 bg-[#0F1217] border border-[#1E242D] rounded-xl overflow-hidden flex flex-col h-[560px]">
                  <div className="px-4 py-3 bg-[#12161E] border-b border-[#1E242D] flex flex-wrap items-center justify-between gap-2">
                    <div className="font-mono text-xs text-white font-semibold">
                      {selectedFilePath || 'Select a file'}
                      {highlightLine ? (
                        <span className="ml-2 text-[#5EEAD4]">(Cited Line {highlightLine})</span>
                      ) : null}
                    </div>
                    {selectedFilePath && (
                      <button
                        type="button"
                        onClick={() => jumpToImpact(selectedFilePath)}
                        className="btn-press text-xs font-mono px-2.5 py-1 rounded bg-[#0D9488] text-white"
                      >
                        Analyze Impact in Radar
                      </button>
                    )}
                  </div>

                  {fileSymbols.length > 0 && (
                    <div className="px-4 py-2 bg-[#0D1016] border-b border-[#1E242D] flex flex-wrap items-center gap-1.5">
                      <span className="text-[11px] text-[#64748B]">Jump to symbol:</span>
                      {fileSymbols.map((s) => (
                        <button
                          key={`${s.name}-${s.start_line}`}
                          type="button"
                          onClick={() => setHighlightLine(s.start_line)}
                          className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#161B24] hover:bg-[#1E2532] text-[#5EEAD4]"
                        >
                          {s.name} (L{s.start_line})
                        </button>
                      ))}
                    </div>
                  )}

                  <div className="flex-1 overflow-auto p-4 font-mono text-xs bg-[#0B0D10]">
                    {fileLines.map((ln, idx) => {
                      const lineNum = idx + 1;
                      const isCited =
                        highlightLine !== null &&
                        lineNum >= highlightLine &&
                        lineNum <= highlightLine + 12;
                      return (
                        <div
                          key={lineNum}
                          className={`flex leading-5 px-2 rounded ${
                            isCited ? 'bg-[#0D9488]/20 border-l-2 border-[#2DD4BF]' : ''
                          }`}
                        >
                          <span className="w-10 select-none text-right pr-3 text-[#475569]">
                            {lineNum}
                          </span>
                          <span className="whitespace-pre text-[#E2E8F0]">{ln || ' '}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
export default App;
