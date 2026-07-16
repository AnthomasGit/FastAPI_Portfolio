import { createContext, useContext } from 'react';

export const CaptureDepthContext = createContext(null);

export function useCaptureDepth() {
  return useContext(CaptureDepthContext);
}
