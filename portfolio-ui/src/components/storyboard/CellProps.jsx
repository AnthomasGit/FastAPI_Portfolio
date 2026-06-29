import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { api } from '../../lib/api';

export function CellProps({ scene, projectId }) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
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
        <Badge key={p.id} variant="secondary" className="text-[10px] bg-purple-500/10 text-purple-300 border-purple-500/20">
          {p.name}
        </Badge>
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
    </div>
  );
}
