import { useEffect } from 'react';
import { Aperture, Frame, Crosshair, Video } from 'lucide-react';
import { useStagingStore } from '@/stores/stagingStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { FOCAL_LENGTHS, FORMATS, getFormat } from './cameraFormats';

export function ShotControls() {
  const camera = useStagingStore((s) => s.camera);
  const navPose = useStagingStore((s) => s.navPose);
  const updateShotCamera = useStagingStore((s) => s.updateShotCamera);
  const pilotMode = useStagingStore((s) => s.pilotMode);
  const setPilotMode = useStagingStore((s) => s.setPilotMode);

  // Seed a default shot on scenes that have none yet, matching the initial
  // viewport pose so the preview isn't empty on first open.
  useEffect(() => {
    if (!camera) {
      updateShotCamera({ position: [5, 5, 5], target: [0, 0, 0] });
    }
  }, [camera, updateShotCamera]);

  const focal = camera?.focal_length ?? 35;
  const fmt = getFormat(camera?.format);

  const setShotFromView = () => {
    if (!navPose) return;
    updateShotCamera({ position: navPose.position, target: navPose.target });
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs font-semibold text-fg-muted uppercase tracking-wider">
        Shot:
      </span>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-line text-fg hover:text-fg tabular-nums"
            title="Focal length"
          >
            <Aperture className="w-3.5 h-3.5 mr-1" />
            {focal}mm
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="center" className="bg-bay-850 border-line min-w-[8rem]">
          {FOCAL_LENGTHS.map((mm) => (
            <DropdownMenuItem
              key={mm}
              onSelect={() => updateShotCamera({ focal_length: mm })}
              className="text-fg focus:bg-lead-500/40 focus:text-bay-950 tabular-nums"
            >
              {mm}mm
              {focal === mm && <span className="text-lead-500 ml-auto">●</span>}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-line text-fg hover:text-fg"
            title="Output format"
          >
            <Frame className="w-3.5 h-3.5 mr-1" />
            {fmt.id}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="center" className="bg-bay-850 border-line min-w-[12rem]">
          {FORMATS.map((f) => (
            <DropdownMenuItem
              key={f.id}
              onSelect={() => updateShotCamera({ format: f.id })}
              className="text-fg focus:bg-lead-500/40 focus:text-bay-950"
            >
              {f.label}
              {fmt.id === f.id && <span className="text-lead-500 ml-auto">●</span>}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        size="xs"
        variant="outline"
        onClick={setShotFromView}
        disabled={!navPose || pilotMode}
        className="border-line text-fg hover:text-fg"
        title="Move the shot camera to your current view"
      >
        <Crosshair className="w-3.5 h-3.5 mr-1" />
        Set from view
      </Button>

      <Button
        size="xs"
        variant={pilotMode ? 'default' : 'outline'}
        onClick={() => setPilotMode(!pilotMode)}
        className={
          pilotMode
            ? 'bg-lead-500 text-bay-950 hover:bg-lead-400'
            : 'border-line text-fg hover:text-fg'
        }
        title={pilotMode ? 'Exit pilot mode (Esc)' : 'Fly the shot camera through the lens'}
      >
        <Video className="w-3.5 h-3.5 mr-1" />
        Pilot
      </Button>
    </div>
  );
}
