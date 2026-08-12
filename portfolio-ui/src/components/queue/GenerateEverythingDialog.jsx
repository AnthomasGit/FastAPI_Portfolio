import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, ListPlus, SlidersHorizontal, ChevronDown, AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { WorkflowParams } from '../workflow/WorkflowParams';
import { api } from '../../lib/api';

// run_after presets map to the backend's parse_run_after vocabulary.
const START_OPTIONS = [
  { value: 'now', label: 'Now' },
  { value: 'tonight', label: 'Tonight (23:00)' },
  { value: '+4h', label: 'In 4 hours' },
];

// What a batch renders. Shot clips are the default unit of work — coverage
// lives in each scene's shot list. Scene stills stay available but demoted.
const KINDS = [
  {
    value: 'shot_clip',
    label: 'Shot clips',
    registryKind: 'video',
    defaultWorkflow: 'minimax_h3_r2v',
    blurb: 'One reference-to-video clip per shot, across every scene. Each scene’s '
         + 'characters, locations and props are injected as references.',
  },
  {
    value: 'scene_image',
    label: 'Scene stills',
    registryKind: 'image',
    defaultWorkflow: null,
    graph: 'image_z_image_turbo',
    blurb: 'One still per scene. Useful for previz, but it does not cover the shot list.',
  },
];

export function GenerateEverythingDialog({ projectId, open, onOpenChange, onCreated }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState('shot_clip');
  const [workflowKey, setWorkflowKey] = useState(null);
  const [variants, setVariants] = useState('1');
  const [start, setStart] = useState('now');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [params, setParams] = useState({});
  const [openSelect, setOpenSelect] = useState(null);

  const cfg = KINDS.find((k) => k.value === kind);

  // One endpoint for both image and video graphs, so one renderer below.
  const { data: workflows = [] } = useQuery({
    queryKey: ['workflows', cfg.registryKind],
    queryFn: () => api.listWorkflows(cfg.registryKind).then((r) => r.workflows),
    enabled: open,
  });

  // Selectable entries are the ones a batch spec can actually name.
  const selectable = workflows.filter((w) => w.workflow_key);
  const selected =
    (cfg.graph ? workflows.find((w) => w.name === cfg.graph) : null) ||
    selectable.find((w) => w.workflow_key === workflowKey) ||
    selectable.find((w) => w.workflow_key === cfg.defaultWorkflow) ||
    selectable[0];

  // A batch builds one prompt per target server-side, so a single global prompt
  // override is meaningless here — offer only the non-prompt knobs.
  const editable = (selected?.params || []).filter(
    (p) => p.group === 'control' && p.type !== 'text',
  );

  const reset = () => { setParams({}); setShowAdvanced(false); setOpenSelect(null); };

  const create = useMutation({
    mutationFn: () =>
      api.createBatch({
        project_id: projectId,
        scope: 'project',
        kind,
        workflow: selected?.workflow_key ?? undefined,
        variants: Number(variants),
        seed_policy: 'random',
        run_after: start === 'now' ? null : start,
        params: Object.keys(params).length ? params : undefined,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] });
      onCreated?.(data);
      // The batch is queued either way, but preflight warnings are the whole
      // point of running preflight — stay open so they're actually read.
      if (!(data.warnings || []).length) onOpenChange(false);
    },
  });

  const warnings = create.data?.warnings || [];
  const queued = create.isSuccess;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Generate everything</DialogTitle>
        </DialogHeader>

        <label className="block mt-1">
          <span className="label-slug block mb-1.5">Render</span>
          <Select value={kind} onValueChange={(v) => { setKind(v); setWorkflowKey(null); reset(); }}
            modal={false} open={openSelect === 'kind'}
            onOpenChange={(v) => setOpenSelect(v ? 'kind' : null)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {KINDS.map((k) => (
                <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>

        <p className="text-xs text-fg-muted mt-2">{cfg.blurb}</p>

        {selectable.length > 1 && cfg.value === 'shot_clip' && (
          <label className="block mt-4">
            <span className="label-slug block mb-1.5">Workflow</span>
            <Select value={selected?.workflow_key ?? ''} onValueChange={setWorkflowKey}
              modal={false} open={openSelect === 'workflow'}
              onOpenChange={(v) => setOpenSelect(v ? 'workflow' : null)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {selectable.map((w) => (
                  <SelectItem key={w.workflow_key} value={w.workflow_key}>{w.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        )}

        <div className="mt-4 grid grid-cols-2 gap-4">
          <label className="block">
            <span className="label-slug block mb-1.5">
              {kind === 'shot_clip' ? 'Variants / shot' : 'Variants / scene'}
            </span>
            <Select value={variants} onValueChange={setVariants} modal={false}
              open={openSelect === 'variants'}
              onOpenChange={(v) => setOpenSelect(v ? 'variants' : null)}>
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
            <Select value={start} onValueChange={setStart} modal={false}
              open={openSelect === 'start'}
              onOpenChange={(v) => setOpenSelect(v ? 'start' : null)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {START_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>

        {editable.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            <button
              type="button"
              onClick={() => setShowAdvanced((s) => !s)}
              className="flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition-colors"
            >
              <SlidersHorizontal className="w-3 h-3" />
              Advanced parameters
              <ChevronDown className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
            </button>
            {showAdvanced && (
              <div className="mt-3">
                <WorkflowParams
                  params={editable}
                  values={params}
                  onChange={setParams}
                  openSelect={openSelect}
                  setOpenSelect={setOpenSelect}
                />
              </div>
            )}
          </div>
        )}

        {warnings.length > 0 && (
          <div className="mt-3 rounded-frame border border-lead-500/40 bg-lead-500/10 px-3 py-2">
            <p className="flex items-center gap-1.5 text-xs text-lead-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              {warnings.length} shot{warnings.length === 1 ? '' : 's'} queued without usable references
            </p>
            <p className="mt-1 text-[11px] text-fg-faint">
              {warnings.slice(0, 6).map((w) => w.shot_number || w.shot_id).join(', ')}
              {warnings.length > 6 ? '…' : ''} — give their characters, locations or props a primary image.
            </p>
          </div>
        )}

        {create.isError && (
          <p role="alert" className="mt-3 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
            Couldn’t queue: {create.error?.message || 'unknown error'}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {queued ? 'Close' : 'Cancel'}
          </Button>
          {!queued && (
            <Button onClick={() => create.mutate()} disabled={create.isPending}>
              {create.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ListPlus className="w-3.5 h-3.5" />}
              Queue batch
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
