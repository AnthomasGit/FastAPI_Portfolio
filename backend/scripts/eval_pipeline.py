#!/usr/bin/env python3
import argparse
import json
import os
import sys

import trimesh


def check_mesh(filepath):
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


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate generated 3D meshes (GLB) against M2 checks."
    )
    subparsers = parser.add_subparsers(dest="command")

    mesh_parser = subparsers.add_parser("mesh", help="Run mesh evaluation checks.")
    mesh_parser.add_argument(
        "--input", "-i", default=None, help="Path to a single GLB file"
    )
    mesh_parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.command != "mesh":
        parser.print_help()
        sys.exit(1)

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


if __name__ == "__main__":
    main()
