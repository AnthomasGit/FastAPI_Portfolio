import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ReactFlow, Background, Controls, MiniMap, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../lib/api';
import { ArrowLeft } from 'lucide-react';

export function Graph() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['graph', id],
    queryFn: () => api.getProjectGraph(id),
  });

  if (isLoading) return <div className="flex justify-center p-12"><div className="animate-spin h-8 w-8 border-2 border-cyan-400 border-t-transparent rounded-full" /></div>;

  const nodeColors = { scene: '#3b82f6', character: '#22c55e', location: '#f59e0b', prop: '#a855f7' };

  const nodes = (data?.nodes || []).map((n) => ({
    id: n.id,
    type: 'default',
    position: { x: 0, y: 0 },
    data: { label: n.label },
    style: {
      background: nodeColors[n.type] || '#64748b',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      padding: '10px 16px',
      fontSize: '12px',
      fontWeight: 500,
    },
  }));

  const edges = (data?.edges || []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    style: { stroke: '#475569' },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' },
    labelStyle: { fill: '#94a3b8', fontSize: 10 },
  }));

  return (
    <div className="h-[calc(100vh-3.5rem)]">
      <div className="absolute top-4 left-4 z-10 flex items-center gap-3">
        <button onClick={() => navigate(`/project/${id}`)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-black/60 backdrop-blur-sm border border-white/10 text-sm text-slate-300 hover:text-white transition-colors">
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
        <div className="px-3 py-1.5 rounded-lg bg-black/60 backdrop-blur-sm border border-white/10 text-sm text-slate-300">
          Entity Relationships
        </div>
      </div>
      <div className="absolute bottom-4 left-4 z-10 flex gap-4">
        {Object.entries(nodeColors).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1.5 text-xs text-slate-400">
            <div className="w-3 h-3 rounded" style={{ background: color }} />
            {type}
          </div>
        ))}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        attributionPosition="bottom-right"
      >
        <Background color="#1e293b" gap={16} />
        <Controls className="[&>button]:bg-slate-800 [&>button]:border-slate-700 [&>button]:text-slate-300" />
        <MiniMap
          nodeColor={(n) => nodeColors[n.data?.type] || '#64748b'}
          style={{ background: '#0f172a', border: '1px solid #1e293b' }}
        />
      </ReactFlow>
    </div>
  );
}
