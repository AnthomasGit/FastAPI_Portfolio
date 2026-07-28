// Live shot-camera pose while piloting. Mutated at frame rate by PilotControls
// and read inside useFrame loops (ShotPreview render, frustum sync) — kept
// outside React/zustand so flying the camera causes zero re-renders or store
// writes. Committed to the store once, on pilot exit.
export const pilotState = {
  active: false,
  pos: [5, 5, 5],
  yaw: 0,          // radians, rotation around +Y; 0 faces -Z
  pitch: 0,        // radians, clamped to ±89°
  targetDistance: 5, // camera↔target distance at entry, reused on commit
};

// Direction the camera looks for a given yaw/pitch (unit vector).
export function forwardVector(yaw, pitch) {
  const cp = Math.cos(pitch);
  return [-Math.sin(yaw) * cp, Math.sin(pitch), -Math.cos(yaw) * cp];
}

// Seed the pose from a stored shot camera ({position, target}).
export function seedFromCamera(camera) {
  const pos = camera?.position || [5, 5, 5];
  const target = camera?.target || [0, 0, 0];
  const dx = target[0] - pos[0];
  const dy = target[1] - pos[1];
  const dz = target[2] - pos[2];
  const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 5;

  pilotState.pos = [...pos];
  pilotState.yaw = Math.atan2(-dx, -dz);
  pilotState.pitch = Math.asin(Math.max(-1, Math.min(1, dy / dist)));
  pilotState.targetDistance = dist;
  pilotState.active = true;
}

// The {position, target} to persist when piloting ends.
export function commitPose() {
  const [fx, fy, fz] = forwardVector(pilotState.yaw, pilotState.pitch);
  const d = pilotState.targetDistance;
  const pos = pilotState.pos;
  pilotState.active = false;
  return {
    position: [...pos],
    target: [pos[0] + fx * d, pos[1] + fy * d, pos[2] + fz * d],
  };
}
