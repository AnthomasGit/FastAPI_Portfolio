import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Sparkles, ImageIcon, RotateCcw, Check } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { api } from '../../lib/api';

export function SetImageDialog({ entityType, entityId, entityName, projectId, open, onOpenChange, onAssigned }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('generate-text');
  const [prompt, setPrompt] = useState('');
  const [sourceRefId, setSourceRefId] = useState('');
  const [sourceAssetImageId, setSourceAssetImageId] = useState('');
  const [pendingAssetId, setPendingAssetId] = useState(null);
  const [imageSize, setImageSize] = useState('768x1024');

  const [sizeWidth, sizeHeight] = imageSize.split('x').map(Number);

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
    onSuccess: (reference) => {
      queryClient.invalidateQueries({ queryKey: ['references', pluralType, entityId] });
      queryClient.invalidateQueries({ queryKey: ['asset-images'] });
      // No global primary — the caller (e.g. Scene Detail) decides whether
      // this pool reference becomes the CURRENT scene's primary.
      onAssigned?.(reference.id);
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
      width: sizeWidth,
      height: sizeHeight,
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
      setImageSize('768x1024');
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
      <DialogContent className="bg-bay-850 border-line text-fg max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="tracking-wide text-fg">{entityName}</DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} orientation="vertical" className="w-full gap-4">
          <TabsList className="flex-col bg-bay-800 border border-line shrink-0 min-w-[88px] self-start">
            <TabsTrigger value="generate-text" className="w-full justify-start text-xs data-active:bg-bay-700 data-active:text-fg text-fg-muted">
              <Sparkles className="w-3 h-3" />Text
            </TabsTrigger>
            <TabsTrigger value="generate-image" className="w-full justify-start text-xs data-active:bg-bay-700 data-active:text-fg text-fg-muted">
              <ImageIcon className="w-3 h-3" />From image
            </TabsTrigger>
          </TabsList>

          <TabsContent value="generate-text" className="space-y-4 mt-0">
            <div className="space-y-3">
              <Textarea
                placeholder="Describe the image..."
                className="bg-bay-800 border-line text-fg placeholder:text-fg-faint min-h-[88px] resize-none focus:border-lead-500 transition-colors"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />

              <div className="space-y-2">
                <label className="text-[11px] text-fg-muted font-medium tracking-wide uppercase">Image size</label>
                <Select value={imageSize} onValueChange={setImageSize} modal={false}>
                  <SelectTrigger className="bg-bay-800 border-line text-fg h-8 text-xs w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-bay-850 border-line text-fg text-xs">
                    <SelectItem value="768x1024">Portrait — 768 × 1024</SelectItem>
                    <SelectItem value="1024x1024">Square — 1024 × 1024</SelectItem>
                    <SelectItem value="1024x768">Landscape — 1024 × 768</SelectItem>
                    <SelectItem value="1280x720">Widescreen — 1280 × 720</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[11px] text-fg-faint">
                  {prompt.length > 0 ? `${prompt.length} characters` : ''}
                </span>
                <Button
                  onClick={handleGenerateText}
                  disabled={isLoading || !prompt.trim()}
                  size="sm"
                  className="bg-lead-500 hover:bg-lead-500 text-fg disabled:opacity-30"
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
              <div className="rounded-frame border border-line bg-bay-800 overflow-hidden">
                <div className="aspect-video flex items-center justify-center bg-bay-900">
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-lead-500/30 border-t-lead-500 animate-spin" />
                    <span className="text-[11px] text-fg-muted animate-pulse">Generating...</span>
                  </div>
                </div>
              </div>
            )}

            {isCompleted && pendingAsset?.image_url && (
              <div className="rounded-frame border border-lead-500/30 bg-lead-500/5 overflow-hidden shadow-[0_0_24px_-4px_rgba(245,158,11,0.12)]">
                <div className="aspect-video flex items-center justify-center bg-bay-900 p-2">
                  <img
                    src={api.getAssetImageFile(pendingAssetId)}
                    alt=""
                    className="w-full h-full object-contain rounded"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 px-3 py-2.5 border-t border-line">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRegenerate}
                    disabled={isLoading}
                    className="text-fg-muted hover:text-fg text-xs"
                  >
                    <RotateCcw className="w-3 h-3 mr-1" />
                    Regenerate
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleAssign}
                    disabled={isLoading}
                    className="bg-ok hover:bg-ok text-fg text-xs"
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
              <div className="rounded-frame border border-stop/30 bg-stop/15[0.03] px-3 py-2.5">
                <p className="text-xs text-stop/80">
                  Generation failed. {pendingAsset?.error ? `Error: ${pendingAsset.error}` : 'Try a different prompt.'}
                </p>
              </div>
            )}
          </TabsContent>

          <TabsContent value="generate-image" className="space-y-4 mt-0">
            <div className="space-y-3">
              <Textarea
                placeholder="Describe the edit or variation..."
                className="bg-bay-800 border-line text-fg placeholder:text-fg-faint min-h-[72px] resize-none focus:border-lead-500 transition-colors"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />

              <div className="space-y-2">
                <label className="text-[11px] text-fg-muted font-medium tracking-wide uppercase">Source reference</label>
                {(references || []).filter((r) => r.url).length > 0 ? (
                  <Select value={sourceRefId} onValueChange={(v) => { setSourceRefId(v); setSourceAssetImageId(''); }} modal={false}>
                    <SelectTrigger className="bg-bay-800 border-line text-fg h-8 text-xs w-full">
                      <SelectValue placeholder="None selected" />
                    </SelectTrigger>
                    <SelectContent className="bg-bay-850 border-line text-fg text-xs">
                      {(references || []).filter((r) => r.url).map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {r.role}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="bg-bay-800 border border-line text-fg-faint h-8 text-xs w-full rounded px-2 flex items-center">
                    No reference images
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-[11px] text-fg-muted font-medium tracking-wide uppercase">Library image</label>
                {(assetImages || []).filter((a) => a.status === 'completed').length > 0 ? (
                  <Select value={sourceAssetImageId} onValueChange={(v) => { setSourceAssetImageId(v); setSourceRefId(''); }} modal={false}>
                    <SelectTrigger className="bg-bay-800 border-line text-fg h-8 text-xs w-full">
                      <SelectValue placeholder="None selected" />
                    </SelectTrigger>
                    <SelectContent className="bg-bay-850 border-line text-fg text-xs">
                      {(assetImages || []).filter((a) => a.status === 'completed').map((a) => (
                        <SelectItem key={a.id} value={a.id}>
                          {a.kind} — {a.prompt?.slice(0, 30)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="bg-bay-800 border border-line text-fg-faint h-8 text-xs w-full rounded px-2 flex items-center">
                    No library images
                  </div>
                )}
              </div>

              {(selectedRefUrl || selectedAssetUrl) && (
                <div className="flex justify-start">
                  <div className="max-h-48 rounded-frame border border-line overflow-hidden bg-bay-900">
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
                  className="bg-lead-500 hover:bg-lead-500 text-fg disabled:opacity-30"
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
              <div className="rounded-frame border border-line bg-bay-800 overflow-hidden">
                <div className="aspect-video flex items-center justify-center bg-bay-900">
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-lead-500/30 border-t-lead-500 animate-spin" />
                    <span className="text-[11px] text-fg-muted animate-pulse">Generating...</span>
                  </div>
                </div>
              </div>
            )}

            {isCompleted && pendingAsset?.image_url && (
              <div className="rounded-frame border border-lead-500/30 bg-lead-500/5 overflow-hidden shadow-[0_0_24px_-4px_rgba(245,158,11,0.12)]">
                <div className="aspect-video flex items-center justify-center bg-bay-900 p-2">
                  <img
                    src={api.getAssetImageFile(pendingAssetId)}
                    alt=""
                    className="w-full h-full object-contain rounded"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 px-3 py-2.5 border-t border-line">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRegenerate}
                    disabled={isLoading}
                    className="text-fg-muted hover:text-fg text-xs"
                  >
                    <RotateCcw className="w-3 h-3 mr-1" />
                    Regenerate
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleAssign}
                    disabled={isLoading}
                    className="bg-ok hover:bg-ok text-fg text-xs"
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
              <div className="rounded-frame border border-stop/30 bg-stop/15[0.03] px-3 py-2.5">
                <p className="text-xs text-stop/80">
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
