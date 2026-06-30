import { useState, useEffect } from 'react';
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

export function SceneTable({ scenes, projectId }) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState(scenes);

  useEffect(() => {
    setItems(scenes);
  }, [scenes]);

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
    <div className="overflow-x-auto rounded-xl border border-white/10">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10 bg-white/[0.03]">
            <th className="sticky left-0 z-10 bg-[#0f172a] p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[140px] max-w-[140px]">
              Scene
            </th>
            <th className="p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[200px]">
              Screenplay
            </th>
            <th className="p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[120px]">
              Characters
            </th>
            <th className="p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[120px]">
              Locations
            </th>
            <th className="p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[100px]">
              Props
            </th>
            <th className="p-3 text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider min-w-[100px]">
              Video
            </th>
            <th className="p-3 w-10" />
          </tr>
        </thead>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
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
                />
              ))}
            </tbody>
          </SortableContext>
        </DndContext>
      </table>
      <div className="p-3 border-t border-white/5">
        <button
          onClick={handleAddScene}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-cyan-400 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Scene
        </button>
      </div>
    </div>
  );
}
