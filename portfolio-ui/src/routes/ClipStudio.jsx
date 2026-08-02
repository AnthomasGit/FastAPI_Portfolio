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
import { DrivingVideoPicker } from '../components/clip/DrivingVideoPicker';
import { WorkflowSettings } from '../components/clip/WorkflowSettings';
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
  const [drivingVideoId, setDrivingVideoId] = useState(null);
  const [prompts, setPrompts] = useState({ global: null, local: null });
  // Keyed by setting id, sparse — only entries the user has touched. Effective
  // values (settingsValues below) fall back to each spec's own default, so
  // switching workflows never shows a stale value from a different graph.
  const [settings, setSettings] = useState({});
  const [milestone, setMilestone] = useState(null);

  // Default to the backend's recommended workflow once the registry lands.
  const selectedWorkflow =
    workflows.find((w) => w.id === workflowId) ||
    workflows.find((w) => w.recommended) ||
    workflows[0];

  const settingSpecs = useMemo(() => selectedWorkflow?.settings || [], [selectedWorkflow]);
  const settingsValues = useMemo(
    () => Object.fromEntries(settingSpecs.map((s) => [s.id, settings[s.id] ?? s.default])),
    [settingSpecs, settings]
  );

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
      const label = selectedWorkflow.max_refs === 1
        ? `A reference image (${subjectKeys.length}/1 chosen)`
        : `At least one reference (${subjectKeys.length}/${selectedWorkflow.max_refs} chosen)`;
      extra.push({ key: 'refs', label, met: subjectKeys.length > 0, required: true });
    }
    if (selectedWorkflow.background) {
      extra.push({ key: 'bg', label: 'Background plate', met: Boolean(backgroundKey), required: false });
    }
    if (selectedWorkflow.driving_video) {
      extra.push({
        key: 'driving_video',
        label: 'Driving video selected',
        met: Boolean(drivingVideoId),
        required: true,
      });
    }
    return [...base, ...extra];
  }, [shot, selectedWorkflow, subjectKeys, backgroundKey, drivingVideoId]);

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
        drivingVideoId: selectedWorkflow.driving_video ? drivingVideoId : null,
        motionPrompt: localPrompt,
        globalPrompt: selectedWorkflow.dual_prompt ? globalPrompt : null,
        localPrompts: selectedWorkflow.dual_prompt ? localPrompt : null,
        params: settingsValues,
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

  // Section numbers are derived, not hardcoded, so a workflow that skips
  // references (i2v) or adds a driving video (SCAIL-2) still reads 1, 2, 3...
  let sectionNum = 1;
  const workflowSectionNum = sectionNum++;
  const refsSectionNum = selectedWorkflow?.max_refs > 0 ? sectionNum++ : null;
  const drivingVideoSectionNum = selectedWorkflow?.driving_video ? sectionNum++ : null;
  const promptSectionNum = sectionNum;

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
              {workflowSectionNum} · Workflow
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

          {refsSectionNum && (
            <section>
              <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                {refsSectionNum} · References
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

          {drivingVideoSectionNum && (
            <section>
              <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                {drivingVideoSectionNum} · Motion source
              </h2>
              <DrivingVideoPicker
                projectId={projectId}
                selectedId={drivingVideoId}
                onSelect={setDrivingVideoId}
              />
              <p className="text-[9px] text-amber-400/70 mt-2">
                Needs a clearly visible person in both the reference image and this video — SAM3
                tracks both, and an untrackable one yields empty masks and a failed generation.
              </p>
            </section>
          )}

          <section className="space-y-3">
            <h2 className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
              {promptSectionNum} · Prompt
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

          {settingSpecs.length > 0 && (
            <details className="rounded-lg border border-white/10 bg-black/30">
              <summary className="px-3 py-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
                Settings
              </summary>
              {/* Rendered entirely from the registry's per-workflow spec — a new
                  workflow's knobs need no frontend change, just a backend spec. */}
              <WorkflowSettings
                specs={settingSpecs}
                values={settingsValues}
                onChange={(id, val) => setSettings((s) => ({ ...s, [id]: val }))}
              />
            </details>
          )}

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
