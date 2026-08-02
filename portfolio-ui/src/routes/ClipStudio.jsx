import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Film, Loader2 } from 'lucide-react';

import { api } from '../lib/api';
import { shotToMotionPrompt, shotToGlobalPrompt } from '../components/scene/shotPrompt';
import { allClips, clipState, shotRequirements, shotReadiness } from '../components/scene/shotReadiness';
import { PipelineStepper } from '../components/clip/PipelineStepper';
import { buildPipelineSteps } from '../components/clip/pipelineSteps';
import { WorkflowCards } from '../components/clip/WorkflowCards';
import { ReferenceSlots } from '../components/clip/ReferenceSlots';
import { sceneCandidates } from '../components/clip/referenceCandidates';
import { ReadinessChecklist } from '../components/clip/ReadinessChecklist';
import { ClipResults } from '../components/clip/ClipResults';
import { MilestoneToast } from '../components/clip/MilestoneToast';
import { claimMilestone } from '../components/clip/milestones';

// Clip Studio — the full-page generator behind the shot list's "Generate clip".
//
// Hub-and-spoke rather than a wizard: the pipeline that leads here has a
// genuinely optional middle (3D staging), and a wizard would either force it or
// hide it. The stepper reports where the shot stands; everything on the page
// stays reachable regardless of which upstream stages were used.

export function ClipStudio() {
  const { id: projectId, sceneId, shotId } = useParams();
  const queryClient = useQueryClient();

  const { data: scene } = useQuery({
    queryKey: ['scene', sceneId],
    queryFn: () => api.getScene(sceneId),
  });
  const { data: shots = [] } = useQuery({
    queryKey: ['shots', sceneId],
    queryFn: () => api.listShots(sceneId),
  });
  const { data: workflows = [] } = useQuery({
    queryKey: ['video-workflows'],
    queryFn: () => api.listVideoWorkflows(),
  });
  const { data: captures = [] } = useQuery({
    queryKey: ['captures', sceneId],
    queryFn: () => api.listCaptures(sceneId),
  });

  const shot = shots.find((s) => s.id === shotId);

  const [workflowId, setWorkflowId] = useState(null);
  const [subjectKeys, setSubjectKeys] = useState([]);
  const [backgroundKey, setBackgroundKey] = useState(null);
  const [prompts, setPrompts] = useState({ global: null, local: null });
  const [settings, setSettings] = useState({
    width: 544, height: 960, fps: 25, duration: 5, reference_frame_count: 17,
  });
  const [milestone, setMilestone] = useState(null);

  // Default to the backend's recommended workflow once the registry lands.
  const selectedWorkflow =
    workflows.find((w) => w.id === workflowId) ||
    workflows.find((w) => w.recommended) ||
    workflows[0];

  const { subjects, locations } = useMemo(() => sceneCandidates(scene), [scene]);

  // Prompts start auto-composed from the shot and stay that way until edited,
  // so changes to size/angle/description upstream keep flowing through.
  const autoLocal = shotToMotionPrompt(shot);
  const autoGlobal = useMemo(() => {
    const chosen = subjectKeys.map((k) => subjects.find((s) => s.key === k)).filter(Boolean);
    const bg = locations.find((l) => l.key === backgroundKey) || null;
    return shotToGlobalPrompt(chosen, bg);
  }, [subjectKeys, backgroundKey, subjects, locations]);

  const localPrompt = prompts.local ?? autoLocal;
  const globalPrompt = prompts.global ?? autoGlobal;

  const clips = allClips(shot);
  const inflight = clips.some((c) => c.status === 'queued' || c.status === 'processing');

  const requirements = useMemo(() => {
    const base = shotRequirements(shot);
    if (!selectedWorkflow) return base;
    const extra = [];
    if (selectedWorkflow.needs_still) {
      extra.push({ key: 'still', label: 'Beauty-pass still attached', met: Boolean(shot?.still), required: true });
    }
    if (selectedWorkflow.max_refs) {
      extra.push({
        key: 'refs',
        label: `At least one reference (${subjectKeys.length}/${selectedWorkflow.max_refs} chosen)`,
        met: subjectKeys.length > 0,
        required: true,
      });
    }
    if (selectedWorkflow.background) {
      extra.push({ key: 'bg', label: 'Background plate', met: Boolean(backgroundKey), required: false });
    }
    return [...base, ...extra];
  }, [shot, selectedWorkflow, subjectKeys, backgroundKey]);

  const blocking = requirements.filter((r) => r.required && !r.met);
  const canGenerate = selectedWorkflow && blocking.length === 0 && !inflight;

  const generateMut = useMutation({
    mutationFn: () => {
      const refIds = subjectKeys
        .map((k) => subjects.find((s) => s.key === k)?.referenceId)
        .filter(Boolean);
      const bg = locations.find((l) => l.key === backgroundKey);
      return api.generateClip({
        workflow: selectedWorkflow.id,
        shotId,
        imageId: selectedWorkflow.needs_still ? shot?.still?.id : null,
        referenceIds: refIds,
        backgroundReferenceId: bg?.referenceId || null,
        motionPrompt: localPrompt,
        globalPrompt: selectedWorkflow.dual_prompt ? globalPrompt : null,
        localPrompts: selectedWorkflow.dual_prompt ? localPrompt : null,
        params: { ...settings },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shots', sceneId] });
    },
  });

  const handleClipCompleted = () => {
    const others = shots.filter((s) => s.id !== shotId);
    const everyOtherDone = others.every((s) => clipState(s) === 'done');
    setMilestone(
      claimMilestone({
        firstClipEver: true,
        sceneComplete: everyOtherDone && shots.length > 1
          ? { sceneId, number: scene?.scene_number, total: shots.length }
          : null,
      })
    );
  };

  if (!shot) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <p className="text-sm text-slate-500">Loading shot…</p>
      </div>
    );
  }

  const readiness = shotReadiness(shot);
  const steps = buildPipelineSteps({
    scene,
    shot,
    hasCapture: captures.length > 0,
    clipState: clipState(shot),
  });

  const toggleSubject = (key) =>
    setSubjectKeys((keys) =>
      keys.includes(key)
        ? keys.filter((k) => k !== key)
        : keys.length < (selectedWorkflow?.max_refs || 0)
          ? [...keys, key]
          : keys
    );

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
      <MilestoneToast milestone={milestone} onDismiss={() => setMilestone(null)} />

      <div className="flex items-center gap-3">
        <Link
          to={`/project/${projectId}/scene/${sceneId}`}
          className="text-slate-500 hover:text-slate-200 transition-colors"
          aria-label="Back to scene"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-slate-100 truncate">
            Shot {shot.shot_number || '—'} · Clip Studio
          </h1>
          <p className="text-[11px] text-slate-500 truncate">
            {[shot.shot_size, shot.angle, shot.movement].filter(Boolean).join(' · ') ||
              'No coverage metadata set'}
          </p>
        </div>
        <span className={`ml-auto text-[10px] font-medium px-2 py-0.5 rounded-full ${readiness.cls}`}>
          {readiness.label}
        </span>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
        <PipelineStepper steps={steps} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-5 min-w-0">
          <section>
            <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
              1 · Workflow
            </h2>
            <WorkflowCards
              workflows={workflows}
              selected={selectedWorkflow?.id}
              onSelect={setWorkflowId}
              disabledReason={(wf) =>
                wf.needs_still && !shot.still ? 'Needs a beauty-pass still' : null
              }
            />
          </section>

          {selectedWorkflow?.max_refs > 0 && (
            <section>
              <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                2 · References
              </h2>
              <ReferenceSlots
                scene={scene}
                maxRefs={selectedWorkflow.max_refs}
                allowBackground={selectedWorkflow.background}
                selectedKeys={subjectKeys}
                onToggleSubject={toggleSubject}
                backgroundKey={backgroundKey}
                onSelectBackground={setBackgroundKey}
              />
            </section>
          )}

          <section className="space-y-3">
            <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
              {selectedWorkflow?.max_refs > 0 ? '3' : '2'} · Prompt
            </h2>
            {selectedWorkflow?.dual_prompt && (
              <div>
                <label className="block text-[10px] text-slate-500 mb-1">
                  Identities — who each reference is (auto-composed from your selection)
                </label>
                <textarea
                  value={globalPrompt}
                  onChange={(e) => setPrompts((p) => ({ ...p, global: e.target.value }))}
                  rows={4}
                  className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1.5 text-slate-200 resize-y focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
                />
              </div>
            )}
            <div>
              <label className="block text-[10px] text-slate-500 mb-1">
                {selectedWorkflow?.dual_prompt
                  ? 'Action & dialogue — what happens in the shot'
                  : 'Motion prompt — prefilled from this shot’s coverage metadata'}
              </label>
              <textarea
                value={localPrompt}
                onChange={(e) => setPrompts((p) => ({ ...p, local: e.target.value }))}
                rows={selectedWorkflow?.dual_prompt ? 7 : 5}
                className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1.5 text-slate-200 resize-y focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
              />
            </div>
          </section>

          <details className="rounded-lg border border-white/10 bg-black/30">
            <summary className="px-3 py-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
              Settings
            </summary>
            <div className="grid grid-cols-4 gap-2 px-3 pb-3">
              {['width', 'height', 'fps', 'duration'].map((k) => (
                <label key={k} className="block">
                  <span className="block text-[9px] text-slate-500 capitalize mb-0.5">
                    {k === 'duration' ? 'seconds' : k}
                  </span>
                  <input
                    type="number"
                    value={settings[k]}
                    onChange={(e) =>
                      setSettings((s) => ({ ...s, [k]: Number(e.target.value) || s[k] }))
                    }
                    className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
                  />
                </label>
              ))}
            </div>
            <p className="text-[9px] text-slate-600 px-3 pb-3">
              Width rounds to a multiple of 32 in latent space; the x2 upscaler doubles the output.
              Clip length is fps × seconds, and drives generation time more than resolution does.
            </p>

            {selectedWorkflow?.reference_frame_count && (
              <div className="px-3 pb-3 border-t border-white/5 pt-3">
                <label className="block w-28">
                  <span className="block text-[9px] text-slate-500 mb-0.5">Reference frames</span>
                  <input
                    type="number"
                    min={1}
                    value={settings.reference_frame_count}
                    onChange={(e) =>
                      setSettings((s) => ({
                        ...s,
                        reference_frame_count: Number(e.target.value) || s.reference_frame_count,
                      }))
                    }
                    className="w-full text-[11px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-fuchsia-400"
                  />
                </label>
                <p className="text-[9px] text-slate-600 mt-1.5">
                  Higher improves identity/detail retention, but needs more GPU memory.
                </p>
              </div>
            )}
          </details>

          <div className="space-y-2">
            <ReadinessChecklist items={requirements} />
            <button
              type="button"
              onClick={() => generateMut.mutate()}
              disabled={!canGenerate || generateMut.isPending}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-fuchsia-400"
            >
              {generateMut.isPending || inflight ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
              ) : (
                <Film className="w-3.5 h-3.5" />
              )}
              {inflight ? 'Generating…' : clips.length ? 'Generate another clip' : 'Generate clip'}
            </button>
            {generateMut.isError && (
              <p className="text-[10px] text-red-400/80 break-words">
                {generateMut.error?.message}
              </p>
            )}
          </div>
        </div>

        <aside className="space-y-2 min-w-0">
          <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Results
          </h2>
          <ClipResults
            clips={clips}
            sceneId={sceneId}
            shotId={shotId}
            onClipCompleted={handleClipCompleted}
          />
        </aside>
      </div>
    </div>
  );
}
