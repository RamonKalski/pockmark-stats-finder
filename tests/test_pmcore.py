# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: MIT
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
"""
Checks the measuring code on made-up pits whose true size, depth, volume
and orientation are known. Needs only NumPy (no QGIS).

Run from the repository folder:   python tests/test_pmcore.py
(or with pytest:                  python -m pytest tests)
"""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pockmark_stats_finder"))
import pmcore

CELL = 1.0                    # grid cell size, meters
X0, Y_TOP = 560000.0, 4156000.0


# ----------------------------------------------------------------------
# Make a test seafloor: a 2 degree slope with one pit in the middle
# ----------------------------------------------------------------------

def make_site(shape, radius, depth, stretch=1.0, azimuth=0.0, n=160):
    """Seafloor with one pit. stretch > 1 makes an ellipse whose long axis
    points toward `azimuth` (degrees from north). Returns grid, outline, center."""
    rows, cols = np.mgrid[0:n, 0:n]
    x = X0 + (cols + 0.5) * CELL
    y = Y_TOP - (rows + 0.5) * CELL
    xc, yc = x.mean(), y.mean()

    # sloping seafloor, downhill toward the south-east (135 degrees)
    tilt = math.tan(math.radians(2.0))
    z = -150 - tilt * ((x - xc) * math.sin(math.radians(135)) + (y - yc) * math.cos(math.radians(135)))

    # the pit, in coordinates turned to line up with its long axis
    t = math.radians(90 - azimuth)
    u = ((x - xc) * math.cos(t) + (y - yc) * math.sin(t)) / stretch
    v = -(x - xc) * math.sin(t) + (y - yc) * math.cos(t)
    q = np.hypot(u, v) / radius
    pit = -depth * (1 - q ** 2) if shape == "bowl" else -depth * (1 - q)
    z += np.where(q < 1, pit, 0.0)

    # the true outline: the pit's rim
    a = np.linspace(0, 2 * math.pi, 200, endpoint=False)
    ox = xc + radius * stretch * np.cos(a) * math.cos(t) - radius * np.sin(a) * math.sin(t)
    oy = yc + radius * stretch * np.cos(a) * math.sin(t) + radius * np.sin(a) * math.cos(t)
    outline = np.column_stack([ox, oy])

    grid = pmcore.Grid(lambda r0, r1, c0, c1: z[r0:r1, c0:c1], n, n, X0, Y_TOP, CELL)
    return grid, outline, (xc, yc)


def measure(grid, outline):
    """Measure one outline."""
    rows, _ = pmcore.measure_all(grid, [(1, [[outline]])])
    return rows[0]


def close(a, b, share):
    """True if a is within `share` (e.g. 0.1 = 10%) of b."""
    return abs(a - b) <= share * abs(b)


# ----------------------------------------------------------------------
# The checks
# ----------------------------------------------------------------------

def test_bowl_size_depth_volume():
    grid, outline, (xc, yc) = make_site("bowl", radius=12, depth=1.0)
    r = measure(grid, outline)
    assert close(r["area_m2"], math.pi * 12 ** 2, 0.01)
    assert close(r["max_depth_below_rim_m"], 1.0, 0.05)
    assert close(r["volume_m3"], math.pi * 12 ** 2 * 1.0 / 2, 0.08)      # a bowl holds half of a same-size cylinder
    assert close(r["volume_ratio"], 0.5, 0.05)
    assert math.hypot(r["bottom_x"] - xc, r["bottom_y"] - yc) <= CELL     # bottom found at the middle
    assert r["flags"] == ""


def test_cone_volume_ratio():
    grid, outline, _ = make_site("cone", radius=12, depth=1.0)
    r = measure(grid, outline)
    assert close(r["volume_ratio"], 1 / 3, 0.08)                          # a cone holds a third of a same-size cylinder


def test_seafloor_slope_and_direction():
    grid, outline, _ = make_site("bowl", radius=12, depth=1.0)
    r = measure(grid, outline)
    assert abs(r["seafloor_slope_deg"] - 2.0) < 0.05
    assert abs(r["seafloor_downslope_azimuth_deg"] - 135.0) < 1.0


def test_ellipse_orientation_and_elongation():
    grid, outline, _ = make_site("bowl", radius=8, depth=1.0, stretch=2.0, azimuth=30)
    r = measure(grid, outline)
    assert abs(r["long_axis_azimuth_deg"] - 30.0) < 0.5
    assert close(r["elongation"], 2.0, 0.01)


def test_crossing_outline_is_flagged():
    grid, _, (xc, yc) = make_site("bowl", radius=12, depth=1.0)
    bow_tie = np.array([(xc - 8, yc - 8), (xc + 8, yc + 8), (xc + 8, yc - 8), (xc - 8, yc + 8)])
    r = measure(grid, bow_tie)
    assert "crosses_itself" in r["flags"]


def test_small_pit_inside_large_one():
    grid, outline, (xc, yc) = make_site("bowl", radius=20, depth=2.0)
    a = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    small = np.column_stack([xc + 6 + 3 * np.cos(a), yc + 3 * np.sin(a)])
    rows, _ = pmcore.measure_all(grid, [(1, [[outline]]), (2, [[small]])])
    assert rows[1]["inside_of"] == 1 and rows[0]["n_inside"] == 1
    assert rows[1].get("max_depth_below_rim_m") is not None                # still measured


# ----------------------------------------------------------------------
# Run all checks when the file is run directly
# ----------------------------------------------------------------------

if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for f in tests:
        f()
        print(f"ok   {f.__name__}")
    print(f"All {len(tests)} checks passed.")
