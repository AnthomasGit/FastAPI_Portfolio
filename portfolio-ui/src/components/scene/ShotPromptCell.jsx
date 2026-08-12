import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Loader2, RefreshCw, Save } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { api } from '../../lib/api';

// The composed six-section H3 document for this shot.
//
// Composed once by the LLM and then owned by the user — renders read the stored
// text, so a retry costs nothing and an overnight batch is reviewable before it
// runs. Regenerating is therefore an explicit action, never a side effect.
export function ShotPromptCell({ shot, sceneId }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
  const text = draft ?? shot.clip_prompt ?? '';
  const dirty = draft != null && draft !== (shot.clip_prompt ?? '');

  const compose = useMutation({
    mutationFn: () => api.composeShotPrompt(shot.id, { force: true }),
    onSuccess: (r) => { setDraft(r.clip_prompt ?? ''); refresh(); },
  });
  const save = useMutation({
    mutationFn: () => api.updateShot(shot.id, { clip_prompt: draft }),
    onSuccess: () => { setDraft(null); refresh(); },
  });

  const has = !!shot.clip_prompt;
  const words = has ? shot.clip_prompt.split(/\s+/).length : 0;

  return (
    <>
      <button
        type="button"
        onClick={() => { setDraft(null); setOpen(true); }}
        title={has ? 'View or edit this shot’s clip prompt' : 'No clip prompt composed yet'}
        className="flex items-center gap-1 text-[10px] bg-bay-900 border border-line rounded px-1.5 py-0.5 text-fg hover:bg-bay-950/80 transition-colors"
      >
        <FileText className={`w-3 h-3 shrink-0 ${has ? 'text-lead-500' : 'text-fg-faint'}`} />
        <span className={has ? '' : 'text-fg-faint'}>{has ? `${words}w` : 'none'}</span>
      </button>

      <Dialog open={open} onOpenChange={(v) => { if (!v) setDraft(null); setOpen(v); }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              Clip prompt — shot {shot.shot_number || '?'}
            </DialogTitle>
          </DialogHeader>

          <p className="text-xs text-fg-muted -mt-1">
            The six-section MiniMax H3 document this shot renders from. Slot order
            in <span className="font-mono">Refs</span> is what
            {' '}<span className="font-mono">&lt;Subject N&gt;</span> refers to — if you
            reorder references, recompose so the text still matches the pictures.
          </p>

          {compose.isError && (
            <p role="alert" className="mt-2 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
              Couldn’t compose: {compose.error?.message || 'unknown error'}
            </p>
          )}

          <textarea
            value={text}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Not composed yet — use Regenerate."
            spellCheck={false}
            className="mt-3 w-full h-[52vh] rounded-frame border border-line bg-bay-900 px-3 py-2
                       font-mono text-[11px] leading-relaxed text-fg placeholder:text-fg-faint
                       focus:outline-none focus:border-lead-600 resize-none"
          />

          <div className="mt-3 flex items-center justify-between">
            <span className="text-[11px] text-fg-faint">
              {dirty ? 'Unsaved edits' : has ? `${words} words` : 'No prompt stored'}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => compose.mutate()}
                disabled={compose.isPending}
                title="Recompose from this shot's metadata and current references"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-frame border border-line text-xs text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors disabled:opacity-50"
              >
                {compose.isPending
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <RefreshCw className="w-3.5 h-3.5" />}
                Regenerate
              </button>
              <button
                type="button"
                onClick={() => save.mutate()}
                disabled={!dirty || save.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors disabled:opacity-40"
              >
                {save.isPending
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <Save className="w-3.5 h-3.5" />}
                Save
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
