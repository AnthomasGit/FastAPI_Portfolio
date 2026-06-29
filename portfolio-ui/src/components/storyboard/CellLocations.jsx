import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { api } from '../../lib/api';

export function CellLocations({ scene, projectId }) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const locations = scene.locations || [];

  const handleAdd = async () => {
    if (!newName.trim()) return;
    try {
      await api.createLocation(projectId, { name: newName });
      setNewName('');
      setOpen(false);
    } catch (e) {
      console.error('Failed to add location', e);
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5 min-h-[32px] items-start">
      {locations.map((loc) => (
        <Badge key={loc.id} variant="outline" className="text-[10px] bg-amber-500/10 text-amber-300 border-amber-500/20">
          {loc.name}
          {loc.shot_type && (
            <span className="ml-1 text-[9px] text-amber-400/60 uppercase">({loc.shot_type})</span>
          )}
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
            <DialogTitle>Add Location</DialogTitle>
          </DialogHeader>
          <div className="flex gap-2">
            <Input
              className="bg-black/40 border-white/10 text-white"
              placeholder="Location name..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Button onClick={handleAdd} className="bg-amber-600 hover:bg-amber-500">Add</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
