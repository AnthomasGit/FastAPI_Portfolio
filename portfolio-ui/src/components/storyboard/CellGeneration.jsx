import { useState, useEffect, useRef } from 'react';
import { Sparkles, Loader2, ImageIcon } from 'lucide-react';
import { api } from '../../lib/api';

export function CellGeneration({ scene }) {
  const [generating, setGenerating] = useState(false);
  const [imageUrl, setImageUrl] = useState(
    scene.generated_images?.[0]?.image_url
      ? `/api/generate/image/${scene.generated_images[0].id}`
      : null
  );
  const [status, setStatus] = useState(scene.generation_status || 'idle');
  const pollingRef = useRef(null);

  const startPolling = (genId) => {
    pollingRef.current = setInterval(async () => {
      try {
        const data = await api.getGenerationStatus(genId);
        setStatus(data.status);
        if (data.status === 'completed') {
          setImageUrl(`/api/generate/image/${genId}`);
          setGenerating(false);
          clearInterval(pollingRef.current);
        } else if (data.status === 'failed') {
          setGenerating(false);
          clearInterval(pollingRef.current);
        }
      } catch (e) {
        console.error('Polling failed', e);
      }
    }, 2000);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setStatus('queued');
    try {
      const data = await api.generateScene(scene.id);
      startPolling(data.generation_id);
    } catch (e) {
      console.error('Generation failed', e);
      setGenerating(false);
      setStatus('failed');
    }
  };

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  useEffect(() => {
    const gens = scene.generated_images || [];
    const latest = gens[gens.length - 1];
    if (latest && (latest.status === 'processing' || latest.status === 'queued') && !pollingRef.current) {
      setGenerating(true);
      setStatus(latest.status);
      startPolling(latest.id);
    }
  }, [scene.generated_images]);

  if (imageUrl) {
    return (
      <div className="relative group">
        <img
          src={imageUrl}
          alt="Generated scene"
          className="w-24 h-16 object-cover rounded-lg border border-white/10"
        />
        <button
          onClick={handleGenerate}
          className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg"
        >
          <Sparkles className="w-4 h-4 text-cyan-400" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-[40px]">
      {generating ? (
        <div className="flex flex-col items-center gap-1">
          <Loader2 className="w-5 h-5 animate-spin text-cyan-400" />
          <span className="text-[10px] text-slate-500 capitalize">{status}</span>
        </div>
      ) : (
        <button
          onClick={handleGenerate}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 hover:border-cyan-500/50 transition-all text-xs text-slate-400"
        >
          <ImageIcon className="w-3.5 h-3.5" />
          Generate
        </button>
      )}
    </div>
  );
}
