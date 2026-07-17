import { Button } from '@/components/ui/button';
import { Camera, Box, Square, Grid, Loader2, X, Move, RotateCw, Maximize, Zap, Layers } from 'lucide-react';
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
        variant="outline"
        onClick={() => addBlockout('floor')}
        className="border-white/10 text-slate-300 hover:text-white"
        title="Add floor"
      >
        <Grid className="w-3.5 h-3.5" />
      </Button>
      <Button
        size="xs"
        variant="outline"
        onClick={() => addBlockout('box')}
        className="border-white/10 text-slate-300 hover:text-white"
        title="Add box"
      >
        <Box className="w-3.5 h-3.5" />
      </Button>
      <Button
        size="xs"
        variant="outline"
        onClick={() => addBlockout('plane')}
        className="border-white/10 text-slate-300 hover:text-white"
        title="Add plane"
      >
        <Square className="w-3.5 h-3.5" />
      </Button>

      {selection && (
        <>
          <div className="w-px h-5 bg-white/10 mx-1" />
          <Button
            size="xs"
            variant="ghost"
            onClick={deleteSelected}
            className="text-rose-400 hover:text-rose-300 hover:bg-rose-400/10"
            title="Delete selected"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
          <div className="w-px h-5 bg-white/10 mx-1" />
          {MODES.map(({ key, icon: Icon, label }) => (
            <Button
              key={key}
              size="xs"
              variant={transformMode === key ? 'default' : 'ghost'}
              onClick={() => setTransformMode(key)}
              className={
                transformMode === key
                  ? 'bg-cyan-600 text-white'
                  : 'text-slate-400 hover:text-white'
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
        className={fastMode ? 'bg-amber-500 text-black hover:bg-amber-400' : 'text-slate-400 hover:text-white'}
        title="Fast movement for WASD controls (toggle with Shift)"
      >
        <Zap className="w-3.5 h-3.5" />
      </Button>

      <div className="w-px h-5 bg-white/10 mx-1" />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-white/10 text-slate-300 hover:text-white"
            title="Which maps Capture produces (color frame is always included)"
          >
            <Layers className="w-3.5 h-3.5 mr-1" />
            {CAPTURE_MODES.find((m) => m.key === captureMode)?.label ?? 'All maps'}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="bg-slate-900 border-white/10 min-w-[13rem]"
        >
          {CAPTURE_MODES.map((mode) => (
            <DropdownMenuItem
              key={mode.key}
              onSelect={() => setCaptureMode(mode.key)}
              className="text-slate-200 focus:bg-cyan-500/10 focus:text-cyan-200 gap-2"
            >
              <div className="flex-1">
                <p className="text-xs">{mode.label}</p>
                <p className="text-[10px] text-slate-500">{mode.hint}</p>
              </div>
              {captureMode === mode.key && <span className="text-cyan-400">●</span>}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        size="sm"
        onClick={() => captureFn?.()}
        disabled={isCapturing || !captureFn}
        className="bg-gradient-to-r from-rose-600 to-purple-600 text-white hover:from-rose-500 hover:to-purple-500"
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
