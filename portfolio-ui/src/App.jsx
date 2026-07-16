import { Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { Projects } from './routes/Projects';
import { NewProject } from './routes/NewProject';
import { Storyboard } from './routes/Storyboard';
import { Graph } from './routes/Graph';
import { SceneStage } from './routes/SceneStage';

function App() {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-[#0f172a] to-black text-slate-200 font-sans selection:bg-cyan-500/30">
      <header className="border-b border-white/10 backdrop-blur-md bg-black/30 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 group">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center text-xs font-bold text-white group-hover:scale-105 transition-transform">
              SP
            </div>
            <span className="font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300">
              Storyboard Pro
            </span>
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            {!isHome && (
              <Link to="/" className="text-slate-400 hover:text-white transition-colors">
                Projects
              </Link>
            )}
            <Link
              to="/new"
              className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-cyan-500 text-white text-sm font-medium hover:from-blue-500 hover:to-cyan-400 transition-all"
            >
              + New Project
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Projects />} />
          <Route path="/new" element={<NewProject />} />
          <Route path="/project/:id" element={<Storyboard />} />
          <Route path="/project/:id/graph" element={<Graph />} />
          <Route path="/project/:id/scene/:sceneId/stage" element={<SceneStage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
