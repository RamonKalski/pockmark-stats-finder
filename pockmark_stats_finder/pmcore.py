# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: MIT
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
"""
The measuring part of Pockmark Stats Finder. It needs only NumPy, so it
runs inside QGIS with nothing extra to install.

For each outline it works out: the center, the deepest point near the
center (after taking away the general tilt of the seafloor), how deep the
pit is below its rim and how much it holds, its shape and direction, the
slopes, the nearest other pit, and whether it sits inside another pit.
"""
import math
import numpy as np

SETTINGS = {
    "center_zone": 0.5,   # look for the bottom within this share of the pit's radius from its center
    "ring_width": 0.6,    # width of the seafloor strip outside the outline (share of the pit's radius,
                          # at least 4 cells), used to find the tilt of the seafloor
    "min_cells": 9,       # outlines covering fewer grid cells get the flag few_cells
    "shallow_m": 0.05,    # pits less deep than this below the rim get the flag shallow
    "max_slope_deg": 45,  # pits with walls steeper than this on average get the flag very_steep
}

# the output columns, in order, and what each holds: a whole number ("int"),
# a decimal number ("float") or text
COLUMNS = [
    ("pockmark_id", "int"), ("flags", "text"), ("center_x", "float"), ("center_y", "float"),
    ("bottom_x", "float"), ("bottom_y", "float"), ("bottom_offset_m", "float"),
    ("bottom_offset_azimuth_deg", "float"), ("bottom_is_deepest", "int"),
    ("area_m2", "float"), ("perimeter_m", "float"), ("equiv_diameter_m", "float"),
    ("rim_depth_m", "float"), ("rim_depth_min_m", "float"), ("rim_depth_max_m", "float"),
    ("bottom_depth_m", "float"), ("deepest_depth_m", "float"),
    ("depth_below_rim_m", "float"), ("max_depth_below_rim_m", "float"),
    ("mean_depth_below_rim_m", "float"), ("rim_spread_m", "float"), ("volume_m3", "float"),
    ("depth_to_diameter", "float"), ("volume_ratio", "float"),
    ("ellipse_major_m", "float"), ("ellipse_minor_m", "float"), ("elongation", "float"),
    ("long_axis_azimuth_deg", "float"), ("box_length_m", "float"), ("box_width_m", "float"),
    ("circularity", "float"), ("solidity", "float"), ("convexity", "float"),
    ("mean_slope_inside_deg", "float"), ("steep_slope_inside_deg", "float"),
    ("seafloor_slope_deg", "float"), ("seafloor_downslope_azimuth_deg", "float"),
    ("long_axis_vs_downslope_deg", "float"),
    ("nearest_id", "int"), ("nearest_distance_m", "float"), ("inside_of", "int"),
    ("n_inside", "int"), ("n_cells", "int"), ("nodata_fraction", "float"),
    ("deepest_x", "float"), ("deepest_y", "float"),
]


class Grid:
    """
    The depth grid, read one small block at a time.
    read(r0, r1, c0, c1) gives heights (negative below sea level) for rows
    r0 to r1 and columns c0 to c1, with NaN where there is no data.
    x0 is the left edge, y_top the top edge, cell the cell size in meters.
    """

    def __init__(self, read, nrows, ncols, x0, y_top, cell):
        self.read, self.nrows, self.ncols = read, nrows, ncols
        self.x0, self.y_top, self.cell = x0, y_top, cell

    def to_rc(self, x, y):
        """Map position to row and column (whole numbers are cell centers)."""
        return (self.y_top - np.asarray(y)) / self.cell - 0.5, (np.asarray(x) - self.x0) / self.cell - 0.5

    def to_xy(self, r, c):
        """Row and column to map position."""
        return self.x0 + (c + 0.5) * self.cell, self.y_top - (r + 0.5) * self.cell

    def window(self, r0, r1, c0, c1):
        """A block of the grid (cut to fit) and its first row and column."""
        r0, c0 = max(int(r0), 0), max(int(c0), 0)
        r1, c1 = min(int(r1), self.nrows), min(int(c1), self.ncols)
        if r1 <= r0 or c1 <= c0:
            return np.zeros((0, 0)), r0, c0
        return np.asarray(self.read(r0, r1, c0, c1), dtype="float64"), r0, c0


# ----------------------------------------------------------------------
# Helpers for outlines and grids
# ----------------------------------------------------------------------


def close_ring(p):
    """Make sure the outline ends exactly where it starts."""
    p = np.asarray(p, float)
    return p if np.array_equal(p[0], p[-1]) else np.vstack([p, p[:1]])


def signed_area(p):
    """Area of the outline: positive if drawn counterclockwise, negative if clockwise."""
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def inside_ring(px, py, ring):
    """True for points inside the outline.
    A point is inside if a line from it to the right crosses the outline
    an odd number of times."""
    px, py = np.asarray(px, float), np.asarray(py, float)
    out = np.zeros(px.shape, bool)
    x1, y1 = ring[:-1, 0], ring[:-1, 1]
    x2, y2 = ring[1:, 0], ring[1:, 1]
    for a, b, c, d in zip(x1, y1, x2, y2):
        crosses = (b > py) != (d > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = a + (py - b) * (c - a) / (d - b)
        out ^= crosses & (px < xc)
    return out


def distance_to_ring(px, py, ring):
    """Distance from each point to the nearest edge of the outline."""
    best = np.full(np.shape(px), np.inf)
    for (a, b), (c, d) in zip(ring[:-1], ring[1:]):
        dx, dy = c - a, d - b
        L = dx * dx + dy * dy
        t = np.clip(((px - a) * dx + (py - b) * dy) / L, 0, 1) if L > 0 else 0.0
        best = np.minimum(best, np.hypot(px - a - t * dx, py - b - t * dy))
    return best


def distance_to_cells(mask):
    """Distance (in cells) from every cell to the nearest cell where mask is True."""
    pr, pc = np.nonzero(mask)
    rr, cc = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    rr, cc = rr.ravel(), cc.ravel()
    best = np.full(rr.size, np.inf)
    for s in range(0, len(pr), 256):                       # 256 at a time, to save memory
        d2 = (rr[:, None] - pr[None, s:s + 256]) ** 2 + (cc[:, None] - pc[None, s:s + 256]) ** 2
        best = np.minimum(best, d2.min(1))
    return np.sqrt(best).reshape(mask.shape)


def convex_hull(pts):
    """Corners of the outline with its dents filled in (its "convex hull"),
    going counterclockwise. Points are taken in order, and any point that
    would make a dent is dropped."""
    P = sorted(set(map(tuple, pts)))
    if len(P) < 3:
        return np.array(P)

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in P:
        while len(lo) >= 2 and turn(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(hi) >= 2 and turn(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return np.array(lo[:-1] + hi[:-1])


def crosses_itself(p):
    """True if any two edges of the outline cross, like a bow tie."""
    a, b = p[:-1], p[1:]
    n = len(a)
    if n < 4:
        return False

    def side(p0, p1, q):
        return np.sign((p1[..., 0] - p0[..., 0]) * (q[..., 1] - p0[..., 1])
                       - (p1[..., 1] - p0[..., 1]) * (q[..., 0] - p0[..., 0]))
    A, B, C, D = a[:, None], b[:, None], a[None], b[None]
    hit = (side(A, B, C) * side(A, B, D) < 0) & (side(C, D, A) * side(C, D, B) < 0)
    i, j = np.triu_indices(n, k=2)
    keep = ~((i == 0) & (j == n - 1))
    return bool(hit[i[keep], j[keep]].any())


def bilinear(f, r, c):
    """Values of grid f at points between cell centers, blended from the
    four nearest cells."""
    r = np.clip(r, 0, f.shape[0] - 1)
    c = np.clip(c, 0, f.shape[1] - 1)
    r0, c0 = np.floor(r).astype(int), np.floor(c).astype(int)
    r1, c1 = np.minimum(r0 + 1, f.shape[0] - 1), np.minimum(c0 + 1, f.shape[1] - 1)
    fr, fc = r - r0, c - c0
    return ((1 - fr) * (1 - fc) * f[r0, c0] + (1 - fr) * fc * f[r0, c1]
            + fr * (1 - fc) * f[r1, c0] + fr * fc * f[r1, c1])


def robust_plane(z, use):
    """Fit a tilted flat surface to the seafloor cells in `use`, ignoring the
    30% of cells that fit worst (bumps, other pits). Gives its height at the
    first cell and its rise per column and per row."""
    r, c = np.nonzero(use & np.isfinite(z))
    if len(r) < 10:
        return None
    A = np.column_stack([np.ones(len(r)), c, r])
    v = z[r, c]
    keep = np.ones(len(r), bool)
    for _ in range(3):
        coef = np.linalg.lstsq(A[keep], v[keep], rcond=None)[0]
        res = np.abs(v - A @ coef)
        keep = res <= np.percentile(res, 70)
    return coef


# ----------------------------------------------------------------------
# Shape, from the outline alone
# ----------------------------------------------------------------------


def shape_stats(p):
    """Size, shape and direction, from the outline alone."""
    # area and center of the outline (moved near zero first, so the math stays precise)
    q = p - p[:-1].mean(0)
    x, y = q[:-1, 0], q[:-1, 1]
    x1, y1 = q[1:, 0], q[1:, 1]
    cr = x * y1 - x1 * y
    a = cr.sum() / 2
    if abs(a) < 1e-12:
        return None
    cx = ((x + x1) * cr).sum() / (6 * a)
    cy = ((y + y1) * cr).sum() / (6 * a)
    # how the area spreads out around its center gives the ellipse with the
    # same spread, and from that the long axis, short axis and long-axis direction
    sxx = ((y * y + y * y1 + y1 * y1) * cr).sum() / 12 / a - cy * cy
    syy = ((x * x + x * x1 + x1 * x1) * cr).sum() / 12 / a - cx * cx
    sxy = ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * cr).sum() / 24 / a - cx * cy
    area = abs(a)
    per = float(np.hypot(*np.diff(p, axis=0).T).sum())
    lam = np.linalg.eigvalsh(np.array([[syy, sxy], [sxy, sxx]]))
    major, minor = 4 * math.sqrt(max(lam[1], 0)), 4 * math.sqrt(max(lam[0], 0))
    azimuth = (90 - 0.5 * math.degrees(math.atan2(2 * sxy, syy - sxx))) % 180   # degrees clockwise from north
    # convex hull (outline with the dents filled in)
    hp = convex_hull(q[:-1])
    hull_ring = np.vstack([hp, hp[:1]])
    hull_area = abs(signed_area(hull_ring))
    hull_per = float(np.hypot(*np.diff(hull_ring, axis=0).T).sum())
    # smallest rectangle around the outline: one of its sides always lies along
    # an edge of the dent-free outline, so try each edge
    best = None
    for k in range(len(hp)):
        e = hp[(k + 1) % len(hp)] - hp[k]
        u = e / np.hypot(*e)
        pu, pv = hp @ u, hp @ np.array([-u[1], u[0]])
        w, h = np.ptp(pu), np.ptp(pv)
        if best is None or w * h < best[0]:
            best = (w * h, max(w, h), min(w, h))
    return {
        "center_x": float(cx + p[:-1, 0].mean()), "center_y": float(cy + p[:-1, 1].mean()),
        "area_m2": area, "perimeter_m": per, "equiv_diameter_m": 2 * math.sqrt(area / math.pi),
        "ellipse_major_m": major, "ellipse_minor_m": minor,
        "elongation": major / minor if minor > 0 else None,
        "long_axis_azimuth_deg": azimuth if major > 1.02 * minor else None,
        "box_length_m": best[1], "box_width_m": best[2],
        "circularity": 4 * math.pi * area / per ** 2,
        "solidity": area / hull_area if hull_area > 0 else None,
        "convexity": hull_per / per,
    }


# ----------------------------------------------------------------------
# Depth, from the outline and the grid
# ----------------------------------------------------------------------


def depth_stats(grid, p, sh, others, S):
    """Depth, volume, slopes and bottom point for one outline.
    others: nearby outlines, kept out of the seafloor strip."""
    out, flags = {}, []
    cell = grid.cell
    r_eq = sh["equiv_diameter_m"] / 2 / cell                      # pit radius, in cells
    ring_w = max(4.0, S["ring_width"] * r_eq)
    # read the part of the grid around the outline
    rr, cc = grid.to_rc(p[:, 0], p[:, 1])
    pad = int(math.ceil(ring_w)) + 3
    z, r0, c0 = grid.window(rr.min() - pad, rr.max() + pad + 1, cc.min() - pad, cc.max() + pad + 1)
    if z.size == 0:
        return out, ["outside_grid"]
    if r0 == 0 or c0 == 0 or r0 + z.shape[0] == grid.nrows or c0 + z.shape[1] == grid.ncols:
        flags.append("near_grid_edge")
    # cells whose centers lie inside the outline
    yy, xx = np.mgrid[0:z.shape[0], 0:z.shape[1]]
    X, Y = grid.to_xy(yy + r0, xx + c0)                            # cell centers
    valid = np.isfinite(z)
    inside = inside_ring(X, Y, p)
    n_cells = int(inside.sum())
    out["n_cells"] = n_cells
    if n_cells == 0:
        return out, flags + ["no_cells"]
    out["nodata_fraction"] = float((inside & ~valid).sum() / n_cells)
    if out["nodata_fraction"] > 0.05:
        flags.append("nodata_inside")
    if n_cells < S["min_cells"]:
        flags.append("few_cells")
    inside &= valid
    if not inside.any():
        return out, flags + ["no_data"]

    # tilt of the seafloor, from a strip just outside the outline (other pockmarks left out)
    d_out = distance_to_cells(inside)
    use = (d_out > 1) & (d_out <= ring_w) & valid
    for q in others:
        use &= ~inside_ring(X, Y, q)
    coef = robust_plane(z, use)
    resid = z - (coef[0] + coef[1] * xx + coef[2] * yy) if coef is not None else z.copy()

    # bottom: the deepest cell near the center, once the seafloor tilt is taken away
    crow, ccol = grid.to_rc(sh["center_x"], sh["center_y"])
    near = inside & (np.hypot(yy - (crow - r0), xx - (ccol - c0)) <= max(S["center_zone"] * r_eq, 1.5))
    if not inside_ring(np.array([sh["center_x"]]), np.array([sh["center_y"]]), p)[0]:
        flags.append("center_outside_outline")
    if not near.any():
        near = inside
    b = np.unravel_index(np.argmin(np.where(near, resid, np.inf)), z.shape)
    d = np.unravel_index(np.argmin(np.where(inside, resid, np.inf)), z.shape)
    bx, by = grid.to_xy(b[0] + r0, b[1] + c0)
    dx, dy = grid.to_xy(d[0] + r0, d[1] + c0)
    off = math.hypot(bx - sh["center_x"], by - sh["center_y"])
    out.update({
        "bottom_x": float(bx), "bottom_y": float(by), "bottom_depth_m": float(-z[b]),
        "bottom_offset_m": off,
        "bottom_offset_azimuth_deg": math.degrees(math.atan2(bx - sh["center_x"], by - sh["center_y"])) % 360
        if off > 0 else None,
        "deepest_x": float(dx), "deepest_y": float(dy), "deepest_depth_m": float(-z[d]),
        "bottom_is_deepest": int(b == d),
    })

    # rim: depths read along the outline every half cell
    seg = np.hypot(*np.diff(p, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.arange(0, s[-1], cell / 2)
    lr, lc = grid.to_rc(np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1]))
    lr, lc = lr - r0, lc - c0

    def along(f):
        """Values of f along the outline (empty cells filled with the typical value)."""
        return bilinear(np.where(np.isfinite(f), f, np.nanmedian(f[valid])), lr, lc)
    rim_raw = along(z)
    out["rim_depth_m"] = float(-np.median(rim_raw))
    out["rim_depth_min_m"] = float(-rim_raw.max())
    out["rim_depth_max_m"] = float(-rim_raw.min())

    # slopes inside the outline, from the grid as it is
    gy, gx = np.gradient(z, cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    sl = slope[inside & np.isfinite(slope)]
    if sl.size:
        out["mean_slope_inside_deg"] = float(sl.mean())
        if sl.mean() > S["max_slope_deg"]:
            flags.append("very_steep")              # walls this steep suggest the wrong grid
        out["steep_slope_inside_deg"] = float(np.percentile(sl, 95))

    # slope of the seafloor around the pit, and which way is downhill
    if coef is None:
        return out, flags + ["no_plane"]
    dzdx, dzdy = coef[1] / cell, -coef[2] / cell                   # rise per meter east, north
    out["seafloor_slope_deg"] = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    down = math.degrees(math.atan2(-dzdx, -dzdy)) % 360
    out["seafloor_downslope_azimuth_deg"] = down
    if sh["long_axis_azimuth_deg"] is not None:
        diff = abs((sh["long_axis_azimuth_deg"] - down) % 180)
        out["long_axis_vs_downslope_deg"] = min(diff, 180 - diff)

    # depth and volume below the rim level, with the seafloor tilt taken away
    rim = along(resid)
    rim_level = float(np.median(rim))
    rin = resid[inside]
    area_cells = inside.sum() * cell ** 2
    D = float(rim_level - rin.min())
    vol = float(np.clip(rim_level - rin, 0, None).sum() * cell ** 2)
    out.update({
        "rim_spread_m": float(np.percentile(rim, 90) - np.percentile(rim, 10)),
        "depth_below_rim_m": float(rim_level - resid[b]), "max_depth_below_rim_m": D,
        "volume_m3": vol, "mean_depth_below_rim_m": vol / area_cells,
        "depth_to_diameter": D / sh["equiv_diameter_m"] if D > 0 else None,
        "volume_ratio": vol / (area_cells * D) if D > 0 else None,
    })
    if D <= 0:
        flags.append("not_a_dip")
    elif D < S["shallow_m"]:
        flags.append("shallow")
    return out, flags


# ----------------------------------------------------------------------
# All outlines
# ----------------------------------------------------------------------


def measure_all(grid, outlines, settings=None, progress=None, cancelled=None):
    """
    Measure every outline.
    outlines: a list of (id, polygons). Each polygon is a list of rings, and
    each ring is a list of x, y points.
    progress(share_done) and cancelled() are optional: one reports progress,
    the other lets the person running it stop early.
    Gives one set of results per outline, and the ring that was measured.
    """
    S = dict(SETTINGS, **(settings or {}))

    # one ring per outline: its largest part, without holes
    rings, notes = [], []
    for _, polys in outlines:
        parts = [close_ring(poly[0]) for poly in polys if len(poly) and len(poly[0]) >= 3]
        note = []
        if len(parts) > 1:
            note.append("multipart")
        if any(len(poly) > 1 for poly in polys):
            note.append("hole_ignored")
        rings.append(max(parts, key=lambda r: abs(signed_area(r))) if parts else None)
        notes.append(note)
    boxes = np.array([_box(r) for r in rings])

    # measure each outline
    rows = []
    for k, ((oid, _), p) in enumerate(zip(outlines, rings)):
        if cancelled and cancelled():
            break
        row, flags = {"pockmark_id": oid}, list(notes[k])
        if p is None or len(p) < 4:
            flags.append("no_shape")
        elif crosses_itself(p):
            flags.append("crosses_itself")              # fix it in QGIS
        else:
            sh = shape_stats(p)
            if sh is None:
                flags.append("no_shape")
            else:
                row.update(sh)
                # nearby outlines are kept out of the seafloor strip, except a
                # larger pit that surrounds this one
                reach = 3 * sh["equiv_diameter_m"] + 4 * grid.cell
                x0, y0, x1, y1 = _box(p)
                near = np.nonzero((boxes[:, 0] < x1 + reach) & (boxes[:, 2] > x0 - reach) &
                                  (boxes[:, 1] < y1 + reach) & (boxes[:, 3] > y0 - reach))[0]
                cx, cy = np.array([sh["center_x"]]), np.array([sh["center_y"]])
                others = [rings[j] for j in near
                          if j != k and rings[j] is not None and not inside_ring(cx, cy, rings[j])[0]]
                dep, f2 = depth_stats(grid, p, sh, others, S)
                row.update(dep)
                flags += f2
        row["flags"] = ";".join(flags)
        rows.append(row)
        if progress:
            progress((k + 1) / len(outlines))
    # nearest neighbor and nesting, once every center is known
    _neighbors(rows, rings[:len(rows)])
    return rows, rings[:len(rows)]


def _box(r):
    """Box around an outline: smallest x, smallest y, largest x, largest y."""
    if r is None:
        return [np.nan] * 4
    return [r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max()]


def _neighbors(rows, rings):
    """Nearest other center, and the smallest larger outline holding each center."""
    idx = [i for i, r in enumerate(rows) if r.get("center_x") is not None]
    if not idx:
        return
    xy = np.array([[rows[i]["center_x"], rows[i]["center_y"]] for i in idx])

    # nearest other center (worked out 500 at a time, to save memory)
    for start in range(0, len(idx), 500):
        block = xy[start:start + 500]
        dist = np.hypot(block[:, None, 0] - xy[None, :, 0], block[:, None, 1] - xy[None, :, 1])
        for a in range(len(block)):
            dist[a, start + a] = np.inf                     # not itself
            j = int(dist[a].argmin())
            if np.isfinite(dist[a, j]):
                rows[idx[start + a]]["nearest_id"] = rows[idx[j]]["pockmark_id"]
                rows[idx[start + a]]["nearest_distance_m"] = float(dist[a, j])

    # nesting: the smallest larger outline that holds this one's center
    area = np.array([rows[i]["area_m2"] for i in idx])
    boxes = np.array([_box(rings[i]) for i in idx])
    for a, i in enumerate(idx):
        x, y = xy[a]
        cand = np.nonzero((boxes[:, 0] <= x) & (boxes[:, 2] >= x) &
                          (boxes[:, 1] <= y) & (boxes[:, 3] >= y) & (area > area[a]))[0]
        cand = [c for c in cand if inside_ring(np.array([x]), np.array([y]), rings[idx[c]])[0]]
        if cand:
            parent = idx[min(cand, key=lambda c: area[c])]
            rows[i]["inside_of"] = rows[parent]["pockmark_id"]
            rows[parent]["n_inside"] = rows[parent].get("n_inside", 0) + 1
    for i in idx:
        rows[i].setdefault("n_inside", 0)
