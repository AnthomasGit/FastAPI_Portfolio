import { useState, useEffect, useRef } from 'react';
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor, useSensor, useSensors,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { SceneRow } from './SceneRow';
import { Plus } from 'lucide-react';
import { api } from '../../lib/api';
import { useQueryClient } from '@tanstack/react-query';

const COLUMN_DEFAULTS = {
  scene: 180, screenplay: 320, characters: 160, locations: 160, props: 140, shots: 180,
};
const COLUMN_MIN_WIDTHS = {
  scene: 140, screenplay: 160, characters: 110, locations: 110, props: 90, shots: 100,
};
const COLUMN_LABELS = {
  scene: 'Scene',
  screenplay: 'Screenplay',
  characters: 'Characters',
  locations: 'Locations',
  props: 'Props',
  shots: 'Stills',
};
const COLUMN_KEYS = ['scene', 'screenplay', 'characters', 'locations', 'props', 'shots'];

export function SceneTable({ scenes, projectId }) {
  const queryClient = useQueryClient();
  // Local copy so drag-reorder can update optimistically; re-sync to the server
  // list during render when it changes (React's recommended alt to an effect).
  const [items, setItems] = useState(scenes);
  const [lastScenes, setLastScenes] = useState(scenes);
  if (scenes !== lastScenes) {
    setLastScenes(scenes);
    setItems(scenes);
  }

  const [colWidths, setColWidths] = useState(() => {
    try {
      const saved = localStorage.getItem('storyboard-col-widths');
      return saved ? { ...COLUMN_DEFAULTS, ...JSON.parse(saved) } : COLUMN_DEFAULTS;
    } catch {
      return COLUMN_DEFAULTS;
    }
  });
  const [isResizing, setIsResizing] = useState(false);
  const colWidthsRef = useRef(colWidths);
  useEffect(() => { colWidthsRef.current = colWidths; }, [colWidths]);

  useEffect(() => {
    document.body.style.cursor = isResizing ? 'col-resize' : '';
    document.body.style.userSelect = isResizing ? 'none' : '';
  }, [isResizing]);

  const startResize = (colKey, e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = colWidths[colKey];

    setIsResizing(true);

    const handleMouseMove = (move) => {
      const delta = move.clientX - startX;
      const newWidth = Math.max(COLUMN_MIN_WIDTHS[colKey], startWidth + delta);
      setColWidths((prev) => ({ ...prev, [colKey]: newWidth }));
    };

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      setIsResizing(false);
      localStorage.setItem('storyboard-col-widths', JSON.stringify(colWidthsRef.current));
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = async (event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    let orderedIds;
    setItems((current) => {
      const oldIndex = current.findIndex((s) => s.id === active.id);
      const newIndex = current.findIndex((s) => s.id === over.id);
      const reordered = [...current];
      const [moved] = reordered.splice(oldIndex, 1);
      reordered.splice(newIndex, 0, moved);
      orderedIds = reordered.map((s) => s.id);
      return reordered;
    });

    try {
      await api.reorderScenes(orderedIds);
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    } catch (e) {
      console.error('Failed to reorder scenes', e);
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    }
  };

  const handleAddScene = async () => {
    try {
      const sceneNumber = (items?.length || 0) + 1;
      await api.createScene(projectId, { scene_number: sceneNumber, sort_order: sceneNumber });
      queryClient.invalidateQueries({ queryKey: ['project', projectId], refetchType: 'all' });
    } catch (e) {
      console.error('Failed to add scene', e);
    }
  };

  const handleDeleteScene = async (sceneId) => {
    try {
      await api.deleteScene(sceneId);
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    } catch (e) {
      console.error('Failed to delete scene', e);
    }
  };

  return (
    <div className="rounded-frame border border-line bg-bay-850 overflow-hidden">
      <div className="max-h-[calc(100vh-15rem)] overflow-auto">
        {/* DndContext renders its own a11y announcer div as a sibling of its
            children in place — wrapping only <tbody> put that div directly
            inside <table>, which is invalid HTML and threw a hydration
            warning. Wrapping the whole <table> keeps that div outside it. */}
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <table className="w-full text-sm table-fixed border-collapse">
            <thead>
              {/* The header sticks to the top of this scroll box (position:sticky on a
                  <tr> is ignored) so column names stay readable while you scroll
                  a long breakdown. */}
              <tr>
                {COLUMN_KEYS.map((key) => (
                  <th
                    key={key}
                    className={`relative px-3 py-2.5 text-left label-slug bg-bay-800 border-b border-line sticky top-0 ${
                      key === 'scene' ? 'left-0 z-30' : 'z-20'
                    }`}
                    style={{ width: colWidths[key], minWidth: COLUMN_MIN_WIDTHS[key] }}
                  >
                    {COLUMN_LABELS[key]}
                    <div
                      role="separator"
                      aria-label={`Resize ${COLUMN_LABELS[key]} column`}
                      className="absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-lead-500 active:bg-lead-400 transition-colors"
                      onMouseDown={(e) => startResize(key, e)}
                    />
                  </th>
                ))}
                <th className="w-10 bg-bay-800 border-b border-line sticky top-0 z-20" />
              </tr>
            </thead>
            <SortableContext items={items.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              <tbody>
                {items.map((scene, i) => (
                  <SceneRow
                    key={scene.id}
                    id={scene.id}
                    scene={scene}
                    projectId={projectId}
                    index={i}
                    onDelete={handleDeleteScene}
                    colWidths={colWidths}
                  />
                ))}
              </tbody>
            </SortableContext>
          </table>
        </DndContext>
      </div>
      <div className="px-3 py-2 border-t border-line">
        <button
          onClick={handleAddScene}
          className="flex items-center gap-1.5 rounded-frame px-1.5 py-1 text-xs text-fg-muted hover:text-lead-500 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Add scene
        </button>
      </div>
    </div>
  );
}
