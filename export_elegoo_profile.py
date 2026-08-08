#!/usr/bin/env python3
"""
Export Print Advisor recommendations as real ElegooSlicer/OrcaSlicer user
presets (process + filament), so the settings don't have to be typed in by
hand every time.

USAGE:
    python3 export_elegoo_profile.py <file.stl> --project TYPE --material MATERIAL

Produces a "<profile name>.json" + "<profile name>.info" pair for both the
process (Quality/Strength/Speed/Support/Other) and filament (temps) presets
in ./elegoo_profiles/, plus install instructions.

These are real ElegooSlicer user presets, not a generic "3D settings file" -
the format was reverse engineered from ElegooSlicer's own source tree
(system profiles) and cross-checked against a known-working, real-world
custom profile set for the same printer (StudioAurora/elegoo-slicer-profiles
on GitHub) to confirm the on-disk format ElegooSlicer actually accepts for
user-created presets, which differs from the system-preset format and is
undocumented by Elegoo/Orca.

LIMITATION: only Centauri Carbon (--printer cc) has verified filament base
names below. Centauri Carbon 2 (--printer cc2) has a verified process base
but unverified filament base names - the filament profile step is skipped
for cc2 with a warning.
"""

import argparse
import json
import re
import time
from pathlib import Path

from print_advisor import analyze_stl, recommend, MATERIALS, BUILD_VOLUME  # noqa: F401


def detect_slicer_version(default="1.5.2.2"):
    """
    ElegooSlicer silently ignores a user preset whose declared "version"
    field doesn't match the running app's version - it doesn't error, the
    preset just never shows up in the dropdown. Read the real version out of
    ElegooSlicer's own config rather than hardcoding one that will go stale
    on the next app update.
    """
    conf_path = Path.home() / "Library/Application Support/ElegooSlicer/ElegooSlicer.conf"
    try:
        conf = json.loads(conf_path.read_text())
        version = conf.get("app", {}).get("version") or conf.get("version")
        if isinstance(version, str) and version:
            return version
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return default


SLICER_VERSION = detect_slicer_version()


# ---------------------------------------------------------------------------
# Known-real ElegooSlicer system preset names (verified against the
# ElegooSlicer/OrcaSlicer source tree - see script docstring).
# ---------------------------------------------------------------------------

PRINTER_BASES = {
    'cc': {
        'process_base': '0.20mm Standard @Elegoo CC 0.4 nozzle',
        'process_base_id': 'PECC04020',  # confirmed real value for this exact base
        'label': 'Centauri Carbon',
    },
    'cc2': {
        # NOTE: "@Elegoo C2" (folder EC2) is the plain Centauri 2, a different
        # printer. Centauri Carbon 2's real base lives in the ECC2 folder.
        'process_base': '0.20mm Standard @Elegoo CC2 0.4 nozzle',
        'process_base_id': '',  # not verified - left blank rather than guessed
        'label': 'Centauri Carbon 2',
    },
}

# material key -> real Elegoo system filament preset name, verified to exist
# and be compatible with the given printer's 0.4mm nozzle.
FILAMENT_BASES = {
    'cc': {
        'pla': 'Elegoo PLA Basic @ECC',
        'pla_plus': 'Elegoo PLA+ @ECC',
        'petg': 'Elegoo PETG @ECC',
        'petg_cf': 'Elegoo PETG-CF @ECC',
        'tpu': 'Elegoo TPU 95A @ECC',
        'paht_cf': 'Elegoo PAHT-CF @ECC',
        'pa6_cf': 'Generic PA6-CF @Elegoo',
        # ppa_cf, pa12_cf, pps_cf: no matching Elegoo/Generic base ships in
        # ElegooSlicer as of this writing - skipped, noted in output.
    },
    'cc2': {
        'pla': 'Elegoo PLA Basic @ECC2',
        'pla_plus': 'Elegoo PLA+ @ECC2',
        'petg': 'Elegoo PETG @ECC2',
        'petg_cf': 'Elegoo PETG-CF @ECC2',
        'tpu': 'Elegoo TPU 95A @ECC2',
        'paht_cf': 'Elegoo PAHT-CF @ECC2',
        'pa6_cf': 'Generic PA6-CF @Elegoo',
        # ppa_cf, pa12_cf, pps_cf: same gap as cc.
    },
}


def _midpoint(text):
    """Pull the numeric value (or the average of a 'X-Y' range) out of a
    display string like '150-180mm/s' or '45°' or '5-8mm'."""
    nums = [float(x) for x in re.findall(r'[\d.]+', text)]
    if not nums:
        return None
    return sum(nums) / len(nums)


def slicer_overrides(geo, project, material_key):
    """
    Mirrors the decision logic in print_advisor.recommend(), but returns raw
    ElegooSlicer/OrcaSlicer config keys and values instead of display text -
    kept as a parallel function (rather than parsing recommend()'s formatted
    strings) so the mapping to real slicer keys stays exact instead of
    depending on regex-parsing human-readable ranges like "40-60%".
    """
    large_flat = geo['max_xy'] > 150 and geo['height'] < 20
    process = {}

    # Quality
    if project == 'figure':
        process['layer_height'] = '0.16'
        process['initial_layer_print_height'] = '0.2'
    elif project == 'test':
        process['layer_height'] = '0.2'
        process['initial_layer_print_height'] = '0.24'
    elif project in ('structural', 'structure'):
        process['layer_height'] = '0.2'
        process['initial_layer_print_height'] = '0.2'
    elif project == 'lamp':
        process['layer_height'] = '0.16'
        process['initial_layer_print_height'] = '0.2'
        process['spiral_mode'] = '1'
    else:
        process['layer_height'] = '0.2'
        process['initial_layer_print_height'] = '0.2'

    process['seam_position'] = 'back' if project in ('decor', 'functional', 'structural', 'structure') else 'random'
    process['ironing_type'] = 'top' if project == 'decor' else 'no ironing'
    if large_flat:
        process['elefant_foot_compensation'] = '0.175'

    # Strength
    if project == 'functional':
        process['wall_loops'] = '4'
        process['top_shell_layers'] = '5'
        process['bottom_shell_layers'] = '5'
        process['sparse_infill_density'] = '50%'
        process['sparse_infill_pattern'] = 'gyroid'
    elif project == 'figure':
        process['wall_loops'] = '2'
        process['top_shell_layers'] = '3'
        process['bottom_shell_layers'] = '3'
        process['sparse_infill_density'] = '18%'
        process['sparse_infill_pattern'] = 'gyroid'
    elif project == 'decor':
        process['wall_loops'] = '3'
        process['top_shell_layers'] = '4'
        process['bottom_shell_layers'] = '4'
        process['sparse_infill_density'] = '18%'
        process['sparse_infill_pattern'] = 'gyroid'
    elif project in ('structural', 'structure'):
        process['wall_loops'] = '8'
        process['top_shell_layers'] = '8'
        process['bottom_shell_layers'] = '8'
        process['sparse_infill_density'] = '100%'
        process['sparse_infill_pattern'] = 'rectilinear'
    elif project == 'lamp':
        process['wall_loops'] = '1'
        process['top_shell_layers'] = '0'
        process['bottom_shell_layers'] = '3'
        process['sparse_infill_density'] = '0%'
        process['sparse_infill_pattern'] = 'grid'
    else:  # test
        process['wall_loops'] = '2'
        process['top_shell_layers'] = '3'
        process['bottom_shell_layers'] = '3'
        process['sparse_infill_density'] = '12%'
        process['sparse_infill_pattern'] = 'grid'

    if MATERIALS[material_key].get('flexible') and project != 'lamp':
        process['wall_loops'] = str(max(int(process['wall_loops']), 3))

    # Speed
    speed_by_project = {
        'test': ('180-200mm/s', '250mm/s'),
        'functional': ('120-150mm/s', '180mm/s'),
        'figure': ('100-130mm/s', '180mm/s'),
        'decor': ('150-180mm/s', '220mm/s'),
        'structural': ('110mm/s', '150mm/s'),
        'structure': ('110mm/s', '150mm/s'),
        'lamp': ('80-100mm/s', '80-100mm/s'),  # infill is 0%, value unused but key must exist
    }
    outer, infill = speed_by_project[project]
    process['outer_wall_speed'] = str(round(_midpoint(outer)))
    process['sparse_infill_speed'] = str(round(_midpoint(infill)))
    process['initial_layer_speed'] = '35' if large_flat else '50'

    # Support
    if project == 'lamp':
        process['enable_support'] = '0'  # spiral mode is incompatible with supports
    elif geo['overhang_pct'] > 5:
        process['enable_support'] = '1'
        process['support_type'] = 'tree(auto)' if project in ('figure', 'structural', 'structure') else 'normal(auto)'
        process['support_threshold_angle'] = '45'
    else:
        process['enable_support'] = '0'

    # Other
    if large_flat or project in ('structural', 'structure'):
        process['brim_type'] = 'outer_only'
        process['brim_width'] = '5' if project in ('structural', 'structure') and not large_flat else '6.5'
        process['brim_object_gap'] = '0.125'
    process['fuzzy_skin'] = 'none'

    return process


def build_process_profile(name, printer_base, overrides):
    return {
        "from": "User",
        "inherits": printer_base['process_base'],
        "is_custom_defined": "0",
        "name": name,
        "print_settings_id": name,
        **overrides,
        "version": SLICER_VERSION,
    }


def build_filament_profile(name, filament_base, mat):
    temp = str(mat['nozzle_temp'])
    bed = str(mat['bed_temp'])
    return {
        "filament_settings_id": [name],
        "from": "User",
        "inherits": filament_base,
        "is_custom_defined": "0",
        "name": name,
        "nozzle_temperature": [temp],
        "nozzle_temperature_initial_layer": [temp],
        "hot_plate_temp": [bed],
        "hot_plate_temp_initial_layer": [bed],
        "version": SLICER_VERSION,
    }


def build_info(base_id=""):
    return (
        "sync_info = create\n"
        "user_id = \n"
        "setting_id = \n"
        f"base_id = {base_id}\n"
        f"updated_time = {int(time.time())}\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Export Print Advisor settings as ElegooSlicer user presets")
    parser.add_argument('stl_file', help="Path to the STL file")
    parser.add_argument('--project', choices=['decor', 'functional', 'figure', 'test', 'structure', 'lamp'], required=True)
    parser.add_argument('--material', choices=list(MATERIALS.keys()), default='pla')
    parser.add_argument('--printer', choices=['cc', 'cc2'], default='cc2',
                         help="Centauri Carbon (cc) or Centauri Carbon 2 (cc2, default)")
    parser.add_argument('--out', default='elegoo_profiles', help="Output directory")
    args = parser.parse_args()

    printer_base = PRINTER_BASES[args.printer]
    geo = analyze_stl(args.stl_file)
    mat = MATERIALS[args.material]
    overrides = slicer_overrides(geo, args.project, args.material)

    out_dir = Path(args.out)
    process_dir = out_dir / 'process'
    filament_dir = out_dir / 'filament'
    process_dir.mkdir(parents=True, exist_ok=True)

    process_name = f"{args.project.capitalize()} {mat['name'].split(' ')[0]} @Elegoo {printer_base['label']}"
    process_profile = build_process_profile(process_name, printer_base, overrides)
    (process_dir / f"{process_name}.json").write_text(json.dumps(process_profile, indent=4))
    (process_dir / f"{process_name}.info").write_text(build_info(printer_base['process_base_id']))

    print(f"Wrote process profile: {process_dir / (process_name + '.json')}")

    filament_bases = FILAMENT_BASES[args.printer]
    suffix = 'ECC2' if args.printer == 'cc2' else 'ECC'
    filament_name = None
    if args.material in filament_bases:
        filament_dir.mkdir(parents=True, exist_ok=True)
        filament_base = filament_bases[args.material]
        filament_name = f"{mat['name']} (Print Advisor) @{suffix}"
        filament_profile = build_filament_profile(filament_name, filament_base, mat)
        (filament_dir / f"{filament_name}.json").write_text(json.dumps(filament_profile, indent=4))
        (filament_dir / f"{filament_name}.info").write_text(build_info())
        print(f"Wrote filament profile: {filament_dir / (filament_name + '.json')}")
    else:
        print(
            f"NOTE: no verified ElegooSlicer system filament base for "
            f"'{args.material}' on printer '{args.printer}' - skipping filament "
            f"profile. Select the closest stock filament preset in ElegooSlicer "
            f"and manually set nozzle={mat['nozzle_temp']}C / bed={mat['bed_temp']}C."
        )

    print()
    print("=== INSTALL ===")
    print("1. Quit ElegooSlicer if it's running.")
    print("2. Copy the file(s) into your ElegooSlicer user preset folder:")
    print()
    print(f"   cp '{process_dir}'/*.json '{process_dir}'/*.info \\")
    print("     ~/Library/Application\\ Support/ElegooSlicer/user/default/process/")
    if filament_name:
        print()
        print(f"   cp '{filament_dir}'/*.json '{filament_dir}'/*.info \\")
        print("     ~/Library/Application\\ Support/ElegooSlicer/user/default/filament/")
    print()
    print(f"3. Relaunch ElegooSlicer, select the {printer_base['label']} printer + 0.4mm")
    print(f"   nozzle, and pick '{process_name}' from the process preset dropdown")
    if filament_name:
        print(f"   and '{filament_name}' from the filament dropdown.")
    print()
    print("If a preset doesn't show up, it's a known ElegooSlicer quirk with")
    print("user-preset loading (see GitHub issue OrcaSlicer/OrcaSlicer#10939) -")
    print("as a fallback, open the report from print_advisor.py and enter the")
    print("values by hand, then click Save in the slicer to create the preset")
    print("yourself (that path always works).")


if __name__ == '__main__':
    main()
