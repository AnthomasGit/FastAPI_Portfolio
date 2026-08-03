import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Music, Trash2, Upload } from 'lucide-react';
import { api } from '../../lib/api';

// Standalone audio-clip library for MiniMax H3 R2V (up to `max` clips). Same
// reusable cross-project shape and multi-select convention as the reference-video
// picker; selection order is preserved so slot 1/2/3 stay stable.
export function AudioPicker({ projectId, selectedIds = [], onToggle, max }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);

  const atCapacity = max != null && selectedIds.length >= max;

  const { data: clips = [], isLoading } = useQuery({
    queryKey: ['reference-audios'],
    queryFn: () => api.listReferenceAudios(),
  });

  const uploadMut = useMutation({
    mutationFn: (file) => api.uploadReferenceAudio(file, { projectId, label: file.name }),
    onSuccess: (ra) => {
      queryClient.invalidateQueries({ queryKey: ['reference-audios'] });
      if (!atCapacity) onToggle?.(ra.id);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id) => api.deleteReferenceAudio(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['reference-audios'] });
      if (selectedIds.includes(id)) onToggle?.(id);
    },
  });

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
    e.target.value = '';
  };

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h3 className="text-[10px] font-semibold text-fg-muted uppercase tracking-wider">
          Reference audio{max != null ? ` (${selectedIds.length}/${max})` : ''}
        </h3>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMut.isPending}
          className="flex items-center gap-1 text-[10px] text-fg-muted hover:text-fg disabled:opacity-40 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 rounded px-1"
        >
          {uploadMut.isPending ? (
            <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
          ) : (
            <Upload className="w-3 h-3" />
          )}
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          onChange={handleFile}
          className="hidden"
        />
      </div>

      {uploadMut.isError && (
        <p className="text-[10px] text-stop/80 break-words">{uploadMut.error.message}</p>
      )}

      {isLoading ? (
        <p className="text-[11px] text-fg-muted">Loading…</p>
      ) : clips.length === 0 ? (
        <p className="text-[11px] text-fg-muted">
          No audio clips yet — upload a voice or soundtrack reference.
        </p>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {clips.map((a) => {
            const slot = selectedIds.indexOf(a.id) + 1;
            const isSelected = slot > 0;
            return (
              <div
                key={a.id}
                className={`relative flex items-center gap-2 rounded border px-2 py-1.5 transition-colors ${
                  isSelected ? 'border-transparent ring-2 ring-clip/50' : 'border-line'
                }`}
              >
                <button
                  type="button"
                  onClick={() => onToggle?.(a.id)}
                  disabled={!isSelected && atCapacity}
                  title={a.label || a.audio_url}
                  className="flex items-center gap-1.5 min-w-0 flex-1 text-left disabled:opacity-30 disabled:cursor-not-allowed focus-visible:outline-none"
                >
                  <span className="w-4 h-4 rounded-full bg-bay-950/85 text-[9px] font-semibold text-fg flex items-center justify-center shrink-0">
                    {isSelected ? slot : <Music className="w-2.5 h-2.5 text-fg-muted" />}
                  </span>
                  <span className="text-[10px] text-fg-muted truncate">
                    {a.label || a.audio_url}
                  </span>
                </button>
                <audio src={api.getReferenceAudioUrl(a)} controls preload="none" className="h-6 max-w-[9rem]" />
                <button
                  type="button"
                  onClick={() => deleteMut.mutate(a.id)}
                  title="Delete"
                  className="w-4 h-4 rounded text-fg-muted hover:text-stop shrink-0 flex items-center justify-center focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600"
                >
                  <Trash2 className="w-2.5 h-2.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
