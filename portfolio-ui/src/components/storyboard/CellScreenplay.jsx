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
        className="w-full rounded-frame border border-lead-500 bg-bay-900 p-2 font-mono text-[12px] leading-relaxed text-fg focus:outline-none resize-y min-h-[80px]"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        autoFocus
      />
    );
  }

  return (
    <button
      type="button"
      className="block w-full min-h-[40px] text-left font-mono text-[12px] leading-relaxed text-fg-muted hover:text-fg transition-colors line-clamp-6"
      onClick={() => setEditing(true)}
      title="Edit screenplay"
    >
      {scene.screenplay || <span className="text-fg-faint">Add screenplay</span>}
    </button>
  );
}
