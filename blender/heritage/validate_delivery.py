"""Static delivery checks for the JSN_Sangok Blender project.

This script intentionally does not import bpy, so it can run with ordinary Python
while Blender is busy rendering. Use --strict when all final exports are expected.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from qa_preview import analyze_image


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
SCRIPT = ROOT / "_scripts" / "jsn_live.py"
MASTER = ROOT / "00_Source_Blender" / "JSN_Master.blend"
PREVIEWS = ROOT / "04_Previews"
README = ROOT / "05_Documentation" / "README.md"
EXPORTS = ROOT / "01_Exports_FBX"
MANIFEST = ROOT / "05_Documentation" / "scene_manifest.json"

VIEWS = {"Survey", "Valley", "Ridge", "Pass"}
ROCK_UNITS = "ABCDEF"
VEG_MODELS = (
    "SM_Black_Pine.fbx",
    "SM_Lugose.fbx",
    "SM_Vitex.fbx",
    "SM_Eulalia.fbx",
    "SM_Artemisia.fbx",
    "SM_Anthephoroides.fbx",
)


def expected_inputs() -> list[Path]:
    paths: list[Path] = []
    extracted = ROOT / "_extracted"
    for unit in ROCK_UNITS:
        rock = extracted / f"ROCK_Columnar{unit}"
        paths.append(rock / "FBX" / f"SM_MDS_Unit{unit}.fbx")
        for suffix in ("BC", "N", "R"):
            paths.append(rock / "Texture" / f"T_MDS_Unit{unit}_{suffix}.png")

    veg = extracted / "VEG"
    paths.extend(veg / name for name in VEG_MODELS)

    cdg = WORKSPACE / "CDG_Changdeokgung" / "_extracted" / "_TexLib"
    for stem in ("T_Ground02A", "T_Ground01A", "T_Stone01B"):
        for suffix in ("BC", "NM", "RN"):
            paths.append(cdg / f"{stem}_{suffix}.png")

    sand = WORKSPACE / "SSW_Soswaewon" / "_extracted" / "Sand"
    for suffix in ("BC", "NM", "RN"):
        paths.append(sand / f"T_Sand_ColorB_{suffix}4k.png")
    return paths


def latest_preview_set() -> tuple[str | None, set[str], list[Path]]:
    pattern = re.compile(r"^(?P<tag>.+)_(?P<view>Survey|Valley|Ridge|Pass)\.png$")
    groups: dict[str, dict[str, Path]] = {}
    for path in PREVIEWS.glob("*.png"):
        match = pattern.match(path.name)
        if match:
            groups.setdefault(match["tag"], {})[match["view"]] = path
    if not groups:
        return None, set(), []
    tag = max(groups, key=lambda item: max(p.stat().st_mtime for p in groups[item].values()))
    files = groups[tag]
    return tag, set(files), sorted(files.values())


def overdare_violations(path: Path) -> tuple[list[str], dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", {})
    tris_limit = int(rules.get("max_tris_per_mesh", 30_000))
    mesh_limit = int(rules.get("max_meshes_per_fbx", 200))
    texture_limit = int(rules.get("max_textures_per_mesh", 1))
    meshes = data.get("unique_meshes", [])
    violations: list[str] = []

    for mesh in meshes:
        name = str(mesh.get("mesh", "<unnamed>"))
        tris = int(mesh.get("tris", 0))
        textures = len(set(mesh.get("textures", [])))
        if tris > tris_limit:
            violations.append(f"{name}: {tris:,} tris > {tris_limit:,}")
        if textures > texture_limit:
            violations.append(f"{name}: {textures} textures > {texture_limit}")

    mesh_count = int(data.get("summary", {}).get("unique_meshes", len(meshes)))
    if mesh_count > mesh_limit:
        violations.append(f"project baseline: {mesh_count} meshes > {mesh_limit} per FBX")
    stats = {
        "unique_meshes": mesh_count,
        "tris_violations": sum(" tris > " in item for item in violations),
        "texture_violations": sum(" textures > " in item for item in violations),
        "mesh_count_violations": sum(" meshes > " in item for item in violations),
    }
    return violations, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat preview findings, OVERDARE violations, and missing FBX exports as failures.",
    )
    parser.add_argument(
        "--overdare",
        action="store_true",
        help="Compare scene_manifest.json with the OVERDARE baseline rules.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    try:
        ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    except (OSError, SyntaxError, UnicodeError) as exc:
        errors.append(f"generator script is not valid UTF-8 Python: {exc}")

    missing_inputs = [path for path in expected_inputs() if not path.is_file()]
    if missing_inputs:
        errors.extend(f"missing input: {path}" for path in missing_inputs)

    if not MASTER.is_file():
        errors.append(f"missing Blender master: {MASTER}")
    else:
        with MASTER.open("rb") as handle:
            header = handle.read(7)
        # Blender files may be plain, gzip-compressed, or zstd-compressed.
        valid_header = (
            header == b"BLENDER"
            or header.startswith(b"\x1f\x8b")
            or header.startswith(b"\x28\xb5\x2f\xfd")
        )
        if not valid_header:
            errors.append(f"unrecognized Blender file header: {MASTER}")

    if not README.is_file():
        warnings.append(f"missing documentation: {README}")

    tag, views, preview_files = latest_preview_set()
    if tag is None:
        errors.append(f"no preview images found in {PREVIEWS}")
    else:
        missing_views = sorted(VIEWS - views)
        if missing_views:
            errors.append(f"latest preview tag {tag!r} lacks: {', '.join(missing_views)}")
        preview_findings = []
        for path in preview_files:
            result = analyze_image(path)
            for finding in result["findings"]:
                preview_findings.append(f"{path.name}: {finding['code']}")
        target = errors if args.strict else warnings
        target.extend(f"preview QA: {finding}" for finding in preview_findings)

    overdare_stats: dict[str, int] | None = None
    if args.overdare:
        if not MANIFEST.is_file():
            errors.append(f"missing scene manifest: {MANIFEST}")
        else:
            try:
                violations, overdare_stats = overdare_violations(MANIFEST)
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(f"invalid scene manifest: {exc}")
            else:
                target = errors if args.strict else warnings
                target.extend(f"OVERDARE: {violation}" for violation in violations)

    exports = sorted(EXPORTS.glob("*.fbx")) if EXPORTS.is_dir() else []
    if not exports:
        message = f"no FBX exports found in {EXPORTS}"
        (errors if args.strict else warnings).append(message)

    print(f"Project: {ROOT}")
    print(f"Inputs: {len(expected_inputs()) - len(missing_inputs)}/{len(expected_inputs())} present")
    if MASTER.is_file():
        print(f"Master: {MASTER.stat().st_size / 1024 / 1024:.1f} MiB")
    if tag is not None:
        print(f"Previews: tag={tag}, views={','.join(sorted(views))}, files={len(preview_files)}")
    if args.overdare and overdare_stats is not None:
        print(
            "OVERDARE baseline: "
            f"meshes={overdare_stats['unique_meshes']}, "
            f"tris={overdare_stats['tris_violations']}, "
            f"textures={overdare_stats['texture_violations']}, "
            f"mesh_count={overdare_stats['mesh_count_violations']} violation(s)"
        )
    print(f"Exports: {len(exports)} FBX file(s)")

    for message in warnings:
        print(f"WARN: {message}")
    for message in errors:
        print(f"ERROR: {message}")

    if errors:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS_WITH_WARNINGS" if warnings else "RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
