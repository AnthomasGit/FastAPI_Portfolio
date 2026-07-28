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
          className="border-white/10 text-slate-300 hover:text-white"
          title="Choose a backdrop image"
        >
          <Image className="w-3.5 h-3.5 mr-1" />
          Backdrop
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="center"
        className="bg-slate-900 border-white/10 min-w-[16rem]"
      >
        <DropdownMenuItem
          disabled={!backdropReferenceId}
          onSelect={() => setBackdropReferenceId(null)}
          className="text-slate-300 focus:bg-white/10 focus:text-white gap-2"
        >
          <X className="w-3.5 h-3.5" />
          None
        </DropdownMenuItem>

        {sceneLocations.length === 0 ? (
          <DropdownMenuItem disabled className="text-slate-500 text-xs">
            Link a location to this scene first
          </DropdownMenuItem>
        ) : isLoading ? (
          <DropdownMenuItem disabled className="text-slate-500 text-xs">
            Loading references...
          </DropdownMenuItem>
        ) : references.length === 0 ? (
          <DropdownMenuItem disabled className="text-slate-500 text-xs">
            No reference images on linked locations
          </DropdownMenuItem>
        ) : (
          <>
            <DropdownMenuSeparator className="bg-white/10" />
            {references.map((ref) => (
              <DropdownMenuItem
                key={ref.id}
                onSelect={() => setBackdropReferenceId(ref.id)}
                className="text-slate-200 focus:bg-cyan-500/10 focus:text-cyan-200 gap-2"
                title="Use as backdrop"
              >
                <img
                  src={api.getReferenceFileUrl(ref)}
                  alt=""
                  className="w-8 h-8 rounded object-cover border border-white/10 shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs truncate">
                    {ref.locationName}
                    {backdropReferenceId === ref.id && (
                      <span className="text-cyan-400 ml-1.5">(active)</span>
                    )}
                  </p>
                  <p className="text-[10px] text-slate-500 truncate">{ref.role}</p>
                </div>
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
