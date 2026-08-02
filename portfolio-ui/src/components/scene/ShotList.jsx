import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Sparkles, Loader2, ListVideo } from 'lucide-react';
import { api } from '../../lib/api';
import { ShotRow } from './ShotRow';
import { sceneClipProgress } from './shotReadiness';

const COLUMNS = [
  'Shot #', 'Status', 'Size', 'Angle', 'Movement',
  'Description', 'Equipment', 'Audio / Notes', 'Still / Clip', '',
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
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <ListVideo className="w-5 h-5 text-cyan-400" />
        <h2 className="text-lg font-semibold text-slate-100">Master shot list</h2>
        {shots.length > 0 && (
          <span className="flex items-center gap-2" title={`${progress.done} of ${progress.total} shots have a completed clip`}>
            <span className="w-20 h-1 rounded-full bg-white/10 overflow-hidden">
              <span
                className="block h-full bg-fuchsia-500/60 transition-all"
                style={{ width: `${progress.pct}%` }}
              />
            </span>
            <span className="text-[10px] text-slate-500">
              {progress.done}/{progress.total} clips
            </span>
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => genMut.mutate()}
          disabled={genMut.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs bg-cyan-600/20 text-cyan-300 hover:bg-cyan-600/30 disabled:opacity-40 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
        >
          {genMut.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles className="w-3.5 h-3.5" />
          )}
          Generate shot list
        </button>
      </div>
      {genMut.isError && (
        <p className="text-xs text-red-400">{genMut.error.message}</p>
      )}

      <div className="rounded-xl border border-white/10 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-white/[0.03]">
              {COLUMNS.map((c, i) => (
                <th key={i} className="px-2 py-2 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none inline" />
              </td></tr>
            ) : shots.length === 0 ? (
              <tr><td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-sm text-slate-600">
                No shots yet. Generate a draft from the screenplay, or add one.
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
        <div className="p-2 border-t border-white/5">
          <button
            onClick={() => addMut.mutate()}
            disabled={addMut.isPending}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-cyan-400 transition-colors disabled:opacity-40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 rounded px-1"
          >
            <Plus className="w-3.5 h-3.5" /> Add shot
          </button>
        </div>
      </div>
    </section>
  );
}
