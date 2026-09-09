# Germany maps pipeline

Scripts that generate the Bundesland maps used by
`content/germany-maps.json` and render Autobahn routes on the
same base map.

## Data source and license

State (admin-1) boundary polygons: Natural Earth, 10m
"Admin 1 - States, Provinces", fetched as GeoJSON from the
official natural-earth-vector GitHub repository (see the URL in
`mapdraw.py`). Natural Earth data is in the public domain
(https://www.naturalearthdata.com/about/terms-of-use/), so it
may be used, modified and redistributed without restriction.

The ~40 MB world file is downloaded on first run and cached in
`~/.cache/pauk-maps/`; only the 16 features with iso_a2 = DE
are used. City coordinates and the Autobahn graph
(`content/autobahn-graph.json`) are hand-curated; graph
kilometers are approximate road distances (about +/-10%).

## How to regenerate

The scripts are pure Python except for the SVG-to-PNG step,
which needs cairosvg (build-time dependency only; do not add it
to the app environments):

    python3 -m venv /tmp/mapsenv
    /tmp/mapsenv/bin/pip install cairosvg
    /tmp/mapsenv/bin/python scripts/maps/generate_state_maps.py

This rewrites all files in `content/maps/` deterministically.

To render a route (writes OUT.svg + OUT.png, prints total km
and the per-leg breakdown as JSON on stdout; exits non-zero
naming the valid neighbors if two consecutive nodes are not
connected by an edge):

    /tmp/mapsenv/bin/python scripts/maps/render_route.py \
        content/autobahn-graph.json /tmp/route.svg \
        muenchen ingolstadt nuernberg bayreuth hof leipzig \
        potsdam berlin

## File inventory

- `mapdraw.py` — shared module: data download/cache, state
  loading, equirectangular projection, polygon simplification,
  SVG assembly, PNG rasterization.

- `generate_state_maps.py` — writes `content/maps/germany.svg`
  / `.png` (overview) and `content/maps/de-<state-slug>.svg` /
  `.png` (one per state, highlighted), 34 files total. All maps
  are ~600x800 and show the ~20 largest cities as labelled dots
  (Bochum and Wuppertal are replaced by Karlsruhe and Mannheim
  for label legibility in the Ruhr area).

- `render_route.py` — draws a node path from
  `content/autobahn-graph.json` on the base map with start/end
  markers.

- `../../content/autobahn-graph.json` — hand-curated major
  Autobahn network: 45 nodes (cities plus the Kirchheimer
  Dreieck and Dreieck Wittstock interchanges), 63 undirected
  edges covering A1-A10, A14, A19, A20, A24, A38, A44, A45,
  A46, A61, A66, A81 and A93.

- `../../content/germany-maps.json` — 16 multiple-choice cards
  ("Which Bundesland is highlighted on this map?") in dir
  `germany/bundeslaender/maps`; distractors are adjacent
  states. The `media:maps/...` image prefix is a placeholder
  the importer replaces with the uploaded file URL.
