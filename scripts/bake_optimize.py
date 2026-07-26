"""Headless Blender mesh web-optimizer for Storyboard Pro.

Turns a heavy AI-generated GLB (TRELLIS/Hunyuan3D: ~400k tris, 2048 textures)
into a lightweight, web-ready GLB:

    decimate -> bake normal map -> export -> gltf-transform (meshopt + WebP)

Geometry is crushed to a target triangle budget while a normal map baked from
the original high-poly surface preserves the look. Textures are kept at full
resolution (they condition downstream generation), with the normal map left
lossless. Output uses EXT_meshopt_compression + KHR_mesh_quantization +
EXT_texture_webp — all loadable by three.js / @react-three/drei with no extra
frontend wiring.

Run:
    blender -b --python bake_optimize.py -- \
        --input /abs/in.glb --output /abs/out.glb [--target-tris 20000] ...

On success prints a single line ``RESULT_JSON:{...}`` to stdout and exits 0.
On failure prints ``ERROR: ...`` to stderr and exits 1.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import bpy


def _argv_after_ddash():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def parse_args():
    p = argparse.ArgumentParser(description="Blender headless mesh web-optimizer")
    p.add_argument("--input", required=True, help="Absolute path to source GLB")
    p.add_argument("--output", required=True, help="Absolute path to write optimized GLB")
    p.add_argument("--target-tris", type=int, default=20000)
    # normal map only aids editor viewport shading (it never reaches generation),
    # so 1024 lossless is plenty; baseColor is kept at --texture-size for fidelity.
    p.add_argument("--normal-size", type=int, default=1024)
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--reuv", action="store_true",
                   help="Smart-UV-project the low-poly and also re-bake albedo (for meshes with bad/no UVs)")
    p.add_argument("--no-web", action="store_true",
                   help="Skip the gltf-transform meshopt/WebP pass; emit the raw Blender GLB")
    p.add_argument("--gltf-transform-bin", default=None,
                   help="Path to the gltf-transform CLI (defaults to PATH lookup)")
    return p.parse_args(_argv_after_ddash())


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def tri_count(obj):
    return sum(len(poly.vertices) - 2 for poly in obj.data.polygons)


def import_and_join(input_path):
    """Import the GLB and merge all mesh objects into one high-poly object."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=input_path)
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh objects found in the imported GLB")

    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    hi = meshes[0]
    bpy.context.view_layer.objects.active = hi
    if len(meshes) > 1:
        bpy.ops.object.join()
    hi = bpy.context.view_layer.objects.active
    hi.name = "HI"

    # drop leftover empties / non-mesh imports so only HI remains
    for o in list(bpy.data.objects):
        if o is not hi and o in imported:
            bpy.data.objects.remove(o, do_unlink=True)
    return hi


def _apply_collapse(lo, ratio):
    mod = lo.modifiers.new("Decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.use_collapse_triangulate = True
    mod.ratio = ratio
    bpy.ops.object.select_all(action="DESELECT")
    lo.select_set(True)
    bpy.context.view_layer.objects.active = lo
    bpy.ops.object.modifier_apply(modifier=mod.name)


def decimate_copy(hi, target_tris):
    """Duplicate HI and collapse-decimate the copy toward target_tris.

    Collapse can stall well above target on disconnected / non-manifold shells
    (common in image-to-3D output), so iterate a few passes until close, or
    until a pass makes no further progress.
    """
    bpy.ops.object.select_all(action="DESELECT")
    hi.select_set(True)
    bpy.context.view_layer.objects.active = hi
    bpy.ops.object.duplicate()
    lo = bpy.context.view_layer.objects.active
    lo.name = "LO"

    orig = tri_count(lo)
    current = orig
    for _ in range(5):
        if current <= target_tris * 1.15:
            break
        ratio = max(0.02, target_tris / current)
        _apply_collapse(lo, ratio)
        new = tri_count(lo)
        if new >= current:  # no progress this pass; stop to avoid a dead loop
            break
        current = new
    eff_ratio = round(current / orig, 5) if orig else 1.0
    return lo, orig, eff_ratio


def ensure_uv(lo, force_reuv):
    if force_reuv or not lo.data.uv_layers:
        bpy.ops.object.select_all(action="DESELECT")
        lo.select_set(True)
        bpy.context.view_layer.objects.active = lo
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        return True
    return False


def _principled(nt):
    return next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)


def prepare_lo_material(lo):
    """Give LO its own material copy so baking doesn't touch the shared HI material."""
    me = lo.data
    if me.materials and me.materials[0]:
        mat = me.materials[0].copy()
        me.materials[0] = mat
    else:
        mat = bpy.data.materials.new("LO_Mat")
        me.materials.clear()
        me.materials.append(mat)
    mat.name = "LO_Mat"
    mat.use_nodes = True
    return mat


def _add_bake_image(mat, name, size, non_color):
    img = bpy.data.images.new(name, size, size, alpha=False)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    nt = mat.node_tree
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    for n in nt.nodes:
        n.select = False
    node.select = True
    nt.nodes.active = node
    return img, node


def bake_selected_to_active(hi, lo, bake_type):
    bpy.ops.object.select_all(action="DESELECT")
    hi.select_set(True)
    lo.select_set(True)
    bpy.context.view_layer.objects.active = lo
    bpy.ops.object.bake(type=bake_type)


def configure_cycles_for_bake(normal_size):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    bake = scene.render.bake
    bake.use_selected_to_active = True
    bake.cage_extrusion = 0.03
    bake.max_ray_distance = 0.05
    bake.margin = max(4, normal_size // 256)
    bake.use_clear = True


def save_image_to_tmp(img, tmpdir, filename):
    path = os.path.join(tmpdir, filename)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    # reload as file-backed so the glTF exporter embeds it reliably
    img.source = "FILE"
    img.filepath = path
    return path


def export_glb(lo, out_path):
    bpy.ops.object.select_all(action="DESELECT")
    lo.select_set(True)
    bpy.context.view_layer.objects.active = lo
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_normals=True,
        export_texcoords=True,
        export_tangents=True,
        export_materials="EXPORT",
        export_yup=True,
    )


def run_gltf_transform(bin_path, blender_glb, output, texture_size):
    """WebP the color slots (normal stays lossless), then meshopt-compress LAST.

    Order matters: meshopt encoding must be the final write, otherwise a later
    pass (e.g. `webp`) re-serialises the file and drops EXT_meshopt_compression.
    """
    gt = bin_path or shutil.which("gltf-transform")
    if not gt:
        # No CLI available: the Blender GLB is still a valid (larger) result.
        shutil.copy2(blender_glb, output)
        return False

    tmp_webp = output + ".webp.glb"
    # 1) WebP only the color-ish slots; leave normalTexture lossless.
    subprocess.run(
        [gt, "webp", blender_glb, tmp_webp,
         "--slots", "{baseColorTexture,metallicRoughnessTexture,emissiveTexture,occlusionTexture}"],
        check=True, capture_output=True, text=True,
    )
    # 2) geometry compression + cleanup LAST so EXT_meshopt_compression survives.
    subprocess.run(
        [gt, "optimize", tmp_webp, output,
         "--compress", "meshopt",
         "--texture-size", str(texture_size),
         "--texture-compress", "false",
         "--simplify", "false"],
        check=True, capture_output=True, text=True,
    )
    try:
        os.remove(tmp_webp)
    except OSError:
        pass
    return True


def main():
    args = parse_args()
    in_path = os.path.abspath(args.input)
    out_path = os.path.abspath(args.output)
    if not os.path.isfile(in_path):
        raise RuntimeError(f"Input GLB not found: {in_path}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    in_bytes = os.path.getsize(in_path)

    reset_scene()
    hi = import_and_join(in_path)
    lo, orig_tris, ratio = decimate_copy(hi, args.target_tris)
    reuved = ensure_uv(lo, args.reuv)

    mat = prepare_lo_material(lo)

    with tempfile.TemporaryDirectory() as tmpdir:
        configure_cycles_for_bake(args.normal_size)

        # albedo re-bake first (only when we changed UVs and thus broke the original mapping)
        if reuved:
            alb_img, _ = _add_bake_image(mat, "LO_Albedo", args.texture_size, non_color=False)
            bake_selected_to_active(hi, lo, "DIFFUSE")
            save_image_to_tmp(alb_img, tmpdir, "albedo.png")
            nt = mat.node_tree
            bsdf = _principled(nt)
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = alb_img
            if bsdf:
                nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

        # normal bake
        norm_img, _ = _add_bake_image(mat, "LO_Normal", args.normal_size, non_color=True)
        bake_selected_to_active(hi, lo, "NORMAL")
        save_image_to_tmp(norm_img, tmpdir, "normal.png")

        nt = mat.node_tree
        bsdf = _principled(nt)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        norm_node = next(n for n in nt.nodes
                         if n.type == "TEX_IMAGE" and n.image is norm_img)
        nt.links.new(norm_node.outputs["Color"], nmap.inputs["Color"])
        if bsdf:
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

        blender_glb = os.path.join(tmpdir, "blender_export.glb")
        export_glb(lo, blender_glb)

        if args.no_web:
            shutil.copy2(blender_glb, out_path)
            web = False
        else:
            web = run_gltf_transform(
                args.gltf_transform_bin, blender_glb, out_path, args.texture_size
            )

    out_bytes = os.path.getsize(out_path)
    result = {
        "input": in_path,
        "output": out_path,
        "orig_tris": orig_tris,
        "target_tris": args.target_tris,
        "decimate_ratio": round(ratio, 5),
        "lo_tris": tri_count(lo),
        "reuv": reuved,
        "in_bytes": in_bytes,
        "out_bytes": out_bytes,
        "web_compressed": web,
    }
    print("RESULT_JSON:" + json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"ERROR: gltf-transform failed: {e}\n{e.stderr or ''}\n")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - headless entrypoint, surface everything
        import traceback
        sys.stderr.write("ERROR: " + str(e) + "\n")
        traceback.print_exc()
        sys.exit(1)
