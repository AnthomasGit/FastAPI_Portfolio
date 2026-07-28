// Super 35 sensor width (mm) — the cinema-standard gauge focal lengths are
// calibrated against. Used to convert focal length (mm) to a vertical FOV.
export const SUPER35_GAUGE = 24.89;

export const FOCAL_LENGTHS = [18, 24, 35, 50, 85, 100];

// Single source of truth for output aspect + capture dimensions. The PiP,
// the shot frustum gizmo, and Capture all derive framing from here.
export const FORMATS = [
  { id: '16:9', label: 'Cinema 16:9', aspect: 16 / 9, capture: [1024, 576] },
  { id: '9:16', label: 'Phone 9:16', aspect: 9 / 16, capture: [576, 1024] },
  { id: '2.39:1', label: 'Anamorphic 2.39:1', aspect: 2.39, capture: [1024, 428] },
  { id: '1:1', label: 'Square 1:1', aspect: 1, capture: [768, 768] },
  { id: '4:5', label: 'Portrait 4:5', aspect: 4 / 5, capture: [768, 960] },
];

export const DEFAULT_FORMAT = '16:9';
export const DEFAULT_FOCAL_LENGTH = 35;

export function getFormat(id) {
  return FORMATS.find((f) => f.id === id) || FORMATS[0];
}

// Corner picture-in-picture layout, shared by the WebGL scissor render and the
// HTML label/border overlay so they line up exactly.
export const PIP_MAX = 220;    // px, longest edge of the preview
export const PIP_MARGIN = 16;  // px inset from the canvas edges

export function pipSize(aspect, scale = 1) {
  const longest = PIP_MAX * scale;
  return aspect >= 1
    ? { pw: longest, ph: longest / aspect }
    : { pw: longest * aspect, ph: longest };
}

// Largest centered rect of the given aspect that fits in (width, height) — the
// through-the-lens gate. Offsets are symmetric, so they hold for both WebGL
// (bottom-left origin) and DOM (top-left origin) coordinates.
export function gateRect(aspect, width, height) {
  let gw = width;
  let gh = width / aspect;
  if (gh > height) {
    gh = height;
    gw = height * aspect;
  }
  return { x: (width - gw) / 2, y: (height - gh) / 2, gw, gh };
}

// Vertical FOV (degrees) for a focal length on a Super 35 sensor at the given
// aspect. The gauge is the horizontal film dimension, so the horizontal FOV is
// derived from it and the vertical FOV follows from the aspect ratio.
export function focalLengthToFov(focalLength, aspect) {
  const hFov = 2 * Math.atan(SUPER35_GAUGE / (2 * focalLength));
  const vFov = 2 * Math.atan(Math.tan(hFov / 2) / aspect);
  return (vFov * 180) / Math.PI;
}
