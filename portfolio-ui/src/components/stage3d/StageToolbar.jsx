import { Button } from '@/components/ui/button';
import { Camera, Box, Square, Grid, Loader2, X, Move, RotateCw, Maximize, Zap, Layers, Undo2, Redo2 } from 'lucide-react';
import { useStagingStore } from '@/stores/stagingStore';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';

const MODES = [
  { key: 'translate', icon: Move, label: 'Move' },
  { key: 'rotate', icon: RotateCw, label: 'Rotate' },
  { key: 'scale', icon: Maximize, label: 'Scale' },
];

const CAPTURE_MODES = [
  { key: 'all', label: 'All maps', hint: 'Depth + Normal + Segmentation' },
  { key: 'depth', label: 'Depth only', hint: 'Just the depth map' },
];

let blockoutCounter = 0;

export function StageToolbar() {
  const setBlockout = useStagingStore((s) => s.setBlockout);
  const blockout = useStagingStore((s) => s.blockout);
  const placements = useStagingStore((s) => s.placements);
  const selection = useStagingStore((s) => s.selection);
  const setSelection = useStagingStore((s) => s.setSelection);
  const removePlacement = useStagingStore((s) => s.removePlacement);
  const removeBlockout = useStagingStore((s) => s.removeBlockout);
  const transformMode = useStagingStore((s) => s.transformMode);
  const setTransformMode = useStagingStore((s) => s.setTransformMode);
  const isCapturing = useStagingStore((s) => s.isCapturing);
  const captureFn = useStagingStore((s) => s.captureFn);
  const fastMode = useStagingStore((s) => s.fastMode);
  const toggleFastMode = useStagingStore((s) => s.toggleFastMode);
  const captureMode = useStagingStore((s) => s.captureMode);
  const setCaptureMode = useStagingStore((s) => s.setCaptureMode);
  const undo = useStagingStore((s) => s.undo);
  const redo = useStagingStore((s) => s.redo);
  const canUndo = useStagingStore((s) => s.past.length > 0);
  const canRedo = useStagingStore((s) => s.future.length > 0);

  const deleteSelected = () => {
    if (!selection) return;
    if (blockout.some((b) => b.id === selection)) removeBlockout(selection);
    else if (placements.some((p) => p.id === selection)) removePlacement(selection);
    setSelection(null);
  };

  const addBlockout = (kind) => {
    blockoutCounter += 1;
    const id = `blockout-${blockoutCounter}`;
    const newBlockout = {
      id,
      kind,
      transform: { pos: [0, 0.5, 0], rot: [0, 0, 0], scale: [1, 1, 1] },
      label: kind,
    };
    setBlockout([...blockout, newBlockout]);
    setSelection(id);
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        size="xs"
        variant="ghost"
        onClick={undo}
        disabled={!canUndo}
        className="text-fg-muted hover:text-fg disabled:opacity-30"
        title="Undo (Ctrl+Z)"
      >
        <Undo2 className="w-3.5 h-3.5" />
      </Button>
      <Button
        size="xs"
        variant="ghost"
        onClick={redo}
        disabled={!canRedo}
        className="text-fg-muted hover:text-fg disabled:opacity-30"
        title="Redo (Ctrl+Shift+Z)"
      >
        <Redo2 className="w-3.5 h-3.5" />
      </Button>
      <div className="w-px h-5 bg-bay-700 mx-1" />
      <Button
        size="xs"
        variant="outline"
        onClick={() => addBlockout('floor')}
        className="border-line text-fg hover:text-fg"
        title="Add floor"
      >
        <Grid className="w-3.5 h-3.5" />
      </Button>
      <Button
        size="xs"
        variant="outline"
        onClick={() => addBlockout('box')}
        className="border-line text-fg hover:text-fg"
        title="Add box"
      >
        <Box className="w-3.5 h-3.5" />
      </Button>
      <Button
        size="xs"
        variant="outline"
        onClick={() => addBlockout('plane')}
        className="border-line text-fg hover:text-fg"
        title="Add plane"
      >
        <Square className="w-3.5 h-3.5" />
      </Button>

      {selection && (
        <>
          <div className="w-px h-5 bg-bay-700 mx-1" />
          <Button
            size="xs"
            variant="ghost"
            onClick={deleteSelected}
            className="text-stop hover:text-stop hover:bg-stop/15"
            title="Delete selected"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
          <div className="w-px h-5 bg-bay-700 mx-1" />
          {MODES.map(({ key, icon: Icon, label }) => (
            <Button
              key={key}
              size="xs"
              variant={transformMode === key ? 'default' : 'ghost'}
              onClick={() => setTransformMode(key)}
              className={
                transformMode === key
                  ? 'bg-lead-500 text-bay-950'
                  : 'text-fg-muted hover:text-fg'
              }
              title={label}
            >
              <Icon className="w-3.5 h-3.5" />
            </Button>
          ))}
        </>
      )}

      <Button
        size="xs"
        variant={fastMode ? 'default' : 'ghost'}
        onClick={toggleFastMode}
        className={fastMode ? 'bg-lead-500 text-black hover:bg-lead-500' : 'text-fg-muted hover:text-fg'}
        title="Fast movement for WASD controls (toggle with Shift)"
      >
        <Zap className="w-3.5 h-3.5" />
      </Button>

      <div className="w-px h-5 bg-bay-700 mx-1" />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-line text-fg hover:text-fg"
            title="Which maps Capture produces (color frame is always included)"
          >
            <Layers className="w-3.5 h-3.5 mr-1" />
            {CAPTURE_MODES.find((m) => m.key === captureMode)?.label ?? 'All maps'}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="bg-bay-850 border-line min-w-[13rem]"
        >
          {CAPTURE_MODES.map((mode) => (
            <DropdownMenuItem
              key={mode.key}
              onSelect={() => setCaptureMode(mode.key)}
              className="text-fg focus:bg-lead-500/40 focus:text-bay-950 gap-2"
            >
              <div className="flex-1">
                <p className="text-xs">{mode.label}</p>
                <p className="text-[10px] text-fg-muted">{mode.hint}</p>
              </div>
              {captureMode === mode.key && <span className="text-lead-500">●</span>}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        size="sm"
        onClick={() => captureFn?.()}
        disabled={isCapturing || !captureFn}
        className="bg-lead-500 text-bay-950 hover:bg-lead-400"
      >
        {isCapturing ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
        ) : (
          <Camera className="w-3.5 h-3.5 mr-1" />
        )}
        Capture
      </Button>
    </div>
  );
}
