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
    functional  - gym brackets, pulleys, load-bearing mechanical parts (strength priority)
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
# STL geometry analysis
# ---------------------------------------------------------------------------

def read_stl(filename):
    with open(filename, 'rb') as f:
        header = f.read(80)
        # Detect ASCII STL (rare for sliced exports, but handle gracefully)
        if header.strip().lower().startswith(b'solid'):
            rest = f.read(500)
            if b'facet' in rest and b'endloop' not in header:
                raise ValueError(
                    "This looks like an ASCII STL. Please export/save as binary STL "
                    "(most CAD tools default to binary; check your export settings)."
                )
        f.seek(80)
        count = struct.unpack('<I', f.read(4))[0]

        # Binary STL triangle record: 3 normal floats, 9 vertex floats, 1 uint16
        # attribute byte count. Read all triangles in one vectorized call instead
        # of looping in Python (per-triangle struct.unpack is very slow on
        # meshes with tens/hundreds of thousands of triangles).
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
    """
    Derive each triangle's normal from its own vertices rather than trusting
    the normal stored in the STL file. Many exporters (and the STL spec itself
    treats this as valid) write all-zero normal vectors and expect the reader
    to compute the real normal from vertex winding order. Trusting a zero
    vector directly would silently zero out overhang% and flattest-face
    detection on those files.
    """
    a = verts[:, 1] - verts[:, 0]
    b = verts[:, 2] - verts[:, 0]
    n = np.cross(a, b)
    lengths = np.linalg.norm(n, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0  # degenerate triangle; area will be 0 anyway
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

    # Flattest face detection (6 cardinal directions)
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

    # Overhang estimate in current (as-uploaded) orientation
    down_dot = -normals[:, 2]
    steep_overhang_area = areas[down_dot > 0.707].sum()
    overhang_pct = 100 * steep_overhang_area / total_area if total_area > 0 else 0

    vol_cm3 = mesh_volume_cm3(verts)

    fits_bed = all(dims[i] <= BUILD_VOLUME[i] for i in range(3))
    # Also check if it fits with a 90-degree rotation about Z (swap X/Y)
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
    """
    Layer lines are always weakest in the Z (vertical/build) direction — PLA parts
    split along layer lines under tension/bending far more easily than across them.
    So orientation advice differs by what the part actually has to survive.
    """
    reasons = []
    best_face_strong = geo['best_face_pct'] > 15

    if project == 'functional':
        reasons.append(
            "FUNCTIONAL/LOAD-BEARING: orient so the main force direction runs ACROSS "
            "layer lines, not along them. A bracket that gets pulled/bent should have "
            "its layers stacked perpendicular to the pull, not parallel — parallel layers "
            "split apart under load like a stack of paper being peeled."
        )
        reasons.append(
            "If there's a bearing/pin hole, print it with the hole axis VERTICAL (drilled "
            "through the layers) rather than horizontal — horizontal round holes print as "
            "slight ellipses due to layer stepping and need reaming; vertical holes come "
            "out rounder."
        )
        if best_face_strong:
            reasons.append(
                f"Geometry suggests the {geo['best_face']} face is your most stable, flattest "
                "base — good candidate for the bed-contact face, but override this if it "
                "conflicts with the load-direction rule above."
            )
        orientation = "Prioritize load-direction over flatness — see notes."

    elif project == 'figure':
        reasons.append(
            "ARTICULATED/ORGANIC: orient each part so its peg/socket joint axis is "
            "VERTICAL where possible — round joint holes print rounder and peg pins are "
            "stronger when the layers run along the pin's length rather than stacking "
            "across it (a horizontal pin is weak and snaps at the layer lines easily)."
        )
        reasons.append(
            "For torso/limb pieces with a 'front' cosmetic side, that face doesn't need "
            "to touch the bed — prioritize joint strength over surface finish, since "
            "supports can be sanded but a snapped peg can't be un-snapped."
        )
        orientation = "Prioritize joint/peg strength over flat-face placement."

    elif project == 'decor':
        if best_face_strong:
            orientation = f"Place the {geo['best_face']} face down — it's your most stable, flattest base."
            reasons.append(
                f"{geo['best_face']} face covers {geo['best_face_pct']:.0f}% of surface area — "
                "good bed contact for adhesion and minimal warping risk."
            )
        else:
            orientation = "No strong flat face detected — orient by eye for the most stable footprint."
            reasons.append(
                "Rounded/organic shape — pick the orientation with the largest, most even "
                "bed contact area rather than trusting auto-lay-flat."
            )
        reasons.append(
            "Cosmetic priority: keep the 'front' or most-visible face UP or to the side, "
            "away from the bed and away from support contact, to avoid support marks or "
            "PEI-texture marking on the surface people will actually see."
        )

    elif project == 'lamp':
        orientation = f"Place the {geo['best_face']} opening/base face down for the most even wall thickness top to bottom."
        reasons.append(
            "Light-diffusing shells print most evenly with the part standing upright on its "
            "widest stable opening — printing on its side introduces visible banding where "
            "layer lines catch the light differently."
        )

    else:  # test
        orientation = f"Quick/practical — place the {geo['best_face']} face down if it's reasonably flat, otherwise whatever orients fastest."
        reasons.append(
            "Test print priority is speed and info, not perfection — don't over-optimize orientation here."
        )

    return {'summary': orientation, 'reasoning': reasons}


# ---------------------------------------------------------------------------
# Project-type rule sets
# ---------------------------------------------------------------------------

def recommend(geo, project, material_key):
    mat = MATERIALS[material_key]
    is_abrasive = mat.get('abrasive', False)
    large_flat = geo['max_xy'] > 150 and geo['height'] < 20
    small_part = geo['max_xy'] < 60

    settings = {
        'nozzle': '0.4mm hardened steel',
        'quality': {},
        'strength': {},
        'speed': {},
        'support': {},
        'other': {},
        'notes': [],
    }

    # --- Material-specific handling notes ---
    if mat.get('hygroscopic'):
        settings['notes'].append(
            f"{mat['name']} absorbs moisture readily — dry the spool before printing "
            "(filament dryer or oven-dry per manufacturer spec) or expect popping/stringing/weak layers."
        )
    if mat.get('high_temp'):
        settings['notes'].append(
            f"{mat['name']} needs {mat['nozzle_temp']}°C at the nozzle — confirm your hotend "
            "is rated above this (check for an all-metal / high-temp-capable hotend, not just "
            "a standard PTFE-lined one) before running a full print."
        )
    if mat.get('extreme_temp'):
        settings['notes'].append(
            f"WARNING: {mat['name']} typically wants {mat['nozzle_temp']}°C+, which is at or "
            "beyond the stock Centauri Carbon nozzle's ~350°C ceiling once you add any margin. "
            "Verify your specific hotend/nozzle combo is rated for this before attempting — "
            "this may not be printable on stock hardware without an upgraded hotend."
        )
    if mat.get('flexible'):
        settings['notes'].append(
            f"{mat['name']} is flexible — print slower (40-60mm/s outer wall), reduce retraction "
            "distance, and expect more tuning time than rigid filaments. Direct-drive extruders "
            "handle TPU far better than bowden setups."
        )

    # --- Nozzle selection ---
    if is_abrasive:
        settings['nozzle'] = '0.4mm hardened steel (required for abrasive filament)'
        settings['notes'].append(
            "Abrasive filament selected — hardened steel nozzle only, brass will wear fast."
        )
    elif project == 'decor' and geo['max_xy'] > 100:
        settings['nozzle'] = '0.6mm hardened steel'
        settings['notes'].append(
            "Large decor piece — 0.6mm nozzle trades fine detail for speed, worth it here."
        )
    elif project == 'figure' and small_part:
        settings['nozzle'] = '0.4mm (or 0.2mm if very fine facial/detail work)'

    # --- Quality tab ---
    if project == 'figure':
        settings['quality']['Layer height'] = '0.16mm'
        settings['quality']['First layer height'] = '0.2mm'
    elif project == 'test':
        settings['quality']['Layer height'] = '0.2mm'
        settings['quality']['First layer height'] = '0.24mm'
    elif project == 'lamp':
        settings['quality']['Layer height'] = '0.16mm'
        settings['quality']['First layer height'] = '0.2mm'
        settings['notes'].append(
            "Thinner layer height (0.16mm) gives smoother, more even light diffusion "
            "through the walls than the usual 0.2mm default."
        )
    else:
        settings['quality']['Layer height'] = '0.2mm'
        settings['quality']['First layer height'] = '0.2mm'

    settings['quality']['Seam position'] = (
        'Aligned (rear/hidden edge)' if project in ('decor', 'functional', 'lamp')
        else 'Random (breaks up seam on organic surface)'
    )
    if project == 'decor':
        settings['quality']['Ironing type'] = 'Top surfaces only (for gloss-prep letters/panels)'
    else:
        settings['quality']['Ironing type'] = 'No ironing'

    if large_flat:
        settings['quality']['Elephant foot compensation'] = '0.15-0.2mm'
        settings['notes'].append(
            "Large flat footprint — bumped elephant foot compensation to fight first-layer squish-out."
        )

    # --- Strength tab ---
    if project == 'functional':
        settings['strength']['Wall loops'] = 4
        settings['strength']['Top/bottom shell layers'] = 5
        settings['strength']['Sparse infill density'] = '40-60%'
        settings['strength']['Sparse infill pattern'] = 'Gyroid or Cubic'
        settings['notes'].append(
            "Load-bearing part — walls and infill both pushed up for real strength."
        )
    elif project == 'figure':
        settings['strength']['Wall loops'] = 2
        settings['strength']['Top/bottom shell layers'] = 3
        settings['strength']['Sparse infill density'] = '15-20%'
        settings['strength']['Sparse infill pattern'] = 'Gyroid'
    elif project == 'decor':
        settings['strength']['Wall loops'] = 3
        settings['strength']['Top/bottom shell layers'] = 4
        settings['strength']['Sparse infill density'] = '15-20%'
        settings['strength']['Sparse infill pattern'] = 'Gyroid'
    elif project == 'lamp':
        settings['strength']['Wall loops'] = 2
        settings['strength']['Top/bottom shell layers'] = 0
        settings['strength']['Sparse infill density'] = '0%'
        settings['strength']['Sparse infill pattern'] = 'N/A (hollow shell)'
        settings['notes'].append(
            "No infill and no top/bottom shell — a lamp shade is meant to stay hollow so "
            "light passes through the thin walls evenly. If the design needs a solid base "
            "for a bulb socket, add a modifier/cut in-slicer for just that section rather "
            "than infilling the whole part."
        )
    else:  # test
        settings['strength']['Wall loops'] = 2
        settings['strength']['Top/bottom shell layers'] = 3
        settings['strength']['Sparse infill density'] = '10-15%'
        settings['strength']['Sparse infill pattern'] = 'Grid (fast, default)'

    if mat.get('flexible'):
        settings['strength']['Wall loops'] = max(settings['strength']['Wall loops'], 3)

    # --- Speed tab ---
    if project == 'test':
        settings['speed']['Outer wall'] = '180-200mm/s'
        settings['speed']['Sparse infill'] = '250mm/s'
        settings['notes'].append("Test print — leaned into speed since quality bar is lower.")
    elif project == 'functional':
        settings['speed']['Outer wall'] = '120-150mm/s'
        settings['speed']['Sparse infill'] = '180mm/s'
        settings['notes'].append("Functional part — speed pulled back slightly for layer adhesion/strength.")
    elif project == 'figure':
        settings['speed']['Outer wall'] = '100-130mm/s'
        settings['speed']['Sparse infill'] = '180mm/s'
        settings['notes'].append("Detail part — moderate speed to keep small features clean.")
    elif project == 'lamp':
        settings['speed']['Outer wall'] = '80-100mm/s'
        settings['speed']['Sparse infill'] = 'N/A (no infill)'
        settings['notes'].append(
            "Slower outer wall speed for lamp shells — consistent extrusion at lower speed "
            "means more even wall thickness, which shows up directly as even light diffusion."
        )
    else:  # decor
        settings['speed']['Outer wall'] = '150-180mm/s'
        settings['speed']['Sparse infill'] = '220mm/s'

    if large_flat:
        settings['speed']['First layer speed'] = '30-40mm/s (slowed for adhesion on large footprint)'
    else:
        settings['speed']['First layer speed'] = '50mm/s (default fine)'

    # --- Support tab ---
    if geo['overhang_pct'] > 5:
        settings['support']['Enable support'] = True
        settings['support']['Type'] = 'Tree (auto)' if project == 'figure' else 'Normal'
        settings['support']['Threshold angle'] = '45°'
        settings['notes'].append(
            f"Geometry shows ~{geo['overhang_pct']:.0f}% steep overhang in current orientation — "
            "supports recommended. Re-check after you set final bed orientation in-slicer."
        )
    else:
        settings['support']['Enable support'] = False
        settings['notes'].append("Low overhang detected — supports likely unnecessary.")

    # --- Other tab ---
    if large_flat:
        settings['other']['Brim type'] = 'Outer brim only'
        settings['other']['Brim width'] = '5-8mm'
        settings['other']['Brim-object gap'] = '0.1-0.15mm'
        settings['notes'].append(
            f"Large flat part ({geo['max_xy']:.0f}mm footprint, {geo['height']:.0f}mm tall) — "
            "brim strongly recommended to prevent corner warping."
        )
    else:
        settings['other']['Brim type'] = 'Auto (or No-brim if part is small/stable)'

    if project == 'decor':
        settings['other']['Fuzzy skin'] = 'None (keep smooth for gloss-spray finish)'
    else:
        settings['other']['Fuzzy skin'] = 'None (default — only use for organic/textured pieces)'

    # --- Orientation recommendation ---
    settings['orientation'] = recommend_orientation(geo, project)

    # --- Bed fit check ---
    if not geo['fits_bed']:
        settings['notes'].insert(0,
            f"WARNING: part dimensions ({geo['dims'][0]:.0f} x {geo['dims'][1]:.0f} x "
            f"{geo['dims'][2]:.0f}mm) may exceed build volume even when rotated. Check scale before slicing."
        )

    return settings, mat


# ---------------------------------------------------------------------------
# Report printer
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
    print(f"Triangle count : {geo['triangle_count']}")
    print(f"Flattest face  : {geo['best_face']} ({geo['best_face_pct']:.1f}% of surface)")
    print(f"Overhang (as-uploaded orientation): {geo['overhang_pct']:.1f}%")
    print(f"Fits build volume (256^3mm): {'YES' if geo['fits_bed'] else 'NO - CHECK SCALE'}")
    print()
    print(f"RECOMMENDED NOZZLE: {settings['nozzle']}")
    print()
    print("--- ORIENTATION ---")
    print(f"  {settings['orientation']['summary']}")
    for r in settings['orientation']['reasoning']:
        print(f"  * {r}")
    print()

    for section in ['quality', 'strength', 'speed', 'support', 'other']:
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
    parser.add_argument('--project', choices=['decor', 'functional', 'figure', 'test', 'lamp'],
                         required=True, help="Project type")
    parser.add_argument('--material', choices=list(MATERIALS.keys()),
                         default='pla', help="Filament material (default: pla)")
    args = parser.parse_args()

    geo = analyze_stl(args.stl_file)
    settings, mat = recommend(geo, args.project, args.material)
    print_report(args.stl_file, geo, settings, mat, args.project)


if __name__ == '__main__':
    main()
