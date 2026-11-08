import { useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  type Node,
  type Edge,
} from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import type { GraphEdgeData, GraphNodeData } from './types';

interface ArchitectureMapProps {
  nodesData: GraphNodeData[];
  edgesData: GraphEdgeData[];
  selectedPath: string | null;
  onSelectFile: (path: string, line?: number) => void;
  onInspectImpact: (path: string) => void;
}

const NODE_WIDTH = 220;
const NODE_HEIGHT = 64;

export function ArchitectureMap({
  nodesData,
  edgesData,
  selectedPath,
  onSelectFile,
  onInspectImpact,
}: ArchitectureMapProps) {
  const [filterKind, setFilterKind] = useState<'all' | 'python' | 'non-test'>('non-test');
  const [searchText, setSearchText] = useState('');

  const filteredNodes = useMemo(() => {
    return nodesData.filter((n) => {
      if (filterKind === 'python' && n.language !== 'python') return false;
      if (filterKind === 'non-test' && (n.type === 'test' || n.language !== 'python')) return false;
      if (searchText.trim() && !n.id.toLowerCase().includes(searchText.trim().toLowerCase())) {
        return false;
      }
      return true;
    });
  }, [nodesData, filterKind, searchText]);

  const { flowNodes, flowEdges } = useMemo(() => {
    const allowedIds = new Set(filteredNodes.map((n) => n.id));
    const validEdges = edgesData.filter(
      (e) => allowedIds.has(e.source) && allowedIds.has(e.target)
    );

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'LR', ranksep: 85, nodesep: 32 });

    filteredNodes.forEach((n) => {
      g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    });
    validEdges.forEach((e) => {
      g.setEdge(e.source, e.target);
    });
    dagre.layout(g);

    const fNodes: Node[] = filteredNodes.map((n) => {
      const pos = g.node(n.id) || { x: 0, y: 0 };
      const isSelected = n.id === selectedPath;
      const isHub = n.imported_by_count >= 2;
      const borderColor = isSelected
        ? '#2DD4BF'
        : n.type === 'entrypoint'
          ? '#F59E0B'
          : isHub
            ? '#38BDF8'
            : '#262C36';

      return {
        id: n.id,
        position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div className="text-left px-2 py-1">
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono text-xs font-semibold text-[#ECEFF4] truncate">
                  {n.label}
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#181C23] text-[#94A3B8] font-mono">
                  in:{n.imported_by_count}
                </span>
              </div>
              <div className="text-[10px] text-[#64748B] font-mono truncate mt-0.5">
                {n.id}
              </div>
            </div>
          ),
        },
        style: {
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          background: isSelected ? '#112224' : '#11141A',
          border: `1.5px solid ${borderColor}`,
          borderRadius: 8,
          color: '#ECEFF4',
          padding: 2,
          boxShadow: isSelected ? '0 0 0 2px rgba(45,212,191,0.22)' : 'none',
        },
      };
    });

    const fEdges: Edge[] = validEdges.map((e, idx) => {
      const isHighlighted = e.source === selectedPath || e.target === selectedPath;
      return {
        id: `e-${idx}-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        animated: isHighlighted,
        label: isHighlighted ? `L${e.evidence.start_line}` : undefined,
        labelStyle: { fill: '#94A3B8', fontSize: 10, fontFamily: 'monospace' },
        style: {
          stroke: isHighlighted ? '#2DD4BF' : '#334155',
          strokeWidth: isHighlighted ? 2 : 1.25,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isHighlighted ? '#2DD4BF' : '#475569',
        },
      };
    });

    return { flowNodes: fNodes, flowEdges: fEdges };
  }, [filteredNodes, edgesData, selectedPath]);

  const activeNode = nodesData.find((n) => n.id === selectedPath) || filteredNodes[0] || null;
  const incomingEdges = edgesData.filter((e) => e.target === activeNode?.id);
  const outgoingEdges = edgesData.filter((e) => e.source === activeNode?.id);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-8 bg-[#0F1217] border border-[#1E242D] rounded-xl overflow-hidden flex flex-col h-[540px]">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-[#1E242D] bg-[#12161D]">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[#94A3B8]">Filter modules:</span>
            {(['non-test', 'python', 'all'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setFilterKind(mode)}
                className={`btn-press text-xs px-2.5 py-1 rounded-md font-medium ${
                  filterKind === mode
                    ? 'bg-[#0D9488] text-white'
                    : 'bg-[#181D26] text-[#94A3B8] hover:text-white'
                }`}
              >
                {mode === 'non-test' ? 'Core Python' : mode === 'python' ? 'All Python (+Tests)' : 'All Files'}
              </button>
            ))}
          </div>
          <input
            type="search"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Filter node path..."
            className="bg-[#0B0D10] border border-[#262E3B] rounded-md px-2.5 py-1 text-xs text-[#ECEFF4] placeholder-[#64748B] focus:outline-none focus:border-[#2DD4BF]"
          />
        </div>

        <div className="flex-1 relative">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            onNodeClick={(_, node) => onSelectFile(node.id)}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#1E293B" gap={20} size={1} />
            <Controls className="!bg-[#161B22] !border-[#262E3B] !text-[#ECEFF4]" />
          </ReactFlow>
        </div>
      </div>

      <div className="lg:col-span-4 bg-[#0F1217] border border-[#1E242D] rounded-xl p-4 flex flex-col justify-between h-[540px] overflow-y-auto">
        {activeNode ? (
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] uppercase tracking-wider px-2 py-0.5 rounded bg-[#0D9488]/20 text-[#5EEAD4] font-mono">
                  Observed Node
                </span>
                <span className="text-[11px] uppercase tracking-wider px-2 py-0.5 rounded bg-[#1E242D] text-[#94A3B8] font-mono">
                  {activeNode.type}
                </span>
              </div>
              <h3 className="font-mono text-sm font-semibold text-white mt-2 break-all">
                {activeNode.id}
              </h3>
              <p className="text-xs text-[#94A3B8] mt-1">
                {activeNode.line_count} lines • {activeNode.symbol_count} symbols • {activeNode.language}
              </p>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onSelectFile(activeNode.id, 1)}
                className="btn-press flex-1 bg-[#181D26] hover:bg-[#222936] border border-[#2B3444] text-xs font-medium text-[#ECEFF4] py-2 px-3 rounded-lg"
              >
                Open Source File
              </button>
              <button
                type="button"
                onClick={() => onInspectImpact(activeNode.id)}
                className="btn-press flex-1 bg-[#0D9488] hover:bg-[#0F766E] text-xs font-medium text-white py-2 px-3 rounded-lg"
              >
                Run Change Radar
              </button>
            </div>

            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8] mb-2">
                Imported By ({incomingEdges.length} dependents)
              </h4>
              {incomingEdges.length === 0 ? (
                <p className="text-xs text-[#64748B]">No internal modules import this file.</p>
              ) : (
                <ul className="space-y-1.5">
                  {incomingEdges.map((edge) => (
                    <li
                      key={`${edge.source}-${edge.evidence.start_line}`}
                      className="flex items-center justify-between text-xs bg-[#141820] border border-[#1E242D] rounded-md px-2.5 py-1.5"
                    >
                      <button
                        type="button"
                        onClick={() => onSelectFile(edge.source, edge.evidence.start_line)}
                        className="font-mono text-[#5EEAD4] hover:underline truncate text-left"
                      >
                        [{edge.source}:{edge.evidence.start_line}]
                      </button>
                      <span className="text-[10px] text-[#64748B] font-mono ml-2">observed</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8] mb-2">
                Direct Imports ({outgoingEdges.length} modules)
              </h4>
              {outgoingEdges.length === 0 ? (
                <p className="text-xs text-[#64748B]">No internal repository imports.</p>
              ) : (
                <ul className="space-y-1.5">
                  {outgoingEdges.map((edge) => (
                    <li
                      key={`${edge.target}-${edge.evidence.start_line}`}
                      className="flex items-center justify-between text-xs bg-[#141820] border border-[#1E242D] rounded-md px-2.5 py-1.5"
                    >
                      <button
                        type="button"
                        onClick={() => onSelectFile(edge.target, 1)}
                        className="font-mono text-[#38BDF8] hover:underline truncate text-left"
                      >
                        {edge.target}
                      </button>
                      <button
                        type="button"
                        onClick={() => onSelectFile(edge.source, edge.evidence.start_line)}
                        className="text-[10px] text-[#94A3B8] hover:text-white font-mono ml-2"
                      >
                        cite L{edge.evidence.start_line}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : (
          <p className="text-xs text-[#64748B]">Select a graph node to inspect its import evidence.</p>
        )}

        <div className="pt-3 border-t border-[#1E242D] text-[11px] text-[#64748B]">
          Legend: <span className="text-[#F59E0B]">Amber = Entry point</span> •{' '}
          <span className="text-[#38BDF8]">Blue = Shared hub</span> •{' '}
          <span className="text-[#2DD4BF]">Teal = Active selection</span>
        </div>
      </div>
    </div>
  );
}
