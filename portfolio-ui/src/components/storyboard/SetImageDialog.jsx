import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Sparkles, ImageIcon, RotateCcw, Check } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { api } from '../../lib/api';

export function SetImageDialog({ entityType, entityId, entityName, projectId, open, onOpenChange }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('generate-text');
  const [prompt, setPrompt] = useState('');
  const [sourceRefId, setSourceRefId] = useState('');
  const [sourceAssetImageId, setSourceAssetImageId] = useState('');
  const [pendingAssetId, setPendingAssetId] = useState(null);

  const pluralType = `${entityType}s`;

  const { data: references } = useQuery({
    queryKey: ['references', pluralType, entityId],
    queryFn: () => api.listReferences(pluralType, entityId),
    enabled: open && activeTab === 'generate-image',
  });

  const { data: assetImages } = useQuery({
    queryKey: ['asset-images', entityType, projectId],
    queryFn: () => api.listAssetImages({ entity_type: pluralType, project_id: projectId }),
    enabled: open && activeTab === 'generate-image',
  });

  const { data: pendingAsset } = useQuery({
    queryKey: ['asset-image', pendingAssetId],
    queryFn: () => api.getAssetImage(pendingAssetId),
    enabled: !!pendingAssetId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === 'completed' || status === 'failed') return false;
      return 2000;
    },
  });

  const generateMutation = useMutation({
    mutationFn: (data) => api.generateAssetImage(data),
    onSuccess: (result) => {
      setPendingAssetId(result.asset_image_id);
      queryClient.invalidateQueries({ queryKey: ['asset-images'] });
    },
  });

  const assignMutation = useMutation({
    mutationFn: ({ entityType, entityId, assetImageId }) =>
      api.assignAssetImage(entityType, entityId, assetImageId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['references', pluralType, entityId] });
      queryClient.invalidateQueries({ queryKey: ['asset-images'] });
      onOpenChange(false);
    },
  });

  const selectedReference = (references || []).find((r) => r.id === sourceRefId);
  const selectedAssetImage = (assetImages || []).find((a) => a.id === sourceAssetImageId);

  const pendingStatus = pendingAsset?.status;
  const isProcessing = pendingStatus === 'queued' || pendingStatus === 'processing';
  const isCompleted = pendingStatus === 'completed';
  const isFailed = pendingStatus === 'failed';
  const isLoading = generateMutation.isPending || assignMutation.isPending;

  const handleGenerateText = () => {
    if (!prompt.trim()) return;
    generateMutation.mutate({
      project_id: projectId,
      entity_type: pluralType,
      prompt,
    });
  };

  const handleGenerateFromImage = () => {
    generateMutation.mutate({
      project_id: projectId,
      entity_type: pluralType,
      prompt,
      source_reference_id: sourceRefId || undefined,
      source_asset_image_id: sourceAssetImageId || undefined,
    });
  };

  const handleAssign = () => {
    assignMutation.mutate({ entityType: pluralType, entityId, assetImageId: pendingAssetId });
  };

  const handleRegenerate = () => {
    setPendingAssetId(null);
    if (activeTab === 'generate-text') {
      handleGenerateText();
    } else {
      handleGenerateFromImage();
    }
  };

  const handleDialogClose = (open) => {
    if (!open) {
      setPendingAssetId(null);
      setPrompt('');
      setSourceRefId('');
      setSourceAssetImageId('');
      setActiveTab('generate-text');
    }
    onOpenChange(open);
  };

  const selectedRefUrl = selectedReference
    ? api.getReferenceFileUrl(selectedReference)
    : null;

  const selectedAssetUrl = selectedAssetImage
    ? api.getAssetImageFile(selectedAssetImage.id)
    : null;

  return (
    <Dialog open={open} onOpenChange={handleDialogClose}>
      <DialogContent className="bg-slate-950 border-white/10 text-slate-200 max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="tracking-wide text-slate-100">{entityName}</DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} orientation="vertical" className="w-full gap-4">
          <TabsList className="flex-col bg-white/[0.04] border border-white/[0.06] shrink-0 min-w-[88px] self-start">
            <TabsTrigger value="generate-text" className="w-full justify-start text-xs data-active:bg-white/10 data-active:text-white text-slate-400">
              <Sparkles className="w-3 h-3" />Text
            </TabsTrigger>
            <TabsTrigger value="generate-image" className="w-full justify-start text-xs data-active:bg-white/10 data-active:text-white text-slate-400">
              <ImageIcon className="w-3 h-3" />From image
            </TabsTrigger>
          </TabsList>

          <TabsContent value="generate-text" className="space-y-4 mt-0">
            <div className="space-y-3">
              <Textarea
                placeholder="Describe the image..."
                className="bg-white/[0.04] border-white/[0.08] text-white placeholder:text-slate-600 min-h-[88px] resize-none focus:border-amber-500/40 transition-colors"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />

              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-600">
                  {prompt.length > 0 ? `${prompt.length} characters` : ''}
                </span>
                <Button
                  onClick={handleGenerateText}
                  disabled={isLoading || !prompt.trim()}
                  size="sm"
                  className="bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-30"
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                  ) : (
                    <Sparkles className="w-3.5 h-3.5 mr-1.5" />
                  )}
                  Generate
                </Button>
              </div>
            </div>

            {isProcessing && (
              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <div className="aspect-video flex items-center justify-center bg-black/40">
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-amber-500/30 border-t-amber-500 animate-spin" />
                    <span className="text-[11px] text-slate-500 animate-pulse">Generating...</span>
                  </div>
                </div>
              </div>
            )}

            {isCompleted && pendingAsset?.image_url && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.02] overflow-hidden shadow-[0_0_24px_-4px_rgba(245,158,11,0.12)]">
                <div className="aspect-video flex items-center justify-center bg-black/50 p-2">
                  <img
                    src={api.getAssetImageFile(pendingAssetId)}
                    alt=""
                    className="w-full h-full object-contain rounded"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 px-3 py-2.5 border-t border-white/[0.06]">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRegenerate}
                    disabled={isLoading}
                    className="text-slate-400 hover:text-white text-xs"
                  >
                    <RotateCcw className="w-3 h-3 mr-1" />
                    Regenerate
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleAssign}
                    disabled={isLoading}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs"
                  >
                    {assignMutation.isPending ? (
                      <Loader2 className="w-3 h-3 animate-spin mr-1" />
                    ) : (
                      <Check className="w-3 h-3 mr-1" />
                    )}
                    Assign
                  </Button>
                </div>
              </div>
            )}

            {isFailed && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/[0.03] px-3 py-2.5">
                <p className="text-xs text-red-400/80">
                  Generation failed. {pendingAsset?.error ? `Error: ${pendingAsset.error}` : 'Try a different prompt.'}
                </p>
              </div>
            )}
          </TabsContent>

          <TabsContent value="generate-image" className="space-y-4 mt-0">
            <div className="space-y-3">
              <Textarea
                placeholder="Describe the edit or variation..."
                className="bg-white/[0.04] border-white/[0.08] text-white placeholder:text-slate-600 min-h-[72px] resize-none focus:border-amber-500/40 transition-colors"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />

              <div className="space-y-2">
                <label className="text-[11px] text-slate-500 font-medium tracking-wide uppercase">Source reference</label>
                {(references || []).filter((r) => r.url).length > 0 ? (
                  <Select value={sourceRefId} onValueChange={(v) => { setSourceRefId(v); setSourceAssetImageId(''); }}>
                    <SelectTrigger className="bg-white/[0.04] border-white/[0.08] text-white h-8 text-xs w-full">
                      <SelectValue placeholder="None selected" />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-900 border-white/[0.08] text-white text-xs">
                      {(references || []).filter((r) => r.url).map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {r.role}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="bg-white/[0.04] border border-white/[0.08] text-slate-600 h-8 text-xs w-full rounded px-2 flex items-center">
                    No reference images
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-[11px] text-slate-500 font-medium tracking-wide uppercase">Library image</label>
                {(assetImages || []).filter((a) => a.status === 'completed').length > 0 ? (
                  <Select value={sourceAssetImageId} onValueChange={(v) => { setSourceAssetImageId(v); setSourceRefId(''); }}>
                    <SelectTrigger className="bg-white/[0.04] border-white/[0.08] text-white h-8 text-xs w-full">
                      <SelectValue placeholder="None selected" />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-900 border-white/[0.08] text-white text-xs">
                      {(assetImages || []).filter((a) => a.status === 'completed').map((a) => (
                        <SelectItem key={a.id} value={a.id}>
                          {a.kind} — {a.prompt?.slice(0, 30)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="bg-white/[0.04] border border-white/[0.08] text-slate-600 h-8 text-xs w-full rounded px-2 flex items-center">
                    No library images
                  </div>
                )}
              </div>

              {(selectedRefUrl || selectedAssetUrl) && (
                <div className="flex justify-start">
                  <div className="max-h-48 rounded-lg border border-white/[0.08] overflow-hidden bg-black/40">
                    <img
                      src={selectedRefUrl || selectedAssetUrl}
                      alt=""
                      className="w-full h-full max-h-48 object-contain"
                    />
                  </div>
                </div>
              )}

              <div className="flex justify-end">
                <Button
                  onClick={handleGenerateFromImage}
                  disabled={isLoading || (!sourceRefId && !sourceAssetImageId) || !prompt.trim()}
                  size="sm"
                  className="bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-30"
                >
                  {generateMutation.isPending ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                  ) : (
                    <ImageIcon className="w-3.5 h-3.5 mr-1.5" />
                  )}
                  Generate
                </Button>
              </div>
            </div>

            {isProcessing && (
              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <div className="aspect-video flex items-center justify-center bg-black/40">
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-amber-500/30 border-t-amber-500 animate-spin" />
                    <span className="text-[11px] text-slate-500 animate-pulse">Generating...</span>
                  </div>
                </div>
              </div>
            )}

            {isCompleted && pendingAsset?.image_url && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.02] overflow-hidden shadow-[0_0_24px_-4px_rgba(245,158,11,0.12)]">
                <div className="aspect-video flex items-center justify-center bg-black/50 p-2">
                  <img
                    src={api.getAssetImageFile(pendingAssetId)}
                    alt=""
                    className="w-full h-full object-contain rounded"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 px-3 py-2.5 border-t border-white/[0.06]">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRegenerate}
                    disabled={isLoading}
                    className="text-slate-400 hover:text-white text-xs"
                  >
                    <RotateCcw className="w-3 h-3 mr-1" />
                    Regenerate
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleAssign}
                    disabled={isLoading}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs"
                  >
                    {assignMutation.isPending ? (
                      <Loader2 className="w-3 h-3 animate-spin mr-1" />
                    ) : (
                      <Check className="w-3 h-3 mr-1" />
                    )}
                    Assign
                  </Button>
                </div>
              </div>
            )}

            {isFailed && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/[0.03] px-3 py-2.5">
                <p className="text-xs text-red-400/80">
                  Generation failed. {pendingAsset?.error ? `Error: ${pendingAsset.error}` : 'Try a different prompt.'}
                </p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
