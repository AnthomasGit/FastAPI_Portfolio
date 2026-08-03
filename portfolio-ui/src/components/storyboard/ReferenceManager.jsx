import { useState, useEffect } from 'react';
import { Trash2, Wand2, Loader2, Plus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Button } from '../ui/button';
import { api } from '../../lib/api';

// No 'primary' — that's a per-scene concept (set on the Scene Detail page's
// asset picker), not a label on the reference itself. These are pool tags.
const ROLES = [
  'moodboard', 'turnaround_front', 'turnaround_side',
  'turnaround_back', 'texture_ref', 'backdrop', 'tpose',
];

export function ReferenceManager({ entityType, entityId, entityName, open, onOpenChange }) {
  const [references, setReferences] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  // Per-reference view switch: true = show cut-out, false = show original.
  // Undefined falls back to !!processed_url (cut-out shown by default once it exists).
  const [viewProcessed, setViewProcessed] = useState({});
  // Per-reference guard so a double-click can't fire a second remove/restore.
  const [bgBusy, setBgBusy] = useState({});

  const pluralType = entityType === 'scene' ? 'scenes' : `${entityType}s`;

  const fetchRefs = async () => {
    setLoading(true);
    try {
      const data = await api.listReferences(pluralType, entityId);
      setReferences(data);
    } catch (e) {
      console.error('Failed to load references', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchRefs();
  }, [open, pluralType, entityId]);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const { url } = await api.upload(file);
      await api.createReference(pluralType, entityId, { url, role: 'moodboard' });
      await fetchRefs();
    } catch (e) {
      console.error('Upload failed', e);
    } finally {
      setUploading(false);
    }
  };

  const handleRoleChange = async (refId, role) => {
    try {
      await api.updateReference(refId, { role });
      // Setting 'primary' demotes any other primary server-side (exactly one
      // primary per entity is enforced) — refetch rather than optimistically
      // patch just this card, or the demoted one would show stale.
      await fetchRefs();
    } catch (e) {
      console.error('Role update failed', e);
    }
  };

  const handleDelete = async (refId) => {
    try {
      await api.deleteReference(refId);
      setReferences((prev) => prev.filter((r) => r.id !== refId));
    } catch (e) {
      console.error('Delete failed', e);
    }
  };

  // Lazily generate the cut-out the first time it's needed, then show it.
  const handleRemoveBg = async (refId) => {
    if (bgBusy[refId]) return;
    setBgBusy((prev) => ({ ...prev, [refId]: true }));
    try {
      const updated = await api.removeBackground(refId);
      setReferences((prev) =>
        prev.map((r) => (r.id === refId ? { ...r, processed_url: updated.processed_url } : r))
      );
      setViewProcessed((prev) => ({ ...prev, [refId]: true }));
    } catch (e) {
      console.error('Background removal failed', e);
    } finally {
      setBgBusy((prev) => ({ ...prev, [refId]: false }));
    }
  };

  // Frontend-only view switch — never hits the API, never regenerates.
  const toggleView = (refId) => {
    setViewProcessed((prev) => ({ ...prev, [refId]: !(prev[refId] ?? true) }));
  };

  // Delete the cut-out and reset back to the "removable" state.
  const handleRestoreBg = async (refId) => {
    if (bgBusy[refId]) return;
    setBgBusy((prev) => ({ ...prev, [refId]: true }));
    try {
      await api.restoreBackground(refId);
      setReferences((prev) =>
        prev.map((r) => (r.id === refId ? { ...r, processed_url: null } : r))
      );
      setViewProcessed((prev) => {
        const next = { ...prev };
        delete next[refId];
        return next;
      });
    } catch (e) {
      console.error('Background restore failed', e);
    } finally {
      setBgBusy((prev) => ({ ...prev, [refId]: false }));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-bay-850 border-line text-fg max-w-xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>References — {entityName}</DialogTitle>
        </DialogHeader>

        {entityType === 'character' && (
          <div className="bg-lead-500/15 border border-lead-500/30 rounded-frame p-3 text-xs text-set mb-3">
            For best 3D mesh results, upload a front-facing photo with a neutral T/A-pose
            and uncluttered background. Background removal is available for each reference.
          </div>
        )}

        <input
          id="ref-upload-input"
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleUpload}
        />

        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-fg-muted" />
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <div
              onClick={() => document.getElementById('ref-upload-input').click()}
              className="aspect-[3/4] rounded-frame border-2 border-dashed border-bay-600 bg-bay-800 flex flex-col items-center justify-center gap-2 cursor-pointer hover:bg-bay-700 hover:border-bay-600 transition-colors"
            >
              {uploading ? (
                <Loader2 className="w-6 h-6 animate-spin text-fg-muted" />
              ) : (
                <>
                  <Plus className="w-8 h-8 text-fg-muted" />
                  <span className="text-xs text-fg-muted">Upload</span>
                </>
              )}
            </div>

            {references.map((ref) => (
              <div key={ref.id} className="aspect-[3/4] rounded-frame border border-line bg-bay-800 overflow-hidden flex flex-col group relative">
                <div className="flex-1 bg-bay-900 flex items-center justify-center overflow-hidden">
                  {ref.url ? (
                    <img
                      src={api.getReferenceFileUrl(ref, { processed: viewProcessed[ref.id] ?? true })}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span className="text-[10px] text-fg-faint">No file</span>
                  )}
                </div>
                <div className="p-1.5 space-y-1">
                  <div className="flex items-center gap-1">
                    <select
                      value={ref.role}
                      onChange={(e) => handleRoleChange(ref.id, e.target.value)}
                      className="text-[9px] bg-bay-900 border border-line rounded px-1 py-0.5 text-fg w-full"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1">
                      {ref.url && !ref.processed_url && (
                        <button
                          onClick={() => handleRemoveBg(ref.id)}
                          disabled={bgBusy[ref.id]}
                          className="p-0.5 rounded hover:bg-clip/20 text-prop transition-colors disabled:opacity-40"
                          title="Remove background"
                        >
                          {bgBusy[ref.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
                        </button>
                      )}
                      {ref.processed_url && (
                        <>
                          <button
                            onClick={() => toggleView(ref.id)}
                            className={`p-0.5 rounded transition-colors ${
                              (viewProcessed[ref.id] ?? true)
                                ? 'text-ok hover:bg-ok/15'
                                : 'text-fg-muted hover:bg-bay-700'
                            }`}
                            title={
                              (viewProcessed[ref.id] ?? true)
                                ? 'Showing background-removed — click to show original'
                                : 'Showing original — click to show background-removed'
                            }
                          >
                            <Wand2 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => handleRestoreBg(ref.id)}
                            disabled={bgBusy[ref.id]}
                            className="text-[7px] rounded bg-bay-700 hover:bg-stop text-fg-muted hover:text-bay-950 px-1 py-0 transition-colors disabled:opacity-40"
                            title="Delete background-removed image"
                          >
                            BG off
                          </button>
                        </>
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(ref.id)}
                      className="p-0.5 rounded hover:bg-stop/15 text-stop transition-colors opacity-0 group-hover:opacity-100"
                      title="Delete reference"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} className="bg-lead-500 hover:bg-lead-400 text-bay-950 font-semibold">
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
