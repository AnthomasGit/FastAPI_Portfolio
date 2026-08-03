import { Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { Projects } from './routes/Projects';
import { NewProject } from './routes/NewProject';
import { Storyboard } from './routes/Storyboard';
import { SceneDetail } from './routes/SceneDetail';
import { Graph } from './routes/Graph';
import { SceneStage } from './routes/SceneStage';
import { ClipStudio } from './routes/ClipStudio';

function App() {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="min-h-screen bg-bay-950 text-fg font-sans">
      <header className="sticky top-0 z-50 border-b border-line bg-bay-950">
        {/* Clapper cap: the app's one signature, at its smallest size. */}
        <div className="clapper h-[3px] w-full" aria-hidden="true" />
        <div className="max-w-[1600px] mx-auto px-5 h-12 flex items-center justify-between">
          <Link to="/" className="flex items-baseline gap-2.5">
            <span className="font-mono text-sm font-bold tracking-tight text-fg">
              STORYBOARD<span className="text-lead-500">/</span>PRO
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            {!isHome && (
              <Link
                to="/"
                className="px-3 py-1.5 rounded-frame text-xs text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors"
              >
                Projects
              </Link>
            )}
            <Link
              to="/new"
              className="px-3 py-1.5 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors"
            >
              New project
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
          <Route path="/project/:id/scene/:sceneId" element={<SceneDetail />} />
          <Route path="/project/:id/scene/:sceneId/stage" element={<SceneStage />} />
          <Route path="/project/:id/scene/:sceneId/shot/:shotId/clip" element={<ClipStudio />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
