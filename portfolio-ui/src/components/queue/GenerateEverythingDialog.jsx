import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, ListPlus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { api } from '../../lib/api';

// run_after presets map to the backend's parse_run_after vocabulary.
const START_OPTIONS = [
  { value: 'now', label: 'Now' },
  { value: 'tonight', label: 'Tonight (23:00)' },
  { value: '+4h', label: 'In 4 hours' },
];

export function GenerateEverythingDialog({ projectId, open, onOpenChange, onCreated }) {
  const queryClient = useQueryClient();
  const [variants, setVariants] = useState('1');
  const [start, setStart] = useState('now');

  const create = useMutation({
    mutationFn: () =>
      api.createBatch({
        project_id: projectId,
        scope: 'project',
        kind: 'scene_image',
        variants: Number(variants),
        seed_policy: 'random',
        run_after: start === 'now' ? null : start,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] });
      onOpenChange(false);
      onCreated?.(data);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Generate everything</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-fg-muted -mt-1">
          Queues one still per scene in this project as a single batch. The
          worker renders them in the background — you can close the tab.
        </p>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <label className="block">
            <span className="label-slug block mb-1.5">Variants / scene</span>
            <Select value={variants} onValueChange={setVariants}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {['1', '2', '3', '4'].map((v) => (
                  <SelectItem key={v} value={v}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          <label className="block">
            <span className="label-slug block mb-1.5">Start</span>
            <Select value={start} onValueChange={setStart}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {START_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>

        {create.isError && (
          <p role="alert" className="mt-3 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
            Couldn’t queue: {create.error?.message || 'unknown error'}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ListPlus className="w-3.5 h-3.5" />}
            Queue batch
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
