# Changes

## 1.0.1 (2026-11-20)

- QGIS 4 can now install the plugin. The plugin info said it only worked up to
  QGIS 3.99, so QGIS 4 refused it. The tool itself is unchanged.

## 1.0.0 (2026-11-20)

First public release.

- For every pockmark outline: the center, the deepest point near the center,
  depth and volume below the rim, shape, direction, slopes, the nearest other
  pockmark, and whether it sits inside another one.
- Results as three new QGIS layers: outlines with all numbers, centers, bottoms.
- Flags for outlines worth checking (too few grid cells, missing data, an outline
  that crosses itself, and more).
- Refuses grids that look like pictures, such as a hillshade.
- Checks on made-up pits with known answers (`tests/test_pmcore.py`).
