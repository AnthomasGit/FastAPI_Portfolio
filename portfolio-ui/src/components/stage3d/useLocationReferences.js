import { useQueries } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useLocationReferences(sceneLocations) {
  const results = useQueries({
    queries: sceneLocations.map((loc) => ({
      queryKey: ['references', 'locations', loc.id],
      queryFn: () => api.listReferences('locations', loc.id),
      enabled: !!loc.id,
    })),
  });

  const references = results.flatMap((result, i) =>
    (result.data || []).map((ref) => ({ ...ref, locationName: sceneLocations[i].name }))
  );
  const isLoading = results.some((r) => r.isLoading);

  return { references, isLoading };
}
