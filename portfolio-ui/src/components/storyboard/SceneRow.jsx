import { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { CellScreenplay } from './CellScreenplay';
import { CellCharacters } from './CellCharacters';
import { CellLocations } from './CellLocations';
import { CellProps } from './CellProps';
import { CellGeneration } from './CellGeneration';
import { GripVertical, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { useProjectStore } from '../../stores/projectStore';

export function SceneRow({ id, scene, projectId, index, onDelete }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const [editingSlug, setEditingSlug] = useState(false);
  const [slugValue, setSlugValue] = useState(scene.slugline || '');
  const updateScene = useProjectStore((s) => s.updateScene);

  const handleSaveSlug = async () => {
    setEditingSlug(false);
    const trimmed = slugValue.trim();
    updateScene(scene.id, { slugline: trimmed || null });
    try {
      await api.updateScene(scene.id, { slugline: trimmed || null });
    } catch (e) {
      console.error('Failed to save slugline', e);
    }
  };

  const handleSlugKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSaveSlug();
    } else if (e.key === 'Escape') {
      setSlugValue(scene.slugline || '');
      setEditingSlug(false);
    }
  };

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : undefined,
  };

  return (
    <tr
      ref={setNodeRef}
      style={style}
      className="border-b border-white/5 hover:bg-white/[0.02] transition-colors group"
    >
      <td className="sticky left-0 z-10 bg-[#0f172a] p-3 min-w-[140px] max-w-[140px]">
        <div className="flex items-center gap-2">
          <button
            ref={setActivatorNodeRef}
            {...attributes}
            {...listeners}
            className="cursor-grab active:cursor-grabbing p-0.5 rounded hover:bg-white/10 transition-colors shrink-0"
          >
            <GripVertical className="w-3.5 h-3.5 text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
          </button>
          <div className="min-w-0 overflow-hidden">
            <span className="text-xs font-bold text-cyan-400">SC {index + 1}</span>
            {editingSlug ? (
              <input
                className="w-full text-[10px] bg-black/60 border border-cyan-500/50 rounded px-1 py-0.5 text-white focus:outline-none mt-0.5"
                value={slugValue}
                onChange={(e) => setSlugValue(e.target.value)}
                onBlur={handleSaveSlug}
                onKeyDown={handleSlugKeyDown}
                autoFocus
              />
            ) : (
              <p
                className="text-[10px] text-slate-500 text-wrap mt-0.5 cursor-text"
                onClick={() => {
                  setSlugValue(scene.slugline || '');
                  setEditingSlug(true);
                }}
              >
                {scene.slugline || <span className="text-slate-600 italic">Add slugline...</span>}
              </p>
            )}
          </div>
        </div>
      </td>
      <td className="p-3 min-w-[200px] max-w-[250px]">
        <CellScreenplay scene={scene} />
      </td>
      <td className="p-3 min-w-[120px]">
        <CellCharacters scene={scene} projectId={projectId} />
      </td>
      <td className="p-3 min-w-[120px]">
        <CellLocations scene={scene} projectId={projectId} />
      </td>
      <td className="p-3 min-w-[100px]">
        <CellProps scene={scene} projectId={projectId} />
      </td>
      <td className="p-3 min-w-[100px]">
        <CellGeneration scene={scene} />
      </td>
      <td className="p-3 w-10">
        <button
          onClick={() => onDelete(scene.id)}
          className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-red-500/20"
        >
          <Trash2 className="w-3.5 h-3.5 text-red-400" />
        </button>
      </td>
    </tr>
  );
}
