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
      <div className="rounded-frame border border-lead-500 bg-bay-900 p-5 space-y-3">
        <input
          value={slugline}
          onChange={(e) => setSlugline(e.target.value)}
          placeholder="INT. LOCATION - DAY"
          className="w-full bg-bay-900 border border-line rounded px-3 py-2 font-mono text-sm uppercase tracking-wide text-lead-500 focus:outline-none focus:border-lead-500"
        />
        <textarea
          value={screenplay}
          onChange={(e) => setScreenplay(e.target.value)}
          rows={10}
          placeholder="Action and dialogue..."
          className="w-full bg-bay-900 border border-line rounded px-3 py-2 font-mono text-sm leading-relaxed text-fg resize-y focus:outline-none focus:border-lead-500"
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={cancel}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-xs text-fg-muted hover:text-fg hover:bg-bay-700 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-lead-500"
          >
            <X className="w-3.5 h-3.5" /> Cancel
          </button>
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-xs bg-lead-500 hover:bg-lead-400 text-bay-950 disabled:opacity-40 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-lead-500"
          >
            <Check className="w-3.5 h-3.5" /> Save
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative rounded-frame border border-line bg-bay-900 p-6">
      <button
        onClick={startEditing}
        title="Edit screenplay"
        className="absolute right-3 top-3 p-1.5 rounded text-fg-faint opacity-0 group-hover:opacity-100 hover:text-lead-500 hover:bg-bay-700 transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-lead-500 focus-visible:opacity-100"
      >
        <Pencil className="w-3.5 h-3.5" />
      </button>
      <p className="label-slug mb-3">Screenplay</p>
      {scene.screenplay ? (
        /* Held to roughly a screenplay's 60-character measure — the same line
           length the page it came from would have. */
        <pre className="font-mono text-[13px] leading-[1.7] text-fg whitespace-pre-wrap break-words max-w-[60ch]">
          {scene.screenplay}
        </pre>
      ) : (
        <p className="text-sm text-fg-faint">Nothing written yet. Use the pencil to draft the scene.</p>
      )}
    </div>
  );
}
