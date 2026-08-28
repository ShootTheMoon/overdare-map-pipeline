"""PIL-only heuristic QA for rendered JSN_Sangok preview images.

The detectors are deliberately conservative: they catch the failure shapes seen
during this project, but their output remains a review signal rather than proof of
a modeling defect.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
PREVIEWS = ROOT / "04_Previews"
VIEW_RE = re.compile(r"^(?P<tag>.+)_(?P<view>Survey|Valley|Ridge|Pass)\.png$")


def _scaled_gray(path: Path, max_width: int = 320) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("L")
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.BILINEAR)
        return image.copy()


def _percentile(image: Image.Image, quantile: float) -> int:
    histogram = image.histogram()
    target = max(0, min(image.width * image.height - 1, round(quantile * (image.width * image.height - 1))))
    count = 0
    for value, amount in enumerate(histogram):
        count += amount
        if count > target:
            return value
    return 255


def _flat_pixels(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", None)
    return list(getter() if getter is not None else image.getdata())


def _components(mask: list[bool], width: int, height: int) -> list[dict[str, int]]:
    """Return four-connected component bounds and area for a small binary image."""
    seen = bytearray(width * height)
    found: list[dict[str, int]] = []
    for start, active in enumerate(mask):
        if not active or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        area = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            area += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            if x and mask[index - 1] and not seen[index - 1]:
                seen[index - 1] = 1
                queue.append(index - 1)
            if x + 1 < width and mask[index + 1] and not seen[index + 1]:
                seen[index + 1] = 1
                queue.append(index + 1)
            if y and mask[index - width] and not seen[index - width]:
                seen[index - width] = 1
                queue.append(index - width)
            if y + 1 < height and mask[index + width] and not seen[index + width]:
                seen[index + width] = 1
                queue.append(index + width)
        found.append(
            {
                "area": area,
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
            }
        )
    return found


def _bbox(component: dict[str, int], width: int, height: int) -> list[float]:
    return [
        round(component["min_x"] / width, 3),
        round(component["min_y"] / height, 3),
        round((component["max_x"] + 1) / width, 3),
        round((component["max_y"] + 1) / height, 3),
    ]


def _dark_vertical_seam(image: Image.Image) -> dict[str, Any] | None:
    width, height = image.size
    threshold = min(52, _percentile(image, 0.12))
    mask = [value <= threshold for value in _flat_pixels(image)]
    candidates: list[tuple[float, dict[str, int]]] = []
    for component in _components(mask, width, height):
        box_width = component["max_x"] - component["min_x"] + 1
        box_height = component["max_y"] - component["min_y"] + 1
        area_ratio = component["area"] / (width * height)
        aspect = box_height / max(1, box_width)
        if box_height >= height * 0.22 and box_width <= width * 0.13 and aspect >= 2.6 and area_ratio >= 0.0015:
            candidates.append((box_height * aspect * area_ratio, component))
    if not candidates:
        return None
    component = max(candidates, key=lambda item: item[0])[1]
    return {
        "code": "dark_vertical_seam",
        "message": "tall low-luminance connected region may be a vertical seam",
        "threshold": threshold,
        "bbox_norm": _bbox(component, width, height),
        "area_ratio": round(component["area"] / (width * height), 4),
    }


def _lens_occlusion(image: Image.Image) -> dict[str, Any] | None:
    width, height = image.size
    top = height * 2 // 3
    crop = image.crop((0, top, width, height))
    cw, ch = crop.size
    threshold = min(68, _percentile(crop, 0.35))
    mask = [value <= threshold for value in _flat_pixels(crop)]
    components = _components(mask, cw, ch)
    if not components:
        return None
    component = max(components, key=lambda item: item["area"])
    ratio = component["area"] / (cw * ch)
    full_mask = [value <= threshold for value in _flat_pixels(image)]
    full_components = _components(full_mask, width, height)
    full_component = max(full_components, key=lambda item: item["area"], default=None)
    full_ratio = full_component["area"] / (width * height) if full_component else 0.0
    touches_bottom = bool(full_component and full_component["max_y"] >= height - 2)
    # A foreground object can cover most of the entire frame while occupying
    # slightly less than 40% of the lower crop (the historical s5/s6 Pass case).
    if ratio < 0.40 and not (full_ratio >= 0.55 and touches_bottom):
        return None
    bbox = _bbox(component, cw, ch)
    bbox[1] = round((top + bbox[1] * ch) / height, 3)
    bbox[3] = round((top + bbox[3] * ch) / height, 3)
    return {
        "code": "lens_occlusion",
        "message": "one dark component covers at least 40% of the lower third",
        "threshold": threshold,
        "bbox_norm": bbox,
        "lower_third_ratio": round(ratio, 4),
        "full_frame_ratio": round(full_ratio, 4),
    }


def _highlight_clipping(image: Image.Image) -> dict[str, Any] | None:
    p99 = _percentile(image, 0.99)
    if p99 < 250:
        return None
    histogram = image.histogram()
    clipped = sum(histogram[250:]) / (image.width * image.height)
    return {
        "code": "highlight_clipping",
        "message": "the 99th-percentile luminance is at least 250",
        "p99": p99,
        "pixels_ge_250_ratio": round(clipped, 4),
    }


def _longest_run(values: Iterable[int], threshold: int) -> int:
    longest = current = 0
    for value in values:
        if value >= threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _map_cut_edge(image: Image.Image) -> dict[str, Any] | None:
    edges = image.filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    pixels = edges.load()
    threshold = 72
    band_x = max(2, round(width * 0.06))
    band_y = max(2, round(height * 0.12))
    candidates: list[tuple[float, str, int, float, float]] = []

    for y in list(range(2, band_y)) + list(range(max(2, height - band_y), height - 2)):
        values = [pixels[x, y] for x in range(2, width - 2)]
        coverage = sum(v >= threshold for v in values) / len(values)
        run = _longest_run(values, threshold) / len(values)
        if coverage >= 0.48 and run >= 0.28:
            candidates.append((coverage + run, "horizontal", y, coverage, run))

    for x in list(range(2, band_x)) + list(range(max(2, width - band_x), width - 2)):
        values = [pixels[x, y] for y in range(2, height - 2)]
        coverage = sum(v >= threshold for v in values) / len(values)
        run = _longest_run(values, threshold) / len(values)
        if coverage >= 0.48 and run >= 0.28:
            candidates.append((coverage + run, "vertical", x, coverage, run))

    if not candidates:
        return None
    _, orientation, offset, coverage, run = max(candidates)
    return {
        "code": "map_cut_edge",
        "message": "a long straight high-contrast edge lies near the frame boundary",
        "orientation": orientation,
        "offset_norm": round(offset / (height if orientation == "horizontal" else width), 3),
        "edge_coverage": round(coverage, 3),
        "longest_run_ratio": round(run, 3),
    }


def analyze_image(path: Path) -> dict[str, Any]:
    image = _scaled_gray(path)
    findings = [
        finding
        for finding in (
            _dark_vertical_seam(image),
            _lens_occlusion(image),
            _highlight_clipping(image),
            _map_cut_edge(image),
        )
        if finding is not None
    ]
    return {
        "path": str(path),
        "sample_size": list(image.size),
        "findings": findings,
    }


def latest_paths(tag: str | None = None) -> tuple[str | None, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in PREVIEWS.glob("*.png"):
        match = VIEW_RE.match(path.name)
        if match:
            groups.setdefault(match["tag"], []).append(path)
    if tag is not None:
        return tag, sorted(groups.get(tag, []))
    if not groups:
        return None, []
    latest = max(groups, key=lambda key: max(path.stat().st_mtime for path in groups[key]))
    return latest, sorted(groups[latest])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="PNG files; defaults to the latest four-view set")
    parser.add_argument("--tag", help="Analyze one preview tag, for example s10")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--report-only", action="store_true", help="Always exit zero")
    args = parser.parse_args()

    tag: str | None = args.tag
    paths = args.paths
    if not paths:
        tag, paths = latest_paths(args.tag)
    results = [analyze_image(path) for path in paths]
    payload = {
        "tag": tag,
        "images": results,
        "finding_count": sum(len(item["findings"]) for item in results),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Preview QA: tag={tag or '-'}, images={len(results)}, findings={payload['finding_count']}")
        for result in results:
            codes = ", ".join(finding["code"] for finding in result["findings"]) or "OK"
            print(f"  {Path(result['path']).name}: {codes}")
    if not paths:
        print("ERROR: no matching preview images", file=sys.stderr)
        return 1
    return 0 if args.report_only or payload["finding_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
