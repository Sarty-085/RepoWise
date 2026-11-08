# RepoWise v2.0 — Codebase Onboarding & Knowledge Continuity

Evidence-backed AI codebase onboarding workspace, bus-factor handover capsule generator, and static change-impact radar.

## Core Capabilities

1. **Codebase X-Ray & Safe Ingestion (`backend/app/services/ingest.py`, `scanner.py`)**
   - Validates HTTPS Git URLs against an allowlist (`github.com`, `gitlab.com`, `bitbucket.org`), blocks credentials, localhost, and private IP ranges (SSRF protection), and performs shallow clones (`--no-checkout`, `core.symlinks=false`, `core.hooksPath=/dev/null`).
   - Also supports ZIP extraction with path-traversal, symlink, and zip-bomb checks.
   - Walks files as data only (never imports or executes repository code), skips excluded folders (`.git`, `node_modules`, `.venv`, `dist`, etc.) and sensitive files (`.env`, private keys), and redacts detected secret tokens before indexing.
   - Parses Python ASTs to extract imports, functions, classes, methods, route decorators, signatures, docstrings, and line-numbered source chunks.

2. **Interactive Dependency Graph (`backend/app/services/graph.py`, `frontend/src/ArchitectureMap.tsx`)**
   - Resolves relative and module imports into a directed NetworkX graph where every edge carries its exact import line citation (`[file:line-line]`).
   - Interactive React Flow + Dagre visualization with module filters, node inspection, and one-click jump to source or Change Radar.

3. **Evidence-Grounded Q&A & Strict Citation Validator (`backend/app/services/retrieval.py`, `llm.py`)**
   - Retrieves relevant AST chunks via BM25 (`rank-bm25`) + exact symbol/path matching + 1-hop graph neighborhood expansion.
   - Uses Gemini (`google-genai`) when `LLM_API_KEY` is configured in `backend/.env`, with automatic fallback to deterministic evidence synthesis so the app always works out of the box.
   - Validates every `[path:start-end]` citation against indexed file paths and line counts—rejecting hallucinated paths or out-of-range lines—and labels answers as `observed`, `inferred`, or `unknown` (abstaining when repository evidence is absent).

4. **Knowledge Continuity & Bus-Factor Handover Capsules (`backend/app/services/history.py`)**
   - Parses `git log` history to compute per-file and per-folder commit ownership concentration.
   - Flags concentrated modules (single author $\ge 70\%$ of commits) weighted by incoming dependency count, and generates cited **Handover Capsules** containing key symbols, recent commit evidence, and explicit open questions for the owner.

5. **Change Radar (`backend/app/services/impact.py`)**
   - Traverses incoming dependency edges to list direct and indirect dependents, shortest dependency chains, affected API routes, and related tests (distinguishing `observed` import links from `inferred` naming matches).
   - Computes an explainable prioritization heuristic (`0.35 * direct_dependents + 0.30 * critical_or_route_flag + 0.20 * indirect_reach + 0.15 * test_gap`) with every factor shown transparently.

6. **3-Day Onboarding Autopilot & Interactive Missions (`backend/app/services/autopilot.py`)**
   - Generates a 3-day cited reading plan with named area experts from Git history, matches open GitHub `good first issue` items to code chunks, and provides 3 interactive onboarding missions with evidence verification.

---

## Quick Start

### 1. Run Backend (Port 8000)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Run backend tests:
```powershell
cd backend
$env:PYTHONPATH="."
.\.venv\Scripts\pytest -v
```

### 2. Run Frontend (Port 5173)

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`. On first launch, RepoWise automatically runs a live self-analysis on its own repository so you can explore the architecture graph, handover capsules, Change Radar, and grounded Q&A immediately, or paste any public Python GitHub URL (e.g. `https://github.com/pallets/itsdangerous` or `https://github.com/pallets/click`).
