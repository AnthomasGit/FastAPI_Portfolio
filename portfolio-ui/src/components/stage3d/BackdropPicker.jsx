import { Image, X } from 'lucide-react';
import { api } from '@/lib/api';
import { useStagingStore } from '@/stores/stagingStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { useLocationReferences } from './useLocationReferences';

export function BackdropPicker({ sceneLocations }) {
  const backdropReferenceId = useStagingStore((s) => s.backdropReferenceId);
  const setBackdropReferenceId = useStagingStore((s) => s.setBackdropReferenceId);
  const { references, isLoading } = useLocationReferences(sceneLocations);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="xs"
          variant="outline"
          className="border-line text-fg hover:text-fg"
          title="Choose a backdrop image"
        >
          <Image className="w-3.5 h-3.5 mr-1" />
          Backdrop
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="center"
        className="bg-bay-850 border-line min-w-[16rem]"
      >
        <DropdownMenuItem
          disabled={!backdropReferenceId}
          onSelect={() => setBackdropReferenceId(null)}
          className="text-fg focus:bg-bay-700 focus:text-fg gap-2"
        >
          <X className="w-3.5 h-3.5" />
          None
        </DropdownMenuItem>

        {sceneLocations.length === 0 ? (
          <DropdownMenuItem disabled className="text-fg-muted text-xs">
            Link a location to this scene first
          </DropdownMenuItem>
        ) : isLoading ? (
          <DropdownMenuItem disabled className="text-fg-muted text-xs">
            Loading references...
          </DropdownMenuItem>
        ) : references.length === 0 ? (
          <DropdownMenuItem disabled className="text-fg-muted text-xs">
            No reference images on linked locations
          </DropdownMenuItem>
        ) : (
          <>
            <DropdownMenuSeparator className="bg-bay-700" />
            {references.map((ref) => (
              <DropdownMenuItem
                key={ref.id}
                onSelect={() => setBackdropReferenceId(ref.id)}
                className="text-fg focus:bg-lead-500/40 focus:text-bay-950 gap-2"
                title="Use as backdrop"
              >
                <img
                  src={api.getReferenceFileUrl(ref)}
                  alt=""
                  className="w-8 h-8 rounded object-cover border border-line shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs truncate">
                    {ref.locationName}
                    {backdropReferenceId === ref.id && (
                      <span className="text-lead-500 ml-1.5">(active)</span>
                    )}
                  </p>
                  <p className="text-[10px] text-fg-muted truncate">{ref.role}</p>
                </div>
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
