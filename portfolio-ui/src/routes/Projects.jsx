import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { Plus, Loader2 } from 'lucide-react';

const STATUS = {
  complete: { dot: 'bg-ok', text: 'text-ok', label: 'Complete' },
  generating: { dot: 'bg-warn animate-pulse', text: 'text-warn', label: 'Generating' },
};
const STATUS_FALLBACK = { dot: 'bg-bay-600', text: 'text-fg-faint', label: 'Draft' };

export function Projects() {
  const navigate = useNavigate();
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center p-16">
        <Loader2 className="w-5 h-5 animate-spin text-lead-500" />
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto px-5 py-10">
      <div className="flex items-end justify-between mb-6 pb-4 border-b border-line">
        <div>
          <p className="label-slug mb-1.5">Slate</p>
          <h1 className="font-mono text-2xl font-bold text-fg">Projects</h1>
        </div>
        <button
          onClick={() => navigate('/new')}
          className="flex items-center gap-1.5 px-3 py-2 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> New project
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="border border-line rounded-frame bg-bay-850 px-8 py-16 text-center">
          <p className="font-mono text-base text-fg mb-1">Nothing on the slate yet.</p>
          <p className="text-sm text-fg-muted mb-6">
            Start from a rough idea — you'll get scenes, a cast, locations and a shot list to work from.
          </p>
          <button
            onClick={() => navigate('/new')}
            className="px-4 py-2 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors"
          >
            Start a project
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {projects.map((project) => {
            const s = STATUS[project.status] || STATUS_FALLBACK;
            return (
              <button
                key={project.id}
                onClick={() => navigate(`/project/${project.id}`)}
                className="group text-left rounded-frame overflow-hidden border border-line bg-bay-850 hover:bg-bay-800 hover:border-bay-600 transition-colors"
              >
                <div className="clapper h-[3px] w-full opacity-60 group-hover:opacity-100 transition-opacity" />
                <div className="p-4">
                  <h2 className="font-mono text-base font-bold text-fg leading-snug mb-4 line-clamp-2">
                    {project.title || 'Untitled project'}
                  </h2>
                  <div className="flex items-center justify-between">
                    <span className={`flex items-center gap-1.5 text-[11px] ${s.text}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                      {s.label}
                    </span>
                    <span className="font-mono text-[11px] text-fg-faint">
                      {new Date(project.created_at).toLocaleDateString(undefined, {
                        year: 'numeric', month: 'short', day: '2-digit',
                      })}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
