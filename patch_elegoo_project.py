#!/usr/bin/env python3
"""
Patch Elegoo / OrcaSlicer .3MF Project Files
---------------------------------------------
Modifies process settings and slicer overrides inside a .3mf file
based on user selection and geometric profile presets.
"""

import os
import sys
import json
import zipfile
import shutil
import tempfile
import argparse
import subprocess
from typing import Dict, Any

from export_elegoo_profile import slicer_overrides

# Hardcoded list to ensure all options always display in the GUI dialog
PROJECT_CHOICES = ["functional", "decor", "figure", "test", "structural"]


def prompt_user_project_type() -> str:
    """
    Displays a native macOS dialog listing all available project choices.
    """
    applescript_choices = '{"' + '", "'.join(PROJECT_CHOICES) + '"}'
    
    applescript = f'''
    set options to {applescript_choices}
    set choice to choose from list options with prompt "What is this part for?" default items {{"{PROJECT_CHOICES[0]}"}}
    if choice is not false then
        return item 1 of choice
    else
        return ""
    end if
    '''
    
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True
        )
        selected = res.stdout.strip()
        if selected in PROJECT_CHOICES:
            return selected
    except Exception:
        pass

    # Fallback to interactive CLI if osascript fails or is cancelled
    print("\nSelect part type:")
    for idx, name in enumerate(PROJECT_CHOICES, 1):
        print(f"  [{idx}] {name}")
    try:
        selection = int(input("Choice number [1]: ") or "1")
        return PROJECT_CHOICES[selection - 1]
    except (ValueError, IndexError):
        return PROJECT_CHOICES[0]


def patch_3mf_file(input_3mf: str, project_type: str, output_3mf: str = None) -> str:
    if not output_3mf:
        base, ext = os.path.splitext(input_3mf)
        output_3mf = f"{base}_{project_type}{ext}"

    # Default dummy geometry dict for standard profile patching
    geo_data = {"overhang_pct": 0.0}
    overrides = slicer_overrides(geo=geo_data, project=project_type, material="PLA")

    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(input_3mf, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        config_path = os.path.join(temp_dir, "Metadata", "project_settings.config")

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                try:
                    config_data = json.load(f)
                except json.JSONDecodeError:
                    config_data = {}

            # Inject/override slicer parameters
            if "process" in config_data and isinstance(config_data["process"], dict):
                config_data["process"].update(overrides)
            else:
                config_data["process"] = overrides

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4)

        # Re-pack the modified files back into a .3mf ZIP archive
        shutil.make_archive(temp_dir, "zip", temp_dir)
        zipped_file = f"{temp_dir}.zip"
        shutil.move(zipped_file, output_3mf)

        print(f"[+] Successfully patched '{input_3mf}' as '{project_type}' -> {output_3mf}")
        return output_3mf

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Patch OrcaSlicer/Elegoo 3MF Project Files")
    parser.add_argument("file", nargs="?", help="Path to target .3mf file")
    parser.add_argument(
        "--project",
        choices=PROJECT_CHOICES,
        help="Specify project choice directly without GUI prompt"
    )
    args = parser.parse_args()

    if not args.file or not os.path.exists(args.file):
        print("Error: Please provide a valid .3mf file path.")
        sys.exit(1)

    project_choice = args.project if args.project else prompt_user_project_type()
    if not project_choice:
        print("Cancelled.")
        sys.exit(0)

    patch_3mf_file(args.file, project_choice)


if __name__ == "__main__":
    main()
