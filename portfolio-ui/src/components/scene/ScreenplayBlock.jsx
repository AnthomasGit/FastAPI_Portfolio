import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil, Check, X } from 'lucide-react';
import { api } from '../../lib/api';

// Renders a scene's screenplay in its own vernacular — courier, a bright
// uppercase slugline, generous leading — so the page opens with the thing the
// scene actually *is*. Click to edit inline. Display reads scene.* directly;
// the local state only backs the edit form (seeded when editing starts).
export function ScreenplayBlock({ scene }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [slugline, setSlugline] = useState(scene.slugline || '');
  const [screenplay, setScreenplay] = useState(scene.screenplay || '');

  const startEditing = () => {
    setSlugline(scene.slugline || '');
    setScreenplay(scene.screenplay || '');
    setEditing(true);
  };

  const saveMut = useMutation({
    mutationFn: () => api.updateScene(scene.id, { slugline, screenplay }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scene', scene.id] });
      setEditing(false);
    },
  });

  const cancel = () => setEditing(false);

  if (editing) {
    return (
      <div className="rounded-xl border border-cyan-500/30 bg-black/40 p-5 space-y-3">
        <input
          value={slugline}
          onChange={(e) => setSlugline(e.target.value)}
          placeholder="INT. LOCATION - DAY"
          className="w-full bg-black/60 border border-white/10 rounded px-3 py-2 font-mono text-sm uppercase tracking-wide text-cyan-300 focus:outline-none focus:border-cyan-500/50"
        />
        <textarea
          value={screenplay}
          onChange={(e) => setScreenplay(e.target.value)}
          rows={10}
          placeholder="Action and dialogue..."
          className="w-full bg-black/60 border border-white/10 rounded px-3 py-2 font-mono text-sm leading-relaxed text-slate-200 resize-y focus:outline-none focus:border-cyan-500/50"
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={cancel}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-xs text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-400"
          >
            <X className="w-3.5 h-3.5" /> Cancel
          </button>
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-xs bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-40 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-300"
          >
            <Check className="w-3.5 h-3.5" /> Save
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative rounded-xl border border-white/10 bg-black/40 p-6">
      <button
        onClick={startEditing}
        title="Edit screenplay"
        className="absolute right-3 top-3 p-1.5 rounded text-slate-600 opacity-0 group-hover:opacity-100 hover:text-cyan-400 hover:bg-white/10 transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 focus-visible:opacity-100"
      >
        <Pencil className="w-3.5 h-3.5" />
      </button>
      <p className="font-mono text-sm font-bold uppercase tracking-widest text-cyan-300">
        {scene.slugline || <span className="text-slate-600 normal-case tracking-normal italic">No slugline — click to add</span>}
      </p>
      {scene.screenplay ? (
        <pre className="mt-4 font-mono text-[13px] leading-relaxed text-slate-300 whitespace-pre-wrap break-words">
          {scene.screenplay}
        </pre>
      ) : (
        <p className="mt-4 text-sm text-slate-600 italic">No screenplay yet — click the pencil to write one.</p>
      )}
    </div>
  );
}
