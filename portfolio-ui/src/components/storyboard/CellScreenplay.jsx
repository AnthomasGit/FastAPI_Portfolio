import { useState, useRef } from 'react';
import { api } from '../../lib/api';
import { useProjectStore } from '../../stores/projectStore';

export function CellScreenplay({ scene }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(scene.screenplay || '');
  const textareaRef = useRef(null);
  const updateScene = useProjectStore((s) => s.updateScene);

  const handleSave = async () => {
    setEditing(false);
    updateScene(scene.id, { screenplay: value });
    try {
      await api.updateScene(scene.id, { screenplay: value });
    } catch (e) {
      console.error('Failed to save screenplay', e);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setValue(scene.screenplay || '');
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        className="w-full bg-black/60 border border-cyan-500/50 rounded-lg p-2 text-white text-xs focus:outline-none resize-none min-h-[60px]"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        autoFocus
      />
    );
  }

  return (
    <div
      className="min-h-[40px] cursor-text text-xs text-slate-300 leading-relaxed"
      onClick={() => setEditing(true)}
    >
      {scene.screenplay || <span className="text-slate-600 italic">Click to add screenplay...</span>}
    </div>
  );
}
