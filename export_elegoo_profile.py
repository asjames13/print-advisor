#!/usr/bin/env python3
"""
Export Elegoo / OrcaSlicer Process Profile JSON & Slicer Overrides
-------------------------------------------------------------------
Generates custom process profile JSON files and exports raw slicer key overrides
for Elegoo Slicer / OrcaSlicer based on project type and STL geometry.

USAGE:
    python3 export_elegoo_profile.py --profile structural --output ./profiles/
"""

import os
import json
import argparse
from typing import Dict, Any

PROFILE_PRESET_MAP = {
    "functional": "0.20mm Standard @Elegoo CC2",
    "decor": "0.16mm Fine @Elegoo CC2",
    "test": "0.28mm Draft @Elegoo CC2",
    "figure": "0.12mm High Detail @Elegoo CC2",
    "structural": "0.16mm Heavy Structural @Elegoo CC2",
}

PROFILE_SETTINGS: Dict[str, Dict[str, Any]] = {
    "test": {
        "layer_height": "0.28",
        "initial_layer_print_height": "0.24",
        "wall_loops": "2",
        "sparse_infill_density": "15%",
        "sparse_infill_pattern": "grid",
        "top_shell_layers": "3",
        "bottom_shell_layers": "3",
    },
    "decor": {
        "layer_height": "0.16",
        "initial_layer_print_height": "0.20",
        "wall_loops": "2",
        "sparse_infill_density": "10%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": "4",
        "bottom_shell_layers": "4",
    },
    "figure": {
        "layer_height": "0.12",
        "initial_layer_print_height": "0.20",
        "wall_loops": "3",
        "sparse_infill_density": "15%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": "5",
        "bottom_shell_layers": "5",
    },
    "functional": {
        "layer_height": "0.20",
        "initial_layer_print_height": "0.20",
        "wall_loops": "4",
        "sparse_infill_density": "40%",
        "sparse_infill_pattern": "gyroid",
        "top_shell_layers": "5",
        "bottom_shell_layers": "5",
    },
    "structural": {
        "layer_height": "0.16",
        "initial_layer_print_height": "0.20",
        "wall_loops": "8",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "rectilinear",
        "top_shell_layers": "8",
        "bottom_shell_layers": "8",
        "fan_max_speed": "40",
        "enable_support": "1",
        "support_type": "tree_auto",
    }
}


def slicer_overrides(geo: dict, project: str, material: str) -> Dict[str, str]:
    """
    Generate dictionary of raw OrcaSlicer/ElegooSlicer process overrides
    for project_settings.config patching in .3mf project files.
    """
    settings = PROFILE_SETTINGS.get(project, PROFILE_SETTINGS["functional"])
    overrides = {k: str(v) for k, v in settings.items()}

    if project == "structural":
        overrides["outer_wall_speed"] = "110"
        overrides["sparse_infill_speed"] = "150"
    elif project == "functional":
        overrides["outer_wall_speed"] = "135"
        overrides["sparse_infill_speed"] = "180"
    else:
        overrides["outer_wall_speed"] = "165"
        overrides["sparse_infill_speed"] = "220"

    if geo.get("overhang_pct", 0) > 5 or project == "structural":
        overrides["enable_support"] = "1"
        overrides["support_type"] = settings.get("support_type", "tree_auto")

    return overrides


def build_elegoo_profile_dict(profile_name: str) -> Dict[str, Any]:
    preset_name = PROFILE_PRESET_MAP.get(profile_name, PROFILE_PRESET_MAP["functional"])
    settings = PROFILE_SETTINGS.get(profile_name, PROFILE_SETTINGS["functional"])

    base_json = {
        "type": "process",
        "name": preset_name,
        "from": "system",
        "instantiation": "true",
        "inherits": "0.16mm Optimal @Elegoo CC2",
        "version": "1.9.0.0",
        "layer_height": settings.get("layer_height", "0.16"),
        "initial_layer_print_height": settings.get("initial_layer_print_height", "0.20"),
        "wall_loops": settings.get("wall_loops", "4"),
        "sparse_infill_density": settings.get("sparse_infill_density", "40%"),
        "sparse_infill_pattern": settings.get("sparse_infill_pattern", "gyroid"),
        "top_shell_layers": settings.get("top_shell_layers", "5"),
        "bottom_shell_layers": settings.get("bottom_shell_layers", "5"),
    }

    if "fan_max_speed" in settings:
        base_json["fan_max_speed"] = [settings["fan_max_speed"]]
    if "enable_support" in settings:
        base_json["enable_support"] = settings["enable_support"]
    if "support_type" in settings:
        base_json["support_type"] = settings["support_type"]

    return base_json


def export_profile(profile_name: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    preset_name = PROFILE_PRESET_MAP.get(profile_name, PROFILE_PRESET_MAP["functional"])
    safe_filename = preset_name.replace(" ", "_").replace("@", "at") + ".json"
    target_path = os.path.join(output_dir, safe_filename)

    profile_data = build_elegoo_profile_dict(profile_name)

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=4)

    print(f"[+] Exported Elegoo Profile: '{preset_name}' -> {target_path}")
    return target_path


def main():
    parser = argparse.ArgumentParser(description="Export Elegoo Slicer Process JSON")
    parser.add_argument(
        "--profile",
        choices=list(PROFILE_PRESET_MAP.keys()),
        default="structural",
        help="Target profile choice"
    )
    parser.add_argument(
        "--output",
        default="./export_profiles",
        help="Directory path to save exported JSON profile"
    )
    args = parser.parse_args()

    export_profile(args.profile, args.output)


if __name__ == "__main__":
    main()
