import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { api } from '../../lib/api';
import {
  PROFILE_FIELDS, HAS_OUTFITS, DEPT_ACCENT,
  profileToDraft, linesToTokens, hasProfile,
} from './promptProfileFields';

// The prompt profile, shown and edited where the asset's description already
// lives. It is the single most load-bearing field in generation and until now
// had no UI at all: with no profile, prompts silently fall back to the
// screenplay description ("Anxiously watches the game") — narrative, not
// visual, pinning no identity, so every unspecified attribute resamples per
// render. A user glancing at six tokens catches that instantly; nobody catches
// it by reading render output.
//
// Editing is a dialog rather than inline: these cards sit four-up in a grid,
// and a location carries six token lists.

// Written out per department rather than interpolated: Tailwind scans source
// for complete class strings, so a `ring-${accent}/20` would never be emitted.
const CHIP_RING = {
  cast: 'ring-cast/25',
  set: 'ring-set/25',
  prop: 'ring-prop/25',
};

function Chips({ tokens, accent, max = 6 }) {
  const shown = tokens.slice(0, max);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((t, i) => (
        <span key={i}
          className={`px-1.5 py-0.5 rounded text-[10px] leading-tight text-fg-muted
                      bg-bay-950 border border-line ring-inset ring-1 ${CHIP_RING[accent] || CHIP_RING.cast}`}>
          {t}
        </span>
      ))}
      {tokens.length > max && (
        <span className="px-1.5 py-0.5 text-[10px] leading-tight text-fg-faint">
          +{tokens.length - max}
        </span>
      )}
    </div>
  );
}

function OutfitEditor({ outfits, onChange }) {
  const set = (i, patch) =>
    onChange(outfits.map((o, j) => (j === i ? { ...o, ...patch } : o)));

  // Exactly one default: it is the outfit baked into every prompt, so two
  // would describe someone wearing both at once.
  const setDefault = (i) =>
    onChange(outfits.map((o, j) => ({ ...o, default: j === i })));

  return (
    <div className="space-y-2">
      {outfits.map((o, i) => (
        <div key={i} className="rounded-frame border border-line bg-bay-950 p-2">
          <div className="flex items-center gap-2">
            <input type="radio" checked={!!o.default} onChange={() => setDefault(i)}
              className="accent-lead-500" title="Worn by default" />
            <Input value={o.name} onChange={(e) => set(i, { name: e.target.value })}
              placeholder="outfit name" className="h-7 text-xs" />
            <button type="button" title="Remove outfit"
              onClick={() => onChange(outfits.filter((_, j) => j !== i))}
              className="text-fg-faint hover:text-stop transition-colors">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          <Textarea
            value={(o.items || []).join('\n')}
            onChange={(e) => set(i, { items: linesToTokens(e.target.value) })}
            rows={3} placeholder={'olive green jersey\nblack track pants\nblack sneakers'}
            className="mt-1.5 text-xs font-mono" />
        </div>
      ))}
      <Button variant="ghost" size="sm"
        onClick={() => onChange([...outfits, { name: '', items: [], default: outfits.length === 0 }])}>
        <Plus className="w-3.5 h-3.5" /> Add outfit
      </Button>
    </div>
  );
}

function ProfileDialog({ open, onOpenChange, entityType, entityId, entityName, profile }) {
  const fields = PROFILE_FIELDS[entityType] || PROFILE_FIELDS.character;
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => profileToDraft(profile, fields));
  const [outfits, setOutfits] = useState(() => (profile?.outfits || []).map((o) => ({ ...o })));

  // No Regenerate here on purpose. POST /prompt-profile writes and COMMITS
  // before the user saves, so Cancel would not undo it; it replaces whatever
  // was typed in this dialog; and it bypasses profile_service's sanitiser,
  // making it the one path that can still write a mood token into `appearance`.
  // Profiles are generated automatically at project build; this dialog is for
  // reading and correcting them.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['project'] });

  const save = useMutation({
    mutationFn: () => {
      const next = { ...(profile || {}) };
      for (const f of fields) next[f.key] = linesToTokens(draft[f.key]);
      if (HAS_OUTFITS[entityType]) {
        const cleaned = outfits
          .map((o) => ({ ...o, name: (o.name || '').trim(), items: o.items || [] }))
          .filter((o) => o.name && o.items.length);
        // Never leave the set without a default — it is what every prompt wears.
        if (cleaned.length && !cleaned.some((o) => o.default)) cleaned[0].default = true;
        next.outfits = cleaned;
      }
      return api.savePromptProfile(`${entityType}s`, entityId, next);
    },
    onSuccess: () => { invalidate(); onOpenChange(false); },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono">{entityName} — prompt profile</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-fg-muted -mt-1">
          One token per line. These are repeated in every frame this
          {entityType === 'location' ? ' place' : ' subject'} appears in, so keep
          them to what is permanently true.
        </p>

        {fields.map((f) => (
          <label key={f.key} className="mt-4 block">
            <span className="label-slug block mb-1">{f.label}</span>
            <Textarea rows={f.key === 'appearance' || f.key === 'environment' ? 5 : 3}
              value={draft[f.key] || ''}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
              className="text-xs font-mono" />
            <span className="mt-1 block text-[10px] text-fg-faint leading-relaxed">{f.hint}</span>
          </label>
        ))}

        {HAS_OUTFITS[entityType] && (
          <div className="mt-4">
            <span className="label-slug block mb-1">Outfits</span>
            <span className="mb-2 block text-[10px] text-fg-faint leading-relaxed">
              A full head-to-toe set worn together, not single garments. The
              default is worn in every prompt; alternates are opt-in per sheet
              and selectable per scene.
            </span>
            <OutfitEditor outfits={outfits} onChange={setOutfits} />
          </div>
        )}

        {/* Sticky because DialogContent is itself the scroll container: a
            location carries six token lists, so Save would otherwise sit a
            scroll below the fold. Bleeds through the dialog's p-4 with negative
            margins, and takes bg-popover (not a bay-* step) so it matches
            whatever surface the dialog primitive is on and content scrolling
            underneath is fully hidden — no alpha. */}
        <div className="sticky bottom-0 -mx-4 -mb-4 mt-5 border-t border-line bg-popover px-4 py-3">
          {save.isError && (
            <p role="alert" className="mb-2 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
              {save.error?.message || 'Something went wrong'}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function PromptProfilePanel({ entityType, entityId, entityName, profile }) {
  const [open, setOpen] = useState(false);
  const accent = DEPT_ACCENT[entityType] || 'cast';
  const present = hasProfile(profile);

  const fields = PROFILE_FIELDS[entityType] || PROFILE_FIELDS.character;
  const primary = fields[0].key;                       // appearance / environment
  const tokens = (profile || {})[primary] || [];
  const outfits = profile?.outfits || [];
  const worn = outfits.find((o) => o.default) || outfits[0];

  return (
    <div className="mt-2.5 pt-2.5 border-t border-line/60">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide text-fg-faint">Profile</span>
        <button type="button" onClick={() => setOpen(true)}
          title={present ? 'Edit prompt profile' : 'Add a prompt profile'}
          className="flex items-center justify-center w-5 h-5 rounded border border-line text-fg-faint hover:text-fg hover:border-bay-600 transition-colors">
          <Pencil className="w-3 h-3" />
        </button>
      </div>

      {present ? (
        <>
          <Chips tokens={tokens} accent={accent} />
          {worn && (
            <p className="mt-1.5 text-[10px] text-fg-faint">
              Wears <span className="text-fg-muted">{worn.name}</span>
              {outfits.length > 1 && ` · ${outfits.length - 1} alternate${outfits.length > 2 ? 's' : ''}`}
            </p>
          )}
        </>
      ) : (
        // Worth spelling out: this is the state that silently degrades every
        // render made from this entity.
        <p className="text-[11px] text-warn/80 leading-relaxed">
          No profile — prompts fall back to the description above, which pins no
          look.
        </p>
      )}

      {open && (
        <ProfileDialog open={open} onOpenChange={setOpen} entityType={entityType}
          entityId={entityId} entityName={entityName} profile={profile} />
      )}
    </div>
  );
}
