import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { Plus, Film } from 'lucide-react';

export function Projects() {
  const navigate = useNavigate();
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  });

  if (isLoading) return <div className="flex justify-center p-12"><div className="animate-spin h-8 w-8 border-2 border-cyan-400 border-t-transparent rounded-full" /></div>;

  return (
    <div className="max-w-7xl mx-auto px-4 py-12">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold">Your Projects</h1>
        <button onClick={() => navigate('/new')} className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-medium hover:from-blue-500 hover:to-cyan-400 transition-all">
          <Plus className="w-4 h-4" /> New Project
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="text-center py-24 bg-white/5 rounded-2xl border border-white/10">
          <Film className="w-16 h-16 mx-auto mb-4 text-slate-600" />
          <p className="text-slate-400 text-lg mb-2">No projects yet</p>
          <p className="text-slate-500 text-sm mb-6">Enter a rough video idea and let AI build your storyboard</p>
          <button onClick={() => navigate('/new')} className="px-6 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-medium hover:from-blue-500 hover:to-cyan-400 transition-all">
            Create Your First Project
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((project) => (
            <div
              key={project.id}
              onClick={() => navigate(`/project/${project.id}`)}
              className="group cursor-pointer bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-cyan-500/50 hover:bg-white/10 transition-all hover:-translate-y-0.5"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold text-lg text-white group-hover:text-cyan-300 transition-colors">
                  {project.title || 'Untitled Project'}
                </h3>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  project.status === 'complete' ? 'bg-emerald-500/20 text-emerald-300' :
                  project.status === 'generating' ? 'bg-amber-500/20 text-amber-300' :
                  'bg-slate-500/20 text-slate-400'
                }`}>
                  {project.status}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                {new Date(project.created_at).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
