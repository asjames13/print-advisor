#!/usr/bin/env python3
"""
Patch a real ElegooSlicer .3mf project file with a new STL's geometry and
Print Advisor's recommended process settings.

WHY THIS EXISTS: ElegooSlicer's .3mf project format bundles a fully-flattened
config (printer + filament + process merged into one ~450-key JSON blob), not
a small diff. Generating that from scratch would mean re-implementing Orca's
entire settings-inheritance resolver by hand - too much surface area to get
right blind. Instead, this script starts from a REAL .3mf you already saved
out of ElegooSlicer (with the correct printer + filament already selected,
so every machine-limit/bed-shape/retraction default is guaranteed correct),
swaps in the new STL's mesh, and overrides only the specific settings
print_advisor.py recommends (walls, infill, supports, speeds, brim, etc).
Filament temps/flow-ratio are left untouched by default, since a calibrated
filament profile should not be overwritten by generic advice - see
--apply-material-temps if you actually want that.

USAGE:
    python3 patch_elegoo_project.py <base.3mf> <new.stl> \
        --project TYPE --material MATERIAL --out <output.3mf>

CAVEAT: verified against a real OrcaSlicer/Bambu example project file's
structure (XML layout, config shape), but NOT yet tested against an actual
Elegoo Centauri Carbon 2 project file - the array-vs-scalar shape of some
project_settings.config keys may differ. First run should be treated as a
test: open the output in ElegooSlicer and confirm it looks right before
trusting it for a real print.
"""

import argparse
import json
import re
import shutil
import defusedxml.ElementTree as ET
import zipfile
from pathlib import Path

from print_advisor import read_stl, MATERIALS
from export_elegoo_profile import slicer_overrides
from print_advisor import analyze_stl


NS = {
    '3mf': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
    'p': 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06',
}
P_PATH = '{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path'
IDENTITY = "1 0 0 0 1 0 0 0 1 0 0 0"
BUILD_VOLUME_XY = (256.0, 256.0)


def find_mesh_target(model_xml_text):
    """
    Parse the top-level 3D/3dmodel.model to find the first build item, then
    resolve whether its mesh lives directly in that file or in a separate
    /3D/Objects/*.model file referenced via a <component>. Returns
    (target_filename, target_object_id, item_object_id).
    """
    root = ET.fromstring(model_xml_text)
    build = root.find('3mf:build', NS)
    item = build.find('3mf:item', NS)
    item_objectid = item.get('objectid')

    resources = root.find('3mf:resources', NS)
    obj = resources.find(f'3mf:object[@id="{item_objectid}"]', NS)
    mesh = obj.find('3mf:mesh', NS)
    if mesh is not None:
        return '3D/3dmodel.model', item_objectid, item_objectid

    components = obj.find('3mf:components', NS)
    component = components.find('3mf:component', NS)
    target_file = component.get(P_PATH).lstrip('/')
    target_objectid = component.get('objectid')
    return target_file, target_objectid, item_objectid


def set_transform_identity(top_level_text, item_objectid, target_objectid):
    """Zero out the item's and (if present) component's transform so the new
    mesh's baked-in coordinates aren't double-transformed by leftover scale
    from the old model."""

    def replace_tag_transform(text, tag, id_attr, id_value):
        pattern = re.compile(rf'<{tag}\b[^>]*{id_attr}="{id_value}"[^>]*/>')
        m = pattern.search(text)
        if not m:
            return text
        tag_text = m.group(0)
        new_tag_text = re.sub(r'transform="[^"]*"', f'transform="{IDENTITY}"', tag_text)
        return text[:m.start()] + new_tag_text + text[m.end():]

    text = replace_tag_transform(top_level_text, 'item', 'objectid', item_objectid)
    if item_objectid != target_objectid:
        text = replace_tag_transform(text, 'component', 'objectid', target_objectid)
    return text


def build_mesh_xml(verts, translate):
    tx, ty, tz = translate
    parts = ['<mesh><vertices>']
    for tri in verts:
        for v in tri:
            parts.append(f'<vertex x="{v[0] + tx:.6f}" y="{v[1] + ty:.6f}" z="{v[2] + tz:.6f}"/>')
    parts.append('</vertices><triangles>')
    for i in range(len(verts)):
        i0, i1, i2 = 3 * i, 3 * i + 1, 3 * i + 2
        parts.append(f'<triangle v1="{i0}" v2="{i1}" v3="{i2}"/>')
    parts.append('</triangles></mesh>')
    return ''.join(parts)


def replace_mesh_in_object(text, target_objectid, new_mesh_xml):
    obj_pattern = re.compile(rf'<object id="{target_objectid}"[^>]*>.*?</object>', re.DOTALL)
    m = obj_pattern.search(text)
    if not m:
        raise ValueError(f"Could not find <object id=\"{target_objectid}\"> in target model file")
    object_block = m.group(0)
    mesh_pattern = re.compile(r'<mesh>.*?</mesh>', re.DOTALL)
    if not mesh_pattern.search(object_block):
        raise ValueError(f"Object {target_objectid} has no direct <mesh> to replace "
                          f"(unexpected nested structure)")
    new_object_block = mesh_pattern.sub(new_mesh_xml, object_block, count=1)
    return text[:m.start()] + new_object_block + text[m.end():]


def apply_overrides(config, overrides):
    changed = {}
    for key, value in overrides.items():
        if key not in config:
            config[key] = value
            changed[key] = value
            continue
        existing = config[key]
        if isinstance(existing, list):
            config[key] = [value] * len(existing)
        else:
            config[key] = value
        changed[key] = config[key]
    return changed


def mark_process_diff(config, changed_keys):
    """
    ElegooSlicer/OrcaSlicer don't trust raw values in project_settings.config
    at face value - they cross-check against "different_settings_to_system"
    (a 3-slot [printer, filament, process] list of semicolon-joined key names
    that actually differ from the named preset in print_settings_id/etc). Any
    key not listed there gets silently re-resolved from the named system
    preset on open, discarding whatever raw value we wrote. This showed up
    as our overrides appearing to have no effect at all when the project was
    reopened - the file was correct on disk, the app just didn't trust it.
    """
    diff_list = config.get('different_settings_to_system')
    if isinstance(diff_list, list) and len(diff_list) >= 3:
        existing = diff_list[2].split(';') if diff_list[2] else []
        merged = sorted(set(k for k in existing if k) | set(changed_keys))
        diff_list[2] = ';'.join(merged)
        config['different_settings_to_system'] = diff_list

    inherits_list = config.get('inherits_group')
    if isinstance(inherits_list, list) and len(inherits_list) >= 3 and not inherits_list[2]:
        inherits_list[2] = config.get('print_settings_id', '')
        config['inherits_group'] = inherits_list


def rename_process_preset(config, new_name):
    """
    print_settings_id exactly matching a real system preset name appears to
    make ElegooSlicer re-resolve the process settings from its own library on
    open, ignoring the embedded raw values in project_settings.config even
    when different_settings_to_system correctly flags them as overridden.
    Renaming to something that can't collide with any known preset forces the
    app to treat this as a standalone/modified config it must read from the
    file itself. Must be called AFTER mark_process_diff, which captures the
    original (pre-rename) preset name into inherits_group for lineage.
    """
    config['print_settings_id'] = new_name


def main():
    parser = argparse.ArgumentParser(description="Patch an ElegooSlicer .3mf with a new STL + recommended settings")
    parser.add_argument('base_3mf', help="A .3mf you saved from ElegooSlicer with the correct printer/filament selected")
    parser.add_argument('stl_file', help="The new STL to slice")
    parser.add_argument('--project', choices=['decor', 'functional', 'figure', 'test', 'structure', 'lamp'], required=True)
    parser.add_argument('--material', choices=list(MATERIALS.keys()), default='pla')
    parser.add_argument('--apply-material-temps', action='store_true',
                         help="Also override nozzle/bed temps from the material table "
                              "(off by default - a calibrated filament profile is usually better)")
    parser.add_argument('--out', default=None, help="Output .3mf path (default: <stl name>.3mf)")
    args = parser.parse_args()

    stl_path = Path(args.stl_file)
    out_path = Path(args.out) if args.out else stl_path.with_suffix('.3mf')

    geo = analyze_stl(str(stl_path))
    verts = read_stl(str(stl_path))
    mat = MATERIALS[args.material]
    overrides = slicer_overrides(geo, args.project, args.material)
    if args.apply_material_temps:
        overrides['nozzle_temperature'] = str(mat['nozzle_temp'])
        overrides['nozzle_temperature_initial_layer'] = str(mat['nozzle_temp'])
        overrides['hot_plate_temp'] = str(mat['bed_temp'])
        overrides['hot_plate_temp_initial_layer'] = str(mat['bed_temp'])

    with zipfile.ZipFile(args.base_3mf, 'r') as zin:
        names = zin.namelist()
        contents = {name: zin.read(name) for name in names}

    top_level_text = contents['3D/3dmodel.model'].decode('utf-8')
    target_file, target_objectid, item_objectid = find_mesh_target(top_level_text)
    print(f"Target mesh: object {target_objectid} in {target_file}")

    all_pts = verts.reshape(-1, 3)
    mins = all_pts.min(axis=0)
    maxs = all_pts.max(axis=0)
    center = (mins + maxs) / 2
    translate = (
        BUILD_VOLUME_XY[0] / 2 - center[0],
        BUILD_VOLUME_XY[1] / 2 - center[1],
        -mins[2],
    )
    new_mesh_xml = build_mesh_xml(verts, translate)

    if target_file == '3D/3dmodel.model':
        new_target_text = replace_mesh_in_object(top_level_text, target_objectid, new_mesh_xml)
        top_level_text = set_transform_identity(new_target_text, item_objectid, target_objectid)
        contents['3D/3dmodel.model'] = top_level_text.encode('utf-8')
    else:
        target_text = contents[target_file].decode('utf-8')
        target_text = replace_mesh_in_object(target_text, target_objectid, new_mesh_xml)
        contents[target_file] = target_text.encode('utf-8')
        top_level_text = set_transform_identity(top_level_text, item_objectid, target_objectid)
        contents['3D/3dmodel.model'] = top_level_text.encode('utf-8')

    project_settings = json.loads(contents['Metadata/project_settings.config'])
    changed = apply_overrides(project_settings, overrides)
    mark_process_diff(project_settings, changed.keys())
    process_preset_name = f"{args.project.capitalize()} {mat['name'].split(' ')[0]} (Print Advisor)"
    rename_process_preset(project_settings, process_preset_name)
    contents['Metadata/project_settings.config'] = json.dumps(project_settings, indent=4).encode('utf-8')

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, contents[name])

    print(f"\nWrote {out_path}")
    print(f"Mesh: {geo['triangle_count']} triangles, "
          f"{geo['dims'][0]:.1f}x{geo['dims'][1]:.1f}x{geo['dims'][2]:.1f}mm, "
          f"centered on plate, resting on Z=0")
    print(f"\nOverridden settings ({len(changed)}):")
    for k, v in changed.items():
        print(f"  {k}: {v}")
    if not args.apply_material_temps:
        print("\nFilament temps left as-is (base project's own filament profile). "
              "Pass --apply-material-temps to override with the material table instead.")
    print(f"\nOpen {out_path} directly in ElegooSlicer to check it before printing.")


if __name__ == '__main__':
    main()
