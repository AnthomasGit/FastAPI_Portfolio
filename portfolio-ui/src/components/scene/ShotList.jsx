import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Sparkles, Loader2 } from 'lucide-react';
import { api } from '../../lib/api';
import { ShotRow } from './ShotRow';
import { sceneClipProgress } from './shotReadiness';

const COLUMNS = [
  'Shot', 'State', 'Size', 'Angle', 'Move',
  'Action', 'Rig', 'Audio / notes', 'Still · clip', '',
];

export function ShotList({ scene }) {
  const sceneId = scene.id;
  const queryClient = useQueryClient();

  const { data: shots = [], isLoading } = useQuery({
    queryKey: ['shots', sceneId],
    queryFn: () => api.listShots(sceneId),
  });

  // Beauty stills available to attach to a shot come from this scene's captures.
  const { data: captures = [] } = useQuery({
    queryKey: ['captures', sceneId],
    queryFn: () => api.listCaptures(sceneId),
  });
  const availableStills = captures.flatMap((cap, ci) =>
    (cap.generated_images || [])
      .filter((g) => g.status === 'completed' && g.kind === 'beauty')
      .map((g, gi) => ({ id: g.id, label: `Capture ${captures.length - ci} · still ${gi + 1}` }))
  );

  const genMut = useMutation({
    mutationFn: () => api.generateShotList(sceneId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });
  const addMut = useMutation({
    mutationFn: () => api.createShot(sceneId, { shot_number: `${scene.scene_number}${String.fromCharCode(65 + shots.length)}` }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });

  const progress = sceneClipProgress(shots);

  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-sm font-semibold text-fg">Master shot list</h2>
        {shots.length > 0 && (
          <span
            className="flex items-center gap-2"
            title={`${progress.done} of ${progress.total} shots have a finished clip`}
          >
            <span className="w-16 h-[3px] rounded-full bg-bay-700 overflow-hidden">
              <span className="block h-full bg-clip transition-all" style={{ width: `${progress.pct}%` }} />
            </span>
            <span className="font-mono text-[11px] text-fg-faint tabular-nums">
              {progress.done}/{progress.total} covered
            </span>
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => genMut.mutate()}
          disabled={genMut.isPending}
          className="flex items-center gap-1.5 rounded-frame border border-line px-2.5 py-1.5 text-xs text-fg-muted hover:text-fg hover:bg-bay-800 disabled:opacity-40 transition-colors"
        >
          {genMut.isPending
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <Sparkles className="w-3.5 h-3.5" />}
          {genMut.isPending ? 'Drafting…' : 'Draft from screenplay'}
        </button>
      </div>
      {genMut.isError && (
        <p role="alert" className="mb-2 rounded-frame border border-stop/30 bg-stop/15 px-3 py-2 text-xs text-stop">
          Couldn't draft the shot list: {genMut.error.message}
        </p>
      )}

      <div className="rounded-frame border border-line bg-bay-850 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr>
                {COLUMNS.map((c, i) => (
                  <th key={i} className="px-2 py-2.5 text-left label-slug bg-bay-800 border-b border-line whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={COLUMNS.length} className="px-3 py-8 text-center">
                  <Loader2 className="w-4 h-4 animate-spin inline text-lead-500" />
                </td></tr>
              ) : shots.length === 0 ? (
                <tr><td colSpan={COLUMNS.length} className="px-3 py-8 text-center">
                  <p className="text-sm text-fg-muted">No coverage planned yet.</p>
                  <p className="text-xs text-fg-faint mt-1">
                    Draft a list from the screenplay, or add shots one at a time.
                  </p>
                </td></tr>
              ) : (
                shots.map((shot) => (
                  <ShotRow
                    key={shot.id}
                    shot={shot}
                    sceneId={sceneId}
                    availableStills={availableStills}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="px-3 py-2 border-t border-line">
          <button
            onClick={() => addMut.mutate()}
            disabled={addMut.isPending}
            className="flex items-center gap-1.5 rounded-frame px-1.5 py-1 text-xs text-fg-muted hover:text-lead-500 transition-colors disabled:opacity-40"
          >
            <Plus className="w-3.5 h-3.5" /> Add shot
          </button>
        </div>
      </div>
    </section>
  );
}
