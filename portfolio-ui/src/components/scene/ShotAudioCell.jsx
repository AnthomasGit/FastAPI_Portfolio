import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Music, X } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from '../ui/popover';
import { api } from '../../lib/api';

// The audio FILE fed to the clip graph's LoadAudio slot — distinct from the
// "Audio / notes" column, which is planning text that feeds the prompt.
//
// audio_role is load-bearing, not a description. The H3 guide treats the two
// cases differently and the composed prompt changes accordingly:
//   dialogue -> [audio reuse],     <Audio 1>: fully_copy, lines preserved verbatim
//   timbre   -> [audio reference], <Audio 1>: reference,  and the guide FORBIDS
//               carrying the source dialogue into the target video.
const ROLES = [
  { value: 'dialogue', label: 'Dialogue', hint: 'The clip reuses these spoken lines verbatim.' },
  { value: 'timbre', label: 'Voice ref', hint: 'Only the voice timbre is followed; the lines are not reused.' },
];

export function ShotAudioCell({ shot, sceneId }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const { data: clips = [] } = useQuery({
    queryKey: ['reference-audios'],
    queryFn: () => api.listReferenceAudios(),
    enabled: open,
  });

  const selected = clips.find((c) => c.id === shot.reference_audio_id);
  const role = shot.audio_role || 'dialogue';

  const save = useMutation({
    mutationFn: (patch) => api.updateShot(shot.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shots', sceneId] }),
  });

  const pick = (id) => save.mutate({
    reference_audio_id: id,
    // Default the role when attaching audio, so the prompt has a rule to follow.
    audio_role: id ? (shot.audio_role || 'dialogue') : null,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title="Audio file fed to the clip (separate from the Audio / notes text)"
          className="flex items-center gap-1 text-[10px] bg-bay-900 border border-line rounded px-1.5 py-0.5 text-fg hover:bg-bay-950/80 transition-colors max-w-[120px]"
        >
          <Music className={`w-3 h-3 shrink-0 ${shot.reference_audio_id ? 'text-lead-500' : 'text-fg-faint'}`} />
          <span className="truncate">
            {shot.reference_audio_id
              ? (selected?.label || 'audio')
              : <span className="text-fg-faint">none</span>}
          </span>
          {shot.reference_audio_id && (
            <span className="text-fg-faint shrink-0">
              {role === 'timbre' ? 'ref' : 'dlg'}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent className="w-64 p-2 bg-bay-850 border-line" align="start">
        <span className="label-slug block mb-1.5">Clip audio</span>

        {clips.length === 0 ? (
          <p className="text-[11px] text-fg-muted p-1">
            No audio uploaded yet — add clips from Clip Studio.
          </p>
        ) : (
          <ul className="space-y-0.5 max-h-40 overflow-y-auto">
            <li>
              <button
                type="button"
                onClick={() => pick(null)}
                className={`w-full flex items-center gap-1.5 px-1 py-1 rounded text-[11px] text-left transition-colors ${
                  !shot.reference_audio_id ? 'bg-bay-800 text-fg' : 'text-fg-muted hover:bg-bay-900'
                }`}
              >
                <X className="w-3 h-3 shrink-0" /> None
              </button>
            </li>
            {clips.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => pick(c.id)}
                  className={`w-full flex items-center gap-1.5 px-1 py-1 rounded text-[11px] text-left transition-colors ${
                    c.id === shot.reference_audio_id ? 'bg-bay-800 text-fg' : 'text-fg-muted hover:bg-bay-900'
                  }`}
                >
                  <Music className="w-3 h-3 shrink-0" />
                  <span className="truncate">{c.label || c.audio_url}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {shot.reference_audio_id && (
          <div className="mt-2 pt-2 border-t border-line">
            <span className="label-slug block mb-1">How it is used</span>
            <div className="flex gap-1">
              {ROLES.map((r) => (
                <button
                  key={r.value}
                  type="button"
                  onClick={() => save.mutate({ audio_role: r.value })}
                  className={`flex-1 px-1.5 py-1 rounded-frame border text-[10px] transition-colors ${
                    role === r.value
                      ? 'border-lead-600 text-lead-400 bg-lead-600/10'
                      : 'border-line text-fg-muted hover:text-fg'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[10px] text-fg-faint leading-snug">
              {ROLES.find((r) => r.value === role)?.hint}
            </p>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
