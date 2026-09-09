#!/usr/bin/env python3
"""Generate the Germany Bundesland maps used by content/germany-maps.json.

Outputs (into content/maps/ by default):

  germany.svg/.png            all 16 states, light fill
  de-<state-slug>.svg/.png    one map per state with that state
                              highlighted (e.g. de-bayern.png)

Every map also shows the ~20 largest German cities as labelled dots.

Data source and license: see mapdraw.py (Natural Earth 10m admin-1,
public domain).  The source GeoJSON is downloaded once and cached
under ~/.cache/pauk-maps/.

Re-running is safe and deterministic; outputs are simply overwritten.
Requires cairosvg for the PNG step (build-time dependency only) —
run with a venv that has it installed, e.g.:

    python3 -m venv /tmp/mapsenv
    /tmp/mapsenv/bin/pip install cairosvg
    /tmp/mapsenv/bin/python scripts/maps/generate_state_maps.py
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapdraw  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTDIR = os.path.join(REPO_ROOT, "content", "maps")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR,
                    help=f"output directory (default: {DEFAULT_OUTDIR})")
    ap.add_argument("--cache", default=mapdraw.DEFAULT_CACHE,
                    help="path of the cached Natural Earth GeoJSON")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    states = mapdraw.load_states(args.cache)

    # Overview map.
    svg = mapdraw.build_svg(states)
    paths = [mapdraw.write_svg_png(svg, os.path.join(args.outdir, "germany"))]
    # One highlighted map per state.
    for slug in sorted(states):
        svg = mapdraw.build_svg(states, highlight=slug)
        paths.append(mapdraw.write_svg_png(
            svg, os.path.join(args.outdir, f"de-{slug}")))

    for svg_path, png_path in paths:
        print(f"wrote {svg_path} + {os.path.basename(png_path)}")
    print(f"{len(paths)} maps ({len(paths) * 2} files) in {args.outdir}")


if __name__ == "__main__":
    main()
