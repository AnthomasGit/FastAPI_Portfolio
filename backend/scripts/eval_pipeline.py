#!/usr/bin/env python3
import argparse
import json
import os
import sys


def check_mesh(filepath):
    import trimesh

    report = {"file": filepath, "checks": {}, "passed": True}

    # 1. Loads successfully
    try:
        mesh = trimesh.load(filepath, force="mesh")
    except Exception as e:
        report["checks"]["loads"] = {"passed": False, "error": str(e)}
        report["passed"] = False
        return report
    report["checks"]["loads"] = {"passed": True}

    # 2. Vertex count in sane band (100 – 200,000)
    vertices = mesh.vertices
    vert_count = len(vertices)
    vert_ok = 100 <= vert_count <= 200000
    report["checks"]["vertex_count"] = {
        "passed": vert_ok,
        "count": vert_count,
    }
    if not vert_ok:
        report["passed"] = False

    # 3. Bounding-box aspect ratio — no dimension more than 10× another
    extents = mesh.bounding_box.extents
    max_extent = max(extents)
    min_extent = min(extents)
    ratio = max_extent / min_extent if min_extent > 0 else float("inf")
    aspect_ok = min_extent > 0 and ratio <= 10.0
    report["checks"]["aspect_ratio"] = {
        "passed": aspect_ok,
        "extents": extents.tolist(),
        "ratio": ratio,
    }
    if not aspect_ok:
        report["passed"] = False

    # 4. Texture present
    texture_ok = False
    if hasattr(mesh, "materials") and mesh.materials:
        for mat in mesh.materials:
            if mat is None:
                continue
            if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                texture_ok = True
                break
            if hasattr(mat, "image") and mat.image is not None:
                texture_ok = True
                break
    if not texture_ok and hasattr(mesh, "visual") and mesh.visual is not None:
        mat = getattr(mesh.visual, "material", None)
        if mat is not None:
            if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                texture_ok = True
            if hasattr(mat, "image") and mat.image is not None:
                texture_ok = True
    report["checks"]["texture"] = {"passed": texture_ok}
    if not texture_ok:
        report["passed"] = False

    # 5. Hole count — warn if > 10 boundary loops
    boundary_edges = mesh.boundary_edges
    estimated_loops = len(boundary_edges) // 2
    hole_ok = estimated_loops <= 10
    report["checks"]["holes"] = {
        "passed": hole_ok,
        "boundary_edges": len(boundary_edges),
        "estimated_boundary_loops": estimated_loops,
        "watertight": mesh.is_watertight,
    }
    if not hole_ok:
        report["passed"] = False

    return report


# ── Controlled-image composition adherence (M4, LLD §9) ─────────────────
#
# Re-estimates depth on a generated output image and correlates it against
# the conditioning depth map that steered the generation. The estimator is
# pluggable and optional: if its model/deps are absent, the check is
# SKIPPED cleanly (exit 0) rather than failing the run.


def _load_midas_estimator():
    """MiDaS small via torch.hub. Returns callable(rgb_uint8) -> depth float
    array (higher = closer), or None if torch/model unavailable."""
    try:
        import torch
    except ImportError:
        print("controlled: torch not installed — depth estimator unavailable")
        return None
    try:
        model = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
        transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
    except Exception as e:
        print(f"controlled: could not load MiDaS model ({e})")
        return None
    model.eval()
    transform = transforms.small_transform

    def estimate(rgb):
        with torch.no_grad():
            batch = transform(rgb)
            prediction = model(batch)
        return prediction.squeeze().cpu().numpy()

    return estimate


ESTIMATOR_LOADERS = {"midas": _load_midas_estimator}


def get_depth_estimator(name):
    """Resolve --estimator into a callable or None (unavailable/disabled)."""
    if name == "none":
        return None
    if name == "auto":
        for loader in ESTIMATOR_LOADERS.values():
            estimator = loader()
            if estimator is not None:
                return estimator
        return None
    loader = ESTIMATOR_LOADERS.get(name)
    return loader() if loader else None


def _normalize(arr):
    import numpy as np

    arr = arr.astype("float64")
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def check_controlled(depth_path, output_path, estimator, threshold):
    """Correlate the conditioning depth map with depth re-estimated from the
    generated image. Both maps use the near=bright convention."""
    import numpy as np
    from PIL import Image

    report = {
        "depth": depth_path,
        "output": output_path,
        "checks": {},
        "passed": True,
    }

    try:
        conditioning = np.array(Image.open(depth_path).convert("L"))
        output_rgb = np.array(Image.open(output_path).convert("RGB"))
    except Exception as e:
        report["checks"]["loads"] = {"passed": False, "error": str(e)}
        report["passed"] = False
        return report
    report["checks"]["loads"] = {"passed": True}

    try:
        estimated = estimator(output_rgb)
    except Exception as e:
        report["checks"]["depth_estimation"] = {"passed": False, "error": str(e)}
        report["passed"] = False
        return report
    report["checks"]["depth_estimation"] = {"passed": True}

    estimated_img = Image.fromarray(_normalize(estimated) * 255.0).convert("L")
    estimated_resized = np.array(
        estimated_img.resize((conditioning.shape[1], conditioning.shape[0]))
    )

    a = _normalize(conditioning).ravel()
    b = _normalize(estimated_resized).ravel()
    if a.std() < 1e-9 or b.std() < 1e-9:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(a, b)[0, 1])

    corr_ok = correlation >= threshold
    report["checks"]["composition_adherence"] = {
        "passed": corr_ok,
        "pearson_r": correlation,
        "threshold": threshold,
    }
    if not corr_ok:
        report["passed"] = False

    return report


def _discover_controlled_pairs(golden_dir):
    """Find (<name>_depth.png, <name>_output.png) pairs in golden/controlled/."""
    pairs = []
    if not os.path.isdir(golden_dir):
        return pairs
    for fname in sorted(os.listdir(golden_dir)):
        if fname.endswith("_depth.png"):
            output = os.path.join(
                golden_dir, fname[: -len("_depth.png")] + "_output.png"
            )
            if os.path.exists(output):
                pairs.append((os.path.join(golden_dir, fname), output))
    return pairs


def run_controlled(args):
    if args.depth or args.output:
        if not (args.depth and args.output):
            print("controlled: --depth and --output must be given together",
                  file=sys.stderr)
            sys.exit(1)
        pairs = [(args.depth, args.output)]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        golden_dir = os.path.join(script_dir, "golden", "controlled")
        pairs = _discover_controlled_pairs(golden_dir)
        if not pairs:
            print(f"No *_depth.png / *_output.png pairs found in {golden_dir}",
                  file=sys.stderr)
            sys.exit(1)

    estimator = get_depth_estimator(args.estimator)
    if estimator is None:
        print("SKIPPED: no depth estimator available "
              f"(--estimator {args.estimator}); composition check not run")
        sys.exit(0)

    all_passed = True
    for depth_path, output_path in pairs:
        report = check_controlled(depth_path, output_path, estimator, args.threshold)
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            all_passed = False

    sys.exit(0 if all_passed else 1)


def run_mesh(args):
    if args.input:
        files = [args.input]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        golden_dir = os.path.join(script_dir, "golden")
        if not os.path.isdir(golden_dir):
            print(f"Error: golden/ directory not found at {golden_dir}", file=sys.stderr)
            sys.exit(1)
        files = [
            os.path.join(golden_dir, f)
            for f in sorted(os.listdir(golden_dir))
            if f.endswith(".glb")
        ]
        if not files:
            print(f"No .glb files found in {golden_dir}", file=sys.stderr)
            sys.exit(1)

    all_passed = True
    reports = []
    for filepath in files:
        report = check_mesh(filepath)
        reports.append(report)
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            all_passed = False
        if args.verbose:
            print()

    sys.exit(0 if all_passed else 1)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate pipeline outputs (M2 mesh checks, M4 controlled-image checks)."
    )
    subparsers = parser.add_subparsers(dest="command")

    mesh_parser = subparsers.add_parser("mesh", help="Run mesh evaluation checks.")
    mesh_parser.add_argument(
        "--input", "-i", default=None, help="Path to a single GLB file"
    )
    mesh_parser.add_argument("--verbose", "-v", action="store_true")

    controlled_parser = subparsers.add_parser(
        "controlled",
        help="Score composition adherence of controlled generations "
             "(conditioning depth vs. depth re-estimated from the output).",
    )
    controlled_parser.add_argument(
        "--depth", default=None, help="Path to a single conditioning depth PNG"
    )
    controlled_parser.add_argument(
        "--output", default=None, help="Path to the generated image for --depth"
    )
    controlled_parser.add_argument(
        "--estimator", default="auto", choices=["auto", "midas", "none"],
        help="Depth estimator to run on outputs (default: auto; "
             "skips cleanly if unavailable)",
    )
    controlled_parser.add_argument(
        "--threshold", type=float, default=0.4,
        help="Minimum Pearson correlation to pass (default 0.4, deliberately loose)",
    )

    args = parser.parse_args()

    if args.command == "mesh":
        run_mesh(args)
    elif args.command == "controlled":
        run_controlled(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
