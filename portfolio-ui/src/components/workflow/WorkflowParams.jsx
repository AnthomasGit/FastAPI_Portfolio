import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';

// Renders editable controls for a workflow's parameters straight from the
// registry schema (GET /api/workflows, KAN-45/46) — no per-workflow form code.
// Only `control`-group params are user-editable; `input`/`system` params
// (image slots, seed, filename) are resolved by the backend and skipped.
//
// Controlled: `values` is the current { key: value } map, `onChange(next)` gets
// the whole updated map. `openSelect`/`setOpenSelect` funnel every Select
// through one piece of state so only one dropdown is open at a time (Radix
// dropdowns inside a Dialog can otherwise race and dismiss the dialog).

export function WorkflowParams({ params = [], values = {}, onChange, openSelect, setOpenSelect }) {
  const controls = params.filter((p) => p.group === 'control');
  if (controls.length === 0) {
    return <p className="text-[11px] text-fg-faint">This workflow exposes no adjustable parameters.</p>;
  }
  const set = (key, v) => onChange({ ...values, [key]: v });

  return (
    <div className="grid grid-cols-2 gap-3">
      {controls.map((p) => (
        <label key={p.key} className={`block ${p.type === 'text' ? 'col-span-2' : ''}`}>
          <span className="label-slug block mb-1.5">{p.label}</span>
          <ParamControl
            p={p}
            value={values[p.key]}
            onChange={(v) => set(p.key, v)}
            openSelect={openSelect}
            setOpenSelect={setOpenSelect}
          />
        </label>
      ))}
    </div>
  );
}

function ParamControl({ p, value, onChange, openSelect, setOpenSelect }) {
  if (p.type === 'enum') {
    return (
      <Select
        value={value ?? ''}
        onValueChange={onChange}
        modal={false}
        open={openSelect === p.key}
        onOpenChange={(v) => setOpenSelect?.(v ? p.key : null)}
      >
        <SelectTrigger className="bg-bay-900 border-line text-fg h-8 text-xs w-full">
          <SelectValue placeholder="Choose…" />
        </SelectTrigger>
        <SelectContent position="popper" className="bg-bay-850 border-line text-fg text-xs">
          {(p.options || []).map((o) => (
            <SelectItem key={o} value={o}>{o}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (p.type === 'text') {
    return (
      <Textarea
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className="bg-bay-900 border-line text-fg placeholder:text-fg-faint min-h-[64px] resize-none text-xs"
      />
    );
  }

  // int / float — a bounded number input.
  return (
    <Input
      type="number"
      value={value ?? ''}
      min={p.min}
      max={p.max}
      step={p.type === 'float' ? 'any' : 1}
      onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      className="bg-bay-900 border-line text-fg text-xs h-8"
    />
  );
}
