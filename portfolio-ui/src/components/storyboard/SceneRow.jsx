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
      className="group border-b border-line align-top [&>td]:bg-bay-850 hover:[&>td]:bg-bay-800 [&>td]:transition-colors"
    >
      {/* The slate. Scene number boxed like a clapper's, slugline in the
          typeface a screenplay is actually set in. */}
      <td
        className="sticky left-0 z-10 px-3 py-2.5"
        style={{ width: colWidths.scene, minWidth: 140 }}
      >
        <div className="flex items-start gap-1.5">
          <button
            ref={setActivatorNodeRef}
            {...attributes}
            {...listeners}
            aria-label={`Reorder scene ${index + 1}`}
            className="mt-0.5 shrink-0 cursor-grab active:cursor-grabbing rounded-frame p-0.5 hover:bg-bay-700 transition-colors"
          >
            <GripVertical className="w-3.5 h-3.5 text-bay-600 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
          <div className="min-w-0 flex-1">
            <Link
              to={`/project/${projectId}/scene/${scene.id}`}
              className="inline-block rounded-frame border border-bay-600 px-1.5 py-0.5 font-mono text-[11px] font-bold text-fg hover:border-lead-500 hover:text-lead-500 transition-colors"
              title="Open scene"
            >
              SC {index + 1}
            </Link>
            {editingSlug ? (
              <input
                className="mt-1.5 w-full rounded-frame border border-lead-500 bg-bay-900 px-1.5 py-1 font-mono text-[11px] uppercase text-fg focus:outline-none"
                value={slugValue}
                onChange={(e) => setSlugValue(e.target.value)}
                onBlur={handleSaveSlug}
                onKeyDown={handleSlugKeyDown}
                autoFocus
              />
            ) : (
              <button
                type="button"
                className="mt-1.5 block w-full text-left font-mono text-[11px] font-bold uppercase leading-snug tracking-wide text-fg-muted hover:text-fg transition-colors"
                onClick={() => {
                  setSlugValue(scene.slugline || '');
                  setEditingSlug(true);
                }}
                title="Edit slugline"
              >
                {scene.slugline || <span className="normal-case tracking-normal font-normal text-fg-faint">Add slugline</span>}
              </button>
            )}
          </div>
        </div>
      </td>
      <td className="px-3 py-2.5" style={{ width: colWidths.screenplay, minWidth: 160 }}>
        <CellScreenplay scene={scene} />
      </td>
      <td className="px-3 py-2.5" style={{ width: colWidths.characters, minWidth: 110 }}>
        <CellCharacters scene={scene} projectId={projectId} />
      </td>
      <td className="px-3 py-2.5" style={{ width: colWidths.locations, minWidth: 110 }}>
        <CellLocations scene={scene} projectId={projectId} />
      </td>
      <td className="px-3 py-2.5" style={{ width: colWidths.props, minWidth: 90 }}>
        <CellProps scene={scene} projectId={projectId} />
      </td>
      <td className="px-3 py-2.5" style={{ width: colWidths.shots, minWidth: 100 }}>
        <CellShots scene={scene} projectId={projectId} />
      </td>
      <td className="w-10 px-2 py-2.5">
        <button
          onClick={() => onDelete(scene.id)}
          aria-label={`Delete scene ${index + 1}`}
          className="rounded-frame p-1 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-fg-faint hover:text-stop hover:bg-stop/10 transition-all"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </td>
    </tr>
  );
}
