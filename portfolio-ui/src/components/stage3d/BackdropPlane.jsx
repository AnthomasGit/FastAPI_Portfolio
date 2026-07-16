import { useStagingStore } from '@/stores/stagingStore';

export function BackdropPlane() {
  const backdropReferenceId = useStagingStore((s) => s.backdropReferenceId);

  return (
    <mesh position={[0, 1.5, -5]} scale={[4, 3, 1]} userData={{ isBackdrop: true }}>
      <planeGeometry args={[4, 3]} />
      <meshStandardMaterial color={backdropReferenceId ? '#334155' : '#1e293b'} side={1} />
    </mesh>
  );
}
