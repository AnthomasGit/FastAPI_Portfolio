import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, ListPlus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { api } from '../../lib/api';
import { ASSET_BATCH_CONFIGS } from './assetBatchConfigs';

export function GenerateAssetsDialog({ tab, projectId, entities = [], open, onOpenChange }) {
  const cfg = ASSET_BATCH_CONFIGS[tab];
  const queryClient = useQueryClient();
  // null means "all of them" — derived rather than synced from an effect, so a
  // newly added entity is included without a re-sync.
  const [selected, setSelected] = useState(null);
  const [skipExisting, setSkipExisting] = useState(false);
  const [fromCanonical, setFromCanonical] = useState(true);
  const [withAngles, setWithAngles] = useState(true);
  const [openSelect, setOpenSelect] = useState(null);
  const [start, setStart] = useState('now');

  const isSelected = (id) => selected === null || selected.includes(id);
  const eligible = entities.filter(
    (e) => isSelected(e.id) && (!skipExisting || !e[cfg.primaryField]),
  );

  const create = useMutation({
    mutationFn: () =>
      api.createBatch({
        project_id: projectId,
        scope: 'entity',
        kind: cfg.kind,
        target_ids: eligible.map((e) => e.id),
        run_after: start === 'now' ? null : start,
        ...(cfg.baseImageToggle ? { from_canonical: fromCanonical } : {}),
        ...(cfg.baseImageToggle && !fromCanonical ? { workflow: cfg.workflow } : {}),
        ...(cfg.anglesToggle ? { with_angles: withAngles } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] });
      onOpenChange(false);
    },
  });

  const toggle = (id) =>
    setSelected((s) => {
      const base = s ?? entities.map((e) => e.id);
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    });

  const handleOpenChange = (v) => {
    if (!v) setSelected(null);   // reset on close, an event rather than an effect
    onOpenChange(v);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{cfg.title}</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-fg-muted -mt-1">{cfg.blurb}</p>

        <div className="mt-4">
          <span className="label-slug block mb-1.5">Include</span>
          <div className="max-h-44 overflow-y-auto rounded-frame border border-line bg-bay-900 divide-y divide-line">
            {entities.length === 0 && (
              <p className="px-3 py-2 text-xs text-fg-faint">Nothing to generate yet.</p>
            )}
            {entities.map((e) => {
              const has = !!e[cfg.primaryField];
              return (
                <label key={e.id}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs text-fg cursor-pointer hover:bg-bay-800">
                  <input type="checkbox" checked={isSelected(e.id)}
                    onChange={() => toggle(e.id)} className="accent-lead-500" />
                  <span className="flex-1 truncate">{e.name}</span>
                  {has && <span className="text-[10px] text-fg-faint">has art</span>}
                </label>
              );
            })}
          </div>
          <label className="mt-2 flex items-center gap-2 text-[11px] text-fg-muted cursor-pointer">
            <input type="checkbox" checked={skipExisting}
              onChange={(e) => setSkipExisting(e.target.checked)} className="accent-lead-500" />
            Skip ones that already have art
          </label>
        </div>

        {cfg.baseImageToggle && (
          <label className="mt-4 block">
            <span className="label-slug block mb-1.5">Base image</span>
            <Select value={fromCanonical ? 'canonical' : 'fresh'}
              onValueChange={(v) => setFromCanonical(v === 'canonical')}
              modal={false} open={openSelect === 'base'}
              onOpenChange={(v) => setOpenSelect(v ? 'base' : null)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="canonical">From primary image (keeps it consistent)</SelectItem>
                <SelectItem value="fresh">Fresh from prompt (Krea2)</SelectItem>
              </SelectContent>
            </Select>
            <span className="mt-1 block text-[10px] text-fg-faint">
              {fromCanonical
                ? 'Cells are edits of the entity’s primary image — this is what makes a sheet look like one subject.'
                : 'Cells are rendered from the prompt. Entities with no primary image always use this.'}
            </span>
          </label>
        )}

        {cfg.anglesToggle && (
          <label className="mt-4 flex items-center gap-2 text-xs text-fg cursor-pointer">
            <input type="checkbox" checked={withAngles}
              onChange={(e) => setWithAngles(e.target.checked)} className="accent-lead-500" />
            Also render the 360 angle set off each new plate
          </label>
        )}

        <label className="mt-4 block">
          <span className="label-slug block mb-1.5">Start</span>
          <Select value={start} onValueChange={setStart} modal={false}
            open={openSelect === 'start'}
            onOpenChange={(v) => setOpenSelect(v ? 'start' : null)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="now">Now</SelectItem>
              <SelectItem value="tonight">Tonight (23:00)</SelectItem>
              <SelectItem value="+4h">In 4 hours</SelectItem>
            </SelectContent>
          </Select>
        </label>

        {create.isError && (
          <p role="alert" className="mt-3 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
            Couldn’t queue: {create.error?.message || 'unknown error'}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between">
          <span className="text-[11px] text-fg-faint">
            {eligible.length} of {entities.length} selected
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()}
              disabled={create.isPending || eligible.length === 0}>
              {create.isPending
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <ListPlus className="w-3.5 h-3.5" />}
              Queue batch
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
