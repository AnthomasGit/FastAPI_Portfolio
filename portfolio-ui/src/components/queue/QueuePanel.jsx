import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, Loader2, XCircle, RotateCcw, ListPlus, Clock } from 'lucide-react';
import { api } from '@/lib/api';
import { GenerateEverythingDialog } from './GenerateEverythingDialog';

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

const STATUS_STYLES = {
  pending: 'bg-bay-700 text-fg-muted',
  scheduled: 'bg-lead-500/15 text-lead-400',
  running: 'bg-set/15 text-set',
  completed: 'bg-ok/15 text-cast',
  failed: 'bg-stop/15 text-stop',
  cancelled: 'bg-bay-700 text-fg-faint',
};

const JOB_STATUS_STYLES = {
  queued: 'bg-bay-700 text-fg-muted',
  running: 'bg-set/15 text-set',
  completed: 'bg-ok/15 text-cast',
  failed: 'bg-stop/15 text-stop',
  cancelled: 'bg-bay-700 text-fg-faint',
};

function StatusChip({ status, styles = STATUS_STYLES }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${styles[status] || 'bg-bay-700 text-fg'}`}>
      {status}
    </span>
  );
}

function ProgressBar({ counts }) {
  const total = counts.total || 1;
  const pct = (n) => `${(n / total) * 100}%`;
  return (
    <div className="h-1.5 w-full flex overflow-hidden rounded-full bg-bay-900">
      <div className="bg-ok/80" style={{ width: pct(counts.completed) }} />
      <div className="bg-set/70" style={{ width: pct(counts.running) }} />
      <div className="bg-stop/70" style={{ width: pct(counts.failed) }} />
      <div className="bg-bay-600" style={{ width: pct(counts.cancelled) }} />
    </div>
  );
}

function fmtTime(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// Expanded detail: per-job status + error text, polled while non-terminal.
function BatchJobs({ batchId, batchStatus }) {
  const { data } = useQuery({
    queryKey: ['batch', batchId],
    queryFn: () => api.getBatch(batchId),
    refetchInterval: () => (TERMINAL.has(batchStatus) ? false : 2000),
  });
  const jobs = data?.jobs || [];
  if (!jobs.length) return <p className="px-4 py-3 text-xs text-fg-faint">No jobs.</p>;
  return (
    <ul className="divide-y divide-line">
      {jobs.map((j) => (
        <li key={j.job_id} className="flex items-start gap-2 px-4 py-2">
          <StatusChip status={j.status} styles={JOB_STATUS_STYLES} />
          <span className="font-mono text-[11px] text-fg-muted">{j.kind}</span>
          {j.status === 'failed' && j.error && (
            <span className="text-[11px] text-stop truncate" title={j.error}>{j.error}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function BatchRow({ batch, projectId }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] });
    queryClient.invalidateQueries({ queryKey: ['batch', batch.id] });
  };
  const cancel = useMutation({ mutationFn: () => api.cancelBatch(batch.id), onSuccess: refresh });
  const retry = useMutation({ mutationFn: () => api.retryFailedBatch(batch.id), onSuccess: refresh });

  const c = batch.counts;
  const canCancel = !TERMINAL.has(batch.status);
  const canRetry = c.failed > 0;

  return (
    <div className="rounded-frame border border-line bg-bay-850">
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-fg-faint hover:text-fg transition-colors"
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          <ChevronRight className={`w-4 h-4 transition-transform ${open ? 'rotate-90' : ''}`} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-bold text-fg truncate">
              {batch.name || batch.kind || 'Batch'}
            </span>
            <StatusChip status={batch.status} />
            {batch.run_after && batch.status === 'scheduled' && (
              <span className="flex items-center gap-1 text-[10px] text-lead-400">
                <Clock className="w-3 h-3" /> {fmtTime(batch.run_after)}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <ProgressBar counts={c} />
            <span className="font-mono text-[10px] text-fg-faint whitespace-nowrap">
              {c.completed}/{c.total}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {canRetry && (
            <button
              onClick={() => retry.mutate()}
              disabled={retry.isPending}
              className="flex items-center gap-1 px-2 py-1 rounded-frame border border-line text-[11px] text-fg-muted hover:text-fg hover:bg-bay-800 transition-colors"
              title="Requeue failed jobs"
            >
              {retry.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
              Retry
            </button>
          )}
          {canCancel && (
            <button
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
              className="flex items-center gap-1 px-2 py-1 rounded-frame border border-stop/40 text-[11px] text-stop hover:bg-stop/10 transition-colors"
              title="Cancel remaining jobs"
            >
              {cancel.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
              Cancel
            </button>
          )}
        </div>
      </div>
      {open && (
        <div className="border-t border-line bg-bay-900/40">
          <BatchJobs batchId={batch.id} batchStatus={batch.status} />
        </div>
      )}
    </div>
  );
}

export function QueuePanel({ projectId }) {
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: batches = [], isLoading } = useQuery({
    queryKey: ['project-batches', projectId],
    queryFn: () => api.listProjectBatches(projectId),
    // Poll while any batch is still working; stop once all are terminal.
    refetchInterval: (query) => {
      const list = query.state.data || [];
      return list.some((b) => !TERMINAL.has(b.status)) ? 2000 : false;
    },
  });

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <p className="label-slug">Render queue</p>
        <button
          onClick={() => setDialogOpen(true)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors"
        >
          <ListPlus className="w-3.5 h-3.5" /> Generate everything…
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center p-8">
          <Loader2 className="w-5 h-5 animate-spin text-lead-500" />
        </div>
      ) : batches.length === 0 ? (
        <p className="text-xs text-fg-faint">
          No batches yet. Use “Generate everything…” to queue a run.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {batches.map((b) => (
            <BatchRow key={b.id} batch={b} projectId={projectId} />
          ))}
        </div>
      )}

      <GenerateEverythingDialog
        projectId={projectId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </section>
  );
}
