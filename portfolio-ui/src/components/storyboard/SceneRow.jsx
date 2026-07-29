import { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { CellScreenplay } from './CellScreenplay';
import { CellCharacters } from './CellCharacters';
import { CellLocations } from './CellLocations';
import { CellProps } from './CellProps';
import { CellShots } from './CellShots';
import { GripVertical, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { useProjectStore } from '../../stores/projectStore';

export function SceneRow({ id, scene, projectId, index, onDelete, colWidths }) {
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
      <td className="sticky left-0 z-10 bg-[#0f172a] p-3" style={{ width: colWidths.scene, minWidth: 120 }}>
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
            <div className="flex items-center gap-1.5">
              <Link
                to={`/project/${projectId}/scene/${scene.id}`}
                className="text-xs font-bold text-cyan-400 hover:text-cyan-300 transition-colors"
              >
                SC {index + 1}
              </Link>
              <Link
                to={`/project/${projectId}/scene/${scene.id}`}
                className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-600/20 text-cyan-300 hover:bg-cyan-600/30 transition-colors leading-none"
                title="Open scene details"
              >
                Details
              </Link>
            </div>
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
      <td className="p-3" style={{ width: colWidths.screenplay, minWidth: 120 }}>
        <CellScreenplay scene={scene} />
      </td>
      <td className="p-3" style={{ width: colWidths.characters, minWidth: 100 }}>
        <CellCharacters scene={scene} projectId={projectId} />
      </td>
      <td className="p-3" style={{ width: colWidths.locations, minWidth: 100 }}>
        <CellLocations scene={scene} projectId={projectId} />
      </td>
      <td className="p-3" style={{ width: colWidths.props, minWidth: 80 }}>
        <CellProps scene={scene} projectId={projectId} />
      </td>
      <td className="p-3" style={{ width: colWidths.shots, minWidth: 80 }}>
        <CellShots scene={scene} projectId={projectId} />
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
