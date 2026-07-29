import { useState, useEffect, useRef } from 'react';
import { Sparkles, Loader2, ImageIcon, Film } from 'lucide-react';
import { api } from '../../lib/api';

export function CellGeneration({ scene }) {
  const initial = scene.generated_images?.[0];
  const [generating, setGenerating] = useState(false);
  const [imageId, setImageId] = useState(initial?.image_url ? initial.id : null);
  const [imageUrl, setImageUrl] = useState(
    initial?.image_url ? `/api/generate/image/${initial.id}` : null
  );
  const [status, setStatus] = useState(scene.generation_status || 'idle');

  const [videoUrl, setVideoUrl] = useState(null);
  const [videoStatus, setVideoStatus] = useState('idle');
  const [videoGenerating, setVideoGenerating] = useState(false);

  const pollingRef = useRef(null);
  const videoPollingRef = useRef(null);

  const startPolling = (genId) => {
    pollingRef.current = setInterval(async () => {
      try {
        const data = await api.getGenerationStatus(genId);
        setStatus(data.status);
        if (data.status === 'completed') {
          setImageId(genId);
          setImageUrl(`/api/generate/image/${genId}`);
          setGenerating(false);
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        } else if (data.status === 'failed') {
          setGenerating(false);
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      } catch (e) {
        console.error('Polling failed', e);
      }
    }, 2000);
  };

  // LTX clips take minutes, not seconds — poll slower than the image path.
  const startVideoPolling = (videoId) => {
    videoPollingRef.current = setInterval(async () => {
      try {
        const data = await api.getVideoStatus(videoId);
        setVideoStatus(data.status);
        if (data.status === 'completed') {
          setVideoUrl(api.getVideoFileUrl(videoId));
          setVideoGenerating(false);
          clearInterval(videoPollingRef.current);
          videoPollingRef.current = null;
        } else if (data.status === 'failed') {
          setVideoGenerating(false);
          clearInterval(videoPollingRef.current);
          videoPollingRef.current = null;
        }
      } catch (e) {
        console.error('Video polling failed', e);
      }
    }, 5000);
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

  const handleGenerateVideo = async () => {
    if (!imageId) return;
    setVideoGenerating(true);
    setVideoStatus('queued');
    try {
      const data = await api.generateVideo(imageId);
      startVideoPolling(data.video_id);
    } catch (e) {
      console.error('Video generation failed', e);
      setVideoGenerating(false);
      setVideoStatus('failed');
    }
  };

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (videoPollingRef.current) clearInterval(videoPollingRef.current);
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

  if (videoUrl) {
    return (
      <video
        src={videoUrl}
        controls
        loop
        muted
        className="w-24 h-16 object-cover rounded-lg border border-white/10"
      />
    );
  }

  if (imageUrl) {
    return (
      <div className="relative group">
        <img
          src={imageUrl}
          alt="Generated scene"
          className="w-24 h-16 object-cover rounded-lg border border-white/10"
        />
        {videoGenerating ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 bg-black/70 rounded-lg">
            <Loader2 className="w-4 h-4 animate-spin text-fuchsia-400" />
            <span className="text-[9px] text-slate-400 capitalize">{videoStatus}</span>
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg">
            <button onClick={handleGenerate} title="Regenerate image">
              <Sparkles className="w-4 h-4 text-cyan-400" />
            </button>
            <button onClick={handleGenerateVideo} title="Generate video from this image">
              <Film className="w-4 h-4 text-fuchsia-400" />
            </button>
          </div>
        )}
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
