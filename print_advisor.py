#!/usr/bin/env python3
"""
Print Settings Advisor for Elegoo Centauri Carbon / Elegoo Slicer
--------------------------------------------------------------
Reads an STL, analyzes its geometry, and recommends nozzle + Elegoo Slicer
settings (Quality / Strength / Speed / Support / Other) based on project type
and material.

USAGE:
    python3 print_advisor.py <file.stl> --project TYPE --material MATERIAL

PROJECT TYPES:
    decor       - bubble letters, wall panels, display pieces (cosmetic priority)
    functional  - gym brackets, pulleys, mechanical parts (strength priority)
    structural  - heavy load-bearing hardware, impact components (maximum strength/shear priority)
    figure      - action figures, articulated joints, organic sculpts (balanced, detail-aware)
    test        - quick test/calibration prints (speed priority, low material use)

MATERIALS:
    pla         - standard/basic PLA
    pla_plus    - PLA+ / Rapid PLA+
    petg        - PETG
    petg_cf     - carbon-fiber filled PETG/Nylon (abrasive - hardened nozzle only)

Build volume assumed: 256 x 256 x 256 mm (Elegoo Centauri Carbon / Carbon 2)
"""

import struct
import sys
import argparse
import numpy as np


BUILD_VOLUME = (256.0, 256.0, 256.0)

# ---------------------------------------------------------------------------
# Profile Presets Definition
# ---------------------------------------------------------------------------

PROFILE_SETTINGS = {
    "test": {
        "layer_height": 0.28,
        "wall_loops": 2,
        "sparse_infill_density": "15%",
        "sparse_infill_pattern": "grid",
        "top_shell_layers": 3,
        "bottom_shell_layers": 3,
    },
    "decor": {
        "layer_height": 0.16,
        "wall_loops": 2,
        "sparse_infill_density": "10%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": 4,
        "bottom_shell_layers": 4,
    },
    "figure": {
        "layer_height": 0.12,
        "wall_loops": 3,
        "sparse_infill_density": "15%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": 5,
        "bottom_shell_layers": 5,
    },
    "functional": {
        "layer_height": 0.20,
        "wall_loops": 4,
        "sparse_infill_density": "40%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": 5,
        "bottom_shell_layers": 5,
    },
    "structural": {
        "layer_height": 0.16,
        "wall_loops": 8,
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "rectilinear",
        "top_shell_layers": 8,
        "bottom_shell_layers": 8,
        "fan_max_speed": "40%",
        "enable_support": "1",
        "support_type": "tree_auto",
    }
}


# ---------------------------------------------------------------------------
# STL geometry analysis
# ---------------------------------------------------------------------------

def read_stl(filename):
    with open(filename, 'rb') as f:
        header = f.read(80)
        if header.strip().lower().startswith(b'solid'):
            rest = f.read(500)
            if b'facet' in rest and b'endloop' not in header:
                raise ValueError(
                    "This looks like an ASCII STL. Please export/save as binary STL."
                )
        f.seek(80)
        count = struct.unpack('<I', f.read(4))[0]

        dtype = np.dtype([
            ('normal', '<f4', (3,)),
            ('verts', '<f4', (3, 3)),
            ('attr', '<u2'),
        ])
        data = np.fromfile(f, dtype=dtype, count=count)
        if len(data) != count:
            raise ValueError(
                f"STL file looks truncated: header declares {count} triangles "
                f"but only {len(data)} could be read."
            )
        return data['verts'].astype(np.float64)


def compute_face_normals(verts):
    a = verts[:, 1] - verts[:, 0]
    b = verts[:, 2] - verts[:, 0]
    n = np.cross(a, b)
    lengths = np.linalg.norm(n, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return n / lengths


def triangle_areas(verts):
    a = verts[:, 1] - verts[:, 0]
    b = verts[:, 2] - verts[:, 0]
    return 0.5 * np.linalg.norm(np.cross(a, b), axis=1)


def mesh_volume_cm3(verts):
    v1, v2, v3 = verts[:, 0], verts[:, 1], verts[:, 2]
    signed_vols = np.einsum('ij,ij->i', v1, np.cross(v2, v3))
    return abs(signed_vols.sum() / 6.0) / 1000.0


def analyze_stl(filename):
    verts = read_stl(filename)
    normals = compute_face_normals(verts)
    all_pts = verts.reshape(-1, 3)
    mins = all_pts.min(axis=0)
    maxs = all_pts.max(axis=0)
    dims = maxs - mins

    areas = triangle_areas(verts)
    total_area = areas.sum()

    dirs = {'+X': (1, 0, 0), '-X': (-1, 0, 0), '+Y': (0, 1, 0),
            '-Y': (0, -1, 0), '+Z': (0, 0, 1), '-Z': (0, 0, -1)}
    face_scores = {}
    for name, d in dirs.items():
        d = np.array(d)
        dots = normals @ d
        mask = dots > 0.98
        face_scores[name] = areas[mask].sum()
    best_face = max(face_scores, key=face_scores.get)
    best_face_pct = 100 * face_scores[best_face] / total_area if total_area > 0 else 0

    down_dot = -normals[:, 2]
    steep_overhang_area = areas[down_dot > 0.707].sum()
    overhang_pct = 100 * steep_overhang_area / total_area if total_area > 0 else 0

    vol_cm3 = mesh_volume_cm3(verts)

    fits_bed = all(dims[i] <= BUILD_VOLUME[i] for i in range(3))
    fits_rotated = (dims[1] <= BUILD_VOLUME[0] and dims[0] <= BUILD_VOLUME[1]
                    and dims[2] <= BUILD_VOLUME[2])

    return {
        'dims': dims,
        'volume_cm3': vol_cm3,
        'triangle_count': len(verts),
        'best_face': best_face,
        'best_face_pct': best_face_pct,
        'overhang_pct': overhang_pct,
        'fits_bed': fits_bed or fits_rotated,
        'max_xy': max(dims[0], dims[1]),
        'height': dims[2],
    }


# ---------------------------------------------------------------------------
# Material base profiles
# ---------------------------------------------------------------------------

MATERIALS = {
    'pla': {
        'nozzle_temp': 205, 'bed_temp': 55, 'name': 'Basic PLA', 'abrasive': False,
    },
    'pla_plus': {
        'nozzle_temp': 210, 'bed_temp': 60, 'name': 'PLA+ / Rapid PLA+', 'abrasive': False,
    },
    'petg': {
        'nozzle_temp': 235, 'bed_temp': 75, 'name': 'PETG', 'abrasive': False,
    },
    'petg_cf': {
        'nozzle_temp': 245, 'bed_temp': 80, 'name': 'PETG-CF / Nylon-CF (abrasive)', 'abrasive': True,
    },
    'tpu': {
        'nozzle_temp': 225, 'bed_temp': 45, 'name': 'TPU (flexible)', 'abrasive': False,
        'flexible': True,
    },
    'paht_cf': {
        'nozzle_temp': 290, 'bed_temp': 90, 'name': 'PAHT-CF (high-temp nylon, carbon fiber)',
        'abrasive': True, 'hygroscopic': True, 'high_temp': True,
    },
    'ppa_cf': {
        'nozzle_temp': 300, 'bed_temp': 110, 'name': 'PPA-CF (carbon fiber)',
        'abrasive': True, 'hygroscopic': True, 'high_temp': True,
    },
    'pa12_cf': {
        'nozzle_temp': 270, 'bed_temp': 100, 'name': 'PA12-CF (carbon fiber nylon)',
        'abrasive': True, 'hygroscopic': True, 'high_temp': True,
    },
    'pa6_cf': {
        'nozzle_temp': 270, 'bed_temp': 90, 'name': 'PA6-CF (carbon fiber nylon)',
        'abrasive': True, 'hygroscopic': True, 'high_temp': True,
    },
    'pps_cf': {
        'nozzle_temp': 330, 'bed_temp': 120, 'name': 'PPS-CF (carbon fiber, very high-temp)',
        'abrasive': True, 'hygroscopic': True, 'high_temp': True, 'extreme_temp': True,
    },
}


# ---------------------------------------------------------------------------
# Orientation recommendation
# ---------------------------------------------------------------------------

def recommend_orientation(geo, project):
    reasons = []
    best_face_strong = geo['best_face_pct'] > 15

    if project in ('functional', 'structural'):
        reasons.append(
            "STRUCTURAL/LOAD-BEARING: orient so the main force direction runs ACROSS "
            "layer lines, not along them. A bracket or high-stress component under tension "
            "or bending should have layers stacked perpendicular to the pull to prevent layer splitting."
        )
        reasons.append(
            "If there are bearing/pin holes or internal bores, print them VERTICALLY "
            "where possible so holes print round without horizontal step-deformation."
        )
        if best_face_strong:
            reasons.append(
                f"Geometry suggests the {geo['best_face']} face is your most stable base — "
                "good candidate for bed contact, unless load direction dictates otherwise."
            )
        orientation = "Prioritize force-vector orientation over flatness."

    elif project == 'figure':
        reasons.append(
            "ARTICULATED/ORGANIC: orient each part so its joint axis is VERTICAL where possible."
        )
        orientation = "Prioritize joint/peg strength over flat-face placement."

    elif project == 'decor':
        if best_face_strong:
            orientation = f"Place the {geo['best_face']} face down — flattest base."
        else:
            orientation = "No strong flat face detected — orient for maximum stable footprint."

    else:  # test
        orientation = f"Quick print — place {geo['best_face']} down if flat."

    return {'summary': orientation, 'reasoning': reasons}


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

def recommend(geo, project, material_key):
    mat = MATERIALS[material_key]
    is_abrasive = mat.get('abrasive', False)
    large_flat = geo['max_xy'] > 150 and geo['height'] < 20

    prof = PROFILE_SETTINGS.get(project, PROFILE_SETTINGS['functional'])

    settings = {
        'nozzle': '0.4mm hardened steel',
        'quality': {},
        'strength': {},
        'speed': {},
        'support': {},
        'other': {},
        'notes': [],
    }

    # --- Material Notes ---
    if mat.get('hygroscopic'):
        settings['notes'].append(f"{mat['name']} requires pre-drying to avoid weak layer bonding.")
    if mat.get('high_temp'):
        settings['notes'].append(f"{mat['name']} requires {mat['nozzle_temp']}°C hotend capability.")

    # --- Nozzle ---
    if is_abrasive:
        settings['nozzle'] = '0.4mm hardened steel (required for abrasive filament)'

    # --- Quality ---
    settings['quality']['Layer height'] = f"{prof['layer_height']}mm"
    settings['quality']['First layer height'] = '0.2mm'
    settings['quality']['Seam position'] = 'Aligned (rear/hidden edge)'

    # --- Strength ---
    settings['strength']['Wall loops'] = prof['wall_loops']
    settings['strength']['Top/bottom shell layers'] = f"{prof['top_shell_layers']} / {prof['bottom_shell_layers']}"
    settings['strength']['Sparse infill density'] = prof['sparse_infill_density']
    settings['strength']['Sparse infill pattern'] = prof['sparse_infill_pattern']

    if project == 'structural':
        settings['notes'].append(
            "STRUCTURAL PROFILE: 8 wall loops + 100% rectilinear infill used for maximum "
            "shear resistance and solid wall consolidation."
        )

    # --- Speed & Cooling ---
    if project == 'structural':
        settings['speed']['Outer wall'] = '100-120mm/s (slowed for maximum layer fusion)'
        settings['speed']['Sparse infill'] = '150mm/s'
        settings['speed']['Max fan speed'] = prof.get('fan_max_speed', '40%')
        settings['notes'].append("Reduced cooling fan speed to increase thermal layer adhesion.")
    elif project == 'functional':
        settings['speed']['Outer wall'] = '120-150mm/s'
        settings['speed']['Sparse infill'] = '180mm/s'
    else:
        settings['speed']['Outer wall'] = '150-180mm/s'
        settings['speed']['Sparse infill'] = '220mm/s'

    # --- Support ---
    if geo['overhang_pct'] > 5 or project == 'structural':
        settings['support']['Enable support'] = True
        settings['support']['Type'] = prof.get('support_type', 'Tree (auto)')
        settings['support']['Threshold angle'] = '45°'

    # --- Orientation & Bed Fit ---
    settings['orientation'] = recommend_orientation(geo, project)
    if not geo['fits_bed']:
        settings['notes'].insert(0, "WARNING: part dimensions may exceed build volume.")

    return settings, mat


# ---------------------------------------------------------------------------
# Report Printer
# ---------------------------------------------------------------------------

def print_report(filename, geo, settings, mat, project):
    print("=" * 70)
    print(f"PRINT ADVISOR REPORT — {filename}")
    print("=" * 70)
    print(f"Project type   : {project}")
    print(f"Material       : {mat['name']}")
    print(f"Nozzle temp    : {mat['nozzle_temp']}°C   Bed temp: {mat['bed_temp']}°C")
    print()
    print(f"Dimensions     : {geo['dims'][0]:.1f} x {geo['dims'][1]:.1f} x {geo['dims'][2]:.1f} mm")
    print(f"Volume (solid) : {geo['volume_cm3']:.1f} cm^3")
    print(f"Overhang       : {geo['overhang_pct']:.1f}%")
    print(f"Fits bed       : {'YES' if geo['fits_bed'] else 'NO - CHECK SCALE'}")
    print()
    print(f"RECOMMENDED NOZZLE: {settings['nozzle']}")
    print()
    print("--- ORIENTATION ---")
    print(f"  {settings['orientation']['summary']}")
    for r in settings['orientation']['reasoning']:
        print(f"  * {r}")
    print()

    for section in ['quality', 'strength', 'speed', 'support']:
        print(f"--- {section.upper()} ---")
        for k, v in settings[section].items():
            print(f"  {k:.<40} {v}")
        print()

    if settings['notes']:
        print("--- NOTES ---")
        for n in settings['notes']:
            print(f"  * {n}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Elegoo Slicer settings advisor")
    parser.add_argument('stl_file', help="Path to the STL file")
    parser.add_argument(
        '--project',
        choices=['decor', 'functional', 'structural', 'figure', 'test'],
        required=True,
        help="Project target application type"
    )
    parser.add_argument(
        '--material',
        choices=list(MATERIALS.keys()),
        default='pla',
        help="Filament material"
    )
    args = parser.parse_args()

    geo = analyze_stl(args.stl_file)
    settings, mat = recommend(geo, args.project, args.material)
    print_report(args.stl_file, geo, settings, mat, args.project)


if __name__ == '__main__':
    main()
