import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Trash2, Upload } from 'lucide-react';
import { api } from '../../lib/api';

// The motion-source library for SCAIL-2 (reference + driving video -> SAM3
// pose transfer). Uploaded videos are reusable across projects and shots — a
// clip of someone walking gets uploaded once — so this renders an inline
// grid with its own upload control, not a scene-scoped picker like
// ReferencePicker. Selection follows the same ring-2 convention.
// Single-select (SCAIL-2) by default. Pass `multiple` + `selectedIds` + `onToggle`
// (and an optional `max`) to select several — MiniMax H3 R2V takes up to 3
// reference videos. Selection order is preserved so slot 1/2/3 stay stable.
export function DrivingVideoPicker({
  projectId, selectedId, onSelect,
  multiple = false, selectedIds = [], onToggle, max,
}) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);

  const isChosen = (id) => (multiple ? selectedIds.includes(id) : id === selectedId);
  const slotOf = (id) => (multiple ? selectedIds.indexOf(id) + 1 : 0);
  const atCapacity = multiple && max != null && selectedIds.length >= max;

  const { data: videos = [], isLoading } = useQuery({
    queryKey: ['driving-videos'],
    queryFn: () => api.listDrivingVideos(),
  });

  const uploadMut = useMutation({
    mutationFn: (file) => api.uploadDrivingVideo(file, { projectId, label: file.name }),
    onSuccess: (dv) => {
      queryClient.invalidateQueries({ queryKey: ['driving-videos'] });
      if (multiple) {
        if (!atCapacity) onToggle?.(dv.id);
      } else {
        onSelect?.(dv.id);
      }
    },
  });

  const choose = (id) => (multiple ? onToggle?.(id) : onSelect?.(id));

  const deleteMut = useMutation({
    mutationFn: (id) => api.deleteDrivingVideo(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['driving-videos'] });
      if (multiple) {
        if (selectedIds.includes(id)) onToggle?.(id);
      } else if (id === selectedId) {
        onSelect?.(null);
      }
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
          {multiple ? `Reference videos${max != null ? ` (${selectedIds.length}/${max})` : ''}` : 'Driving video'}
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
          accept="video/mp4,video/webm,video/quicktime"
          onChange={handleFile}
          className="hidden"
        />
      </div>

      {uploadMut.isError && (
        <p className="text-[10px] text-stop/80 break-words">{uploadMut.error.message}</p>
      )}

      {isLoading ? (
        <p className="text-[11px] text-fg-muted">Loading…</p>
      ) : videos.length === 0 ? (
        <p className="text-[11px] text-fg-muted">
          No driving videos yet — upload a clip of the motion you want to transfer.
        </p>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-1.5 max-h-64 overflow-y-auto">
          {videos.map((v) => {
            const isSelected = isChosen(v.id);
            const slot = slotOf(v.id);
            return (
              <div key={v.id} className="relative group/tile">
                <button
                  type="button"
                  onClick={() => choose(v.id)}
                  disabled={!isSelected && atCapacity}
                  title={v.label || v.video_url}
                  className={`w-full flex flex-col rounded overflow-hidden border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600 disabled:opacity-30 disabled:cursor-not-allowed ${
                    isSelected
                      ? 'border-transparent ring-2 ring-clip/50'
                      : 'border-line hover:border-bay-600'
                  }`}
                >
                  <div className="aspect-square bg-bay-900">
                    <video
                      src={api.getDrivingVideoUrl(v)}
                      muted
                      preload="metadata"
                      className="w-full h-full object-cover"
                    />
                  </div>
                  {multiple && slot > 0 && (
                    <span className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-bay-950/85 text-[9px] font-semibold text-fg flex items-center justify-center">
                      {slot}
                    </span>
                  )}
                  <span className="text-[9px] text-fg-muted truncate px-0.5 py-0.5 bg-bay-900 group-hover/tile:text-fg">
                    {v.label || v.video_url}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => deleteMut.mutate(v.id)}
                  title="Delete"
                  className="absolute top-0.5 right-0.5 w-4 h-4 rounded bg-bay-950/80 text-fg-muted hover:text-stop opacity-0 group-hover/tile:opacity-100 transition-opacity flex items-center justify-center focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bay-600"
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
