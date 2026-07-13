import { useState } from 'react';
import { Plus, ImageIcon } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { api } from '../../lib/api';
import { ReferenceManager } from './ReferenceManager';
import { SetImageDialog } from './SetImageDialog';

export function CellCharacters({ scene, projectId }) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [refTarget, setRefTarget] = useState(null);
  const [imageTarget, setImageTarget] = useState(null);
  const characters = scene.characters || [];

  const handleAdd = async () => {
    if (!newName.trim()) return;
    try {
      await api.createCharacter(projectId, { name: newName });
      setNewName('');
      setOpen(false);
    } catch (e) {
      console.error('Failed to add character', e);
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5 min-h-[32px] items-start">
      {characters.map((ch) => (
        <div key={ch.id} className="flex items-center gap-0.5">
          <button onClick={() => setRefTarget(ch)} className="focus:outline-none">
            <Badge variant="secondary" className="text-[10px] bg-emerald-500/10 text-emerald-300 border-emerald-500/20 cursor-pointer hover:bg-emerald-500/20 transition-colors">
              {ch.name}
            </Badge>
          </button>
          <button
            onClick={() => setImageTarget(ch)}
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
            <DialogTitle>Add Character</DialogTitle>
          </DialogHeader>
          <div className="flex gap-2">
            <Input
              className="bg-black/40 border-white/10 text-white"
              placeholder="Character name..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Button onClick={handleAdd} className="bg-emerald-600 hover:bg-emerald-500">Add</Button>
          </div>
        </DialogContent>
      </Dialog>
      {refTarget && (
        <ReferenceManager
          entityType="character"
          entityId={refTarget.id}
          entityName={refTarget.name}
          open={!!refTarget}
          onOpenChange={(v) => { if (!v) setRefTarget(null); }}
        />
      )}
      {imageTarget && (
        <SetImageDialog
          entityType="character"
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
