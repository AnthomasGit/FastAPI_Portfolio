import { CellScreenplay } from './CellScreenplay';
import { CellCharacters } from './CellCharacters';
import { CellLocations } from './CellLocations';
import { CellProps } from './CellProps';
import { CellGeneration } from './CellGeneration';
import { GripVertical, Trash2 } from 'lucide-react';

export function SceneRow({ scene, projectId, index, onDelete }) {
  return (
    <tr className="border-b border-white/5 hover:bg-white/[0.02] transition-colors group">
      <td className="sticky left-0 z-10 bg-[#0f172a] p-3 min-w-[140px] max-w-[140px]">
        <div className="flex items-center gap-2">
          <GripVertical className="w-3.5 h-3.5 text-slate-600 cursor-grab opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
          <div>
            <span className="text-xs font-bold text-cyan-400">SC {index + 1}</span>
            {scene.slugline && (
              <p className="text-[10px] text-slate-500 truncate mt-0.5">{scene.slugline}</p>
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
