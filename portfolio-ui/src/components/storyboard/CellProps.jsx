import { useState } from 'react';
import { Plus, ImageIcon } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { api } from '../../lib/api';
import { ReferenceManager } from './ReferenceManager';
import { SetImageDialog } from './SetImageDialog';

export function CellProps({ scene, projectId }) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [refTarget, setRefTarget] = useState(null);
  const [imageTarget, setImageTarget] = useState(null);
  const props = scene.props || [];

  const handleAdd = async () => {
    if (!newName.trim()) return;
    try {
      await api.createProp(projectId, { name: newName });
      setNewName('');
      setOpen(false);
    } catch (e) {
      console.error('Failed to add prop', e);
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5 min-h-[32px] items-start">
      {props.map((p) => (
        <div key={p.id} className="flex items-center gap-0.5">
          <button onClick={() => setRefTarget(p)} className="focus:outline-none">
            <Badge variant="secondary" className="text-[10px] bg-purple-500/10 text-purple-300 border-purple-500/20 cursor-pointer hover:bg-purple-500/20 transition-colors">
              {p.name}
            </Badge>
          </button>
          <button
            onClick={() => setImageTarget(p)}
            className="p-0.5 rounded hover:bg-white/10 text-slate-500 hover:text-cyan-400 transition-colors"
            title="Set image"
          >
            <ImageIcon className="w-3 h-3" />
          </button>
        </div>
      ))}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <button className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors shrink-0">
            <Plus className="w-3 h-3 text-slate-400" />
          </button>
        </DialogTrigger>
        <DialogContent className="bg-slate-900 border-white/10 text-slate-200">
          <DialogHeader>
            <DialogTitle>Add Prop</DialogTitle>
          </DialogHeader>
          <div className="flex gap-2">
            <Input
              className="bg-black/40 border-white/10 text-white"
              placeholder="Prop name..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Button onClick={handleAdd} className="bg-purple-600 hover:bg-purple-500">Add</Button>
          </div>
        </DialogContent>
      </Dialog>
      {refTarget && (
        <ReferenceManager
          entityType="prop"
          entityId={refTarget.id}
          entityName={refTarget.name}
          open={!!refTarget}
          onOpenChange={(v) => { if (!v) setRefTarget(null); }}
        />
      )}
      {imageTarget && (
        <SetImageDialog
          entityType="prop"
          entityId={imageTarget.id}
          entityName={imageTarget.name}
          projectId={projectId}
          open={!!imageTarget}
          onOpenChange={(v) => { if (!v) setImageTarget(null); }}
        />
      )}
    </div>
  );
}
