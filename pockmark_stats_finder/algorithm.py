# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: GPL-2.0-or-later
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
"""
The Pockmark Stats Finder tool, as a QGIS Processing algorithm.

QGIS builds the tool's box from the inputs listed in initAlgorithm():
a grid dropdown, an outline-layer dropdown and a Run button. When Run is
clicked, processAlgorithm() does the work in five steps:
  1. open the grid and read the outlines
  2. measure every outline (the math is in pmcore.py)
  3. make the three output layers
  4. fill them with the outlines and points
  5. report flags and style the new layers
"""
import numpy as np
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform, QgsFeature, QgsFeatureSink, QgsField, QgsFields, QgsGeometry,
    QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface, QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer, QgsWkbTypes, QgsUnitTypes,
)
from . import pmcore

try:
    from qgis.core import Qgis
except ImportError:
    Qgis = None

# ----------------------------------------------------------------------
# Names that differ between QGIS versions
# Newer QGIS renamed some settings. For each one, use the new name if this
# QGIS has it, otherwise the old one.
# ----------------------------------------------------------------------


def _name(new, old):
    """Whichever of two names this QGIS has, e.g. ("Qgis", "WkbType", "Point")."""
    for path in (new, old):
        obj = globals().get(path[0])
        try:
            for part in path[1:]:
                obj = getattr(obj, part)
            return obj
        except AttributeError:
            continue
    raise ImportError(f"{'.'.join(new)} not found in this QGIS")


POLYGON_LAYER = _name(("Qgis", "ProcessingSourceType", "VectorPolygon"), ("QgsProcessing", "TypeVectorPolygon"))
POINT_LAYER = _name(("Qgis", "ProcessingSourceType", "VectorPoint"), ("QgsProcessing", "TypeVectorPoint"))
MULTIPOLYGON = _name(("Qgis", "WkbType", "MultiPolygon"), ("QgsWkbTypes", "MultiPolygon"))
POINT = _name(("Qgis", "WkbType", "Point"), ("QgsWkbTypes", "Point"))
METERS = _name(("Qgis", "DistanceUnit", "Meters"), ("QgsUnitTypes", "DistanceMeters"))
FAST = _name(("QgsFeatureSink", "Flag", "FastInsert"), ("QgsFeatureSink", "FastInsert"))
ADVANCED = _name(("Qgis", "ProcessingParameterFlag", "Advanced"),
                 ("QgsProcessingParameterDefinition", "FlagAdvanced"))
DECIMAL = _name(("Qgis", "ProcessingNumberParameterType", "Double"), ("QgsProcessingParameterNumber", "Double"))


def _field_types():
    """Column types for whole numbers, decimals and text (newer QGIS names them differently)."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        types = {"int": QMetaType.Type.Int, "float": QMetaType.Type.Double, "text": QMetaType.Type.QString}
        QgsField("test", types["float"])        # fails on older QGIS
        return types
    except Exception:
        return {"int": QVariant.Int, "float": QVariant.Double, "text": QVariant.String}


# ----------------------------------------------------------------------
# Layer styles
# Colors suit color-blind viewers: orange outlines, black center crosses,
# blue bottom dots.
# ----------------------------------------------------------------------

_KEEP = []          # QGIS needs the style settings kept until it uses them


class _Style(QgsProcessingLayerPostProcessorInterface):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind

    def postProcessLayer(self, layer, context, feedback):
        try:
            from qgis.core import QgsFillSymbol, QgsMarkerSymbol
            if self.kind == "outline":
                sym = QgsFillSymbol.createSimple(
                    {"color": "0,0,0,0", "outline_color": "230,159,0", "outline_width": "0.6"})
            elif self.kind == "center":
                sym = QgsMarkerSymbol.createSimple({"name": "cross2", "color": "0,0,0", "size": "2.5"})
            else:
                sym = QgsMarkerSymbol.createSimple(
                    {"name": "circle", "color": "0,114,178", "outline_color": "255,255,255", "size": "1.8"})
            layer.renderer().setSymbol(sym)
            layer.triggerRepaint()
        except Exception:
            pass                                 # a plain style is fine too


# ----------------------------------------------------------------------
# The tool
# ----------------------------------------------------------------------


class PockmarkStatsAlgorithm(QgsProcessingAlgorithm):
    GRID, OUTLINES, VALUES = "GRID", "OUTLINES", "VALUES"
    CENTER_ZONE, RING_WIDTH = "CENTER_ZONE", "RING_WIDTH"
    OUT_STATS, OUT_CENTERS, OUT_BOTTOMS = "OUT_STATS", "OUT_CENTERS", "OUT_BOTTOMS"
    VALUE_CHOICES = ["Automatic", "Elevation (negative down)", "Depth (positive down)"]

    # --- names and help text shown in QGIS ---

    def tr(self, text):
        return QCoreApplication.translate("PockmarkStats", text)

    def createInstance(self):
        return PockmarkStatsAlgorithm()

    def name(self):
        return "pockmarkstats"

    def displayName(self):
        return self.tr("Pockmark Stats Finder")

    def shortHelpString(self):
        return self.tr(
            "Measures every pockmark from your outlines.\n\n"
            "For each outline it finds the center and the deepest point near the center, "
            "and measures size, depth and volume below the rim, shape, direction, slopes, "
            "the nearest other pockmark, and whether it sits inside another one.\n\n"
            "Bathymetry grid: the depth grid itself (not a hillshade), in meters, in a map "
            "projection such as UTM.\n"
            "Pockmark outlines: one polygon per pockmark.\n\n"
            "You get three new layers: your outlines with all the numbers in the attribute "
            "table, the centers, and the bottoms. The 'flags' column notes anything to check. "
            "README.md in the plugin folder explains every column.")

    # --- the inputs and outputs that make up the tool's box ---

    def initAlgorithm(self, config=None):
        # inputs
        self.addParameter(QgsProcessingParameterRasterLayer(self.GRID, self.tr("Bathymetry grid")))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OUTLINES, self.tr("Pockmark outlines"), [POLYGON_LAYER]))
        self.addParameter(QgsProcessingParameterEnum(
            self.VALUES, self.tr("Grid values are"), self.VALUE_CHOICES, defaultValue=0))

        # settings, hidden under "Advanced Parameters"
        for key, label, value in (
                (self.CENTER_ZONE, "Bottom search zone (share of pit radius from the center)",
                 pmcore.SETTINGS["center_zone"]),
                (self.RING_WIDTH, "Seafloor strip width (share of pit radius)",
                 pmcore.SETTINGS["ring_width"])):
            p = QgsProcessingParameterNumber(key, self.tr(label), DECIMAL, value, minValue=0.05, maxValue=5)
            p.setFlags(p.flags() | ADVANCED)
            self.addParameter(p)

        # outputs (new layers)
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUT_STATS, self.tr("Pockmark stats"), POLYGON_LAYER))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUT_CENTERS, self.tr("Pockmark centers"), POINT_LAYER))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUT_BOTTOMS, self.tr("Pockmark bottoms"), POINT_LAYER))

    # --- what happens when Run is clicked ---

    def processAlgorithm(self, parameters, context, feedback):
        # 1. open the grid and read the outlines
        raster = self.parameterAsRasterLayer(parameters, self.GRID, context)
        source = self.parameterAsSource(parameters, self.OUTLINES, context)
        if raster is None:
            raise QgsProcessingException(self.invalidRasterError(parameters, self.GRID))
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.OUTLINES))
        crs = raster.crs()
        if crs.isGeographic() or crs.mapUnits() != METERS:
            raise QgsProcessingException("The grid must be in meters, in a map projection such as "
                                         "WGS 84 / UTM zone 18N. Reproject it and try again.")
        values = self.parameterAsEnum(parameters, self.VALUES, context)
        grid = self._open_grid(raster, values, feedback)
        feats, geoms, outlines = self._read_outlines(source, crs, context, feedback)

        # 2. measure every outline
        settings = {"center_zone": self.parameterAsDouble(parameters, self.CENTER_ZONE, context),
                    "ring_width": self.parameterAsDouble(parameters, self.RING_WIDTH, context)}
        feedback.pushInfo(f"Measuring {len(outlines)} outlines ...")
        rows, _ = pmcore.measure_all(grid, outlines, settings,
                                     progress=lambda fraction: feedback.setProgress(100 * fraction),
                                     cancelled=feedback.isCanceled)
        if not any(r.get("n_cells") for r in rows):
            raise QgsProcessingException("None of the outlines are on the grid. Check that the two "
                                         "layers cover the same area.")

        # 3. make the three output layers
        T = _field_types()
        stats_fields, keep = self._stats_fields(source, T)
        center_fields = QgsFields()
        center_fields.append(QgsField("pockmark_id", T["int"]))
        center_fields.append(QgsField("center_depth_m", T["float"]))
        bottom_fields = QgsFields()
        bottom_fields.append(QgsField("pockmark_id", T["int"]))
        bottom_fields.append(QgsField("bottom_depth_m", T["float"]))
        bottom_fields.append(QgsField("depth_below_rim_m", T["float"]))
        stats, stats_id = self.parameterAsSink(parameters, self.OUT_STATS, context,
                                               stats_fields, MULTIPOLYGON, crs)
        centers, centers_id = self.parameterAsSink(parameters, self.OUT_CENTERS, context,
                                                   center_fields, POINT, crs)
        bottoms, bottoms_id = self.parameterAsSink(parameters, self.OUT_BOTTOMS, context,
                                                   bottom_fields, POINT, crs)
        for sink, key in ((stats, self.OUT_STATS), (centers, self.OUT_CENTERS), (bottoms, self.OUT_BOTTOMS)):
            if sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, key))

        # 4. fill them with the outlines and points
        for f, g, row in zip(feats, geoms, rows):
            # outline with all its numbers, then the layer's own fields
            out = QgsFeature(stats_fields)
            shape = QgsGeometry(g)
            if not shape.isNull():
                shape.convertToMultiType()
                out.setGeometry(shape)
            numbers = [_plain(row.get(name), typ) for name, typ in pmcore.COLUMNS]
            own = [f.attributes()[i] for i in keep]
            out.setAttributes(numbers + own)
            stats.addFeature(out, FAST)

            # center point
            if row.get("center_x") is not None:
                c = QgsFeature(center_fields)
                c.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(row["center_x"], row["center_y"])))
                c.setAttributes([int(row["pockmark_id"]), _depth_at(grid, row["center_x"], row["center_y"])])
                centers.addFeature(c, FAST)

            # bottom point
            if row.get("bottom_x") is not None:
                b = QgsFeature(bottom_fields)
                b.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(row["bottom_x"], row["bottom_y"])))
                b.setAttributes([int(row["pockmark_id"]), _plain(row.get("bottom_depth_m"), "float"),
                                 _plain(row.get("depth_below_rim_m"), "float")])
                bottoms.addFeature(b, FAST)

        # 5. report flags and style the new layers
        counts = {}
        for row in rows:
            for flag in filter(None, (row.get("flags") or "").split(";")):
                counts[flag] = counts.get(flag, 0) + 1
        n_flagged = sum(1 for row in rows if row.get("flags"))
        feedback.pushInfo(f"Done: {len(rows)} pockmarks, {n_flagged} with flags to check.")
        if counts:
            feedback.pushInfo("Flags: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for dest, kind in ((stats_id, "outline"), (centers_id, "center"), (bottoms_id, "bottom")):
            if context.willLoadLayerOnCompletion(dest):
                style = _Style(kind)
                _KEEP.append(style)
                context.layerToLoadOnCompletionDetails(dest).setPostProcessor(style)
        return {self.OUT_STATS: stats_id, self.OUT_CENTERS: centers_id, self.OUT_BOTTOMS: bottoms_id}

    # --- step 1 helpers ---

    def _open_grid(self, raster, values, feedback):
        """Open the grid file. It is then read one small block at a time."""
        from osgeo import gdal
        ds = gdal.Open(raster.source())
        if ds is None:
            raise QgsProcessingException("Could not open the grid. Use a grid saved as a file (.tif or .asc).")

        # the grid must have north at the top and square cells
        gt = ds.GetGeoTransform()          # left edge, cell width, 0, top edge, 0, -cell height
        if gt[2] != 0 or gt[4] != 0:
            raise QgsProcessingException("The grid is rotated. Save it again without rotation.")
        if gt[5] > 0:
            raise QgsProcessingException("The grid has south at the top. Save it again with north at the top.")
        cell = gt[1]
        if abs(abs(gt[5]) - cell) > 1e-6 * cell:
            raise QgsProcessingException(f"Grid cells are not square ({gt[1]} x {abs(gt[5])}).")
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        ny, nx = ds.RasterYSize, ds.RasterXSize

        def clean(a):
            """Mark empty cells as empty (NaN)."""
            a = a.astype("float64")
            if nodata is not None:
                a[np.isclose(a, nodata)] = np.nan
            a[np.abs(a) > 1e30] = np.nan
            return a

        # a quick look at the whole grid (at most 512 x 512 values)
        sample = clean(band.ReadAsArray(0, 0, nx, ny, buf_xsize=min(nx, 512), buf_ysize=min(ny, 512)))
        found = sample[np.isfinite(sample)]
        if found.size == 0:
            raise QgsProcessingException("The grid is empty.")

        # refuse pictures such as a hillshade (whole numbers from 0 to 255)
        picture = band.DataType == gdal.GDT_Byte or (
            found.min() >= 0 and found.max() <= 255 and np.allclose(found, np.round(found)))
        if values == 0 and picture:
            raise QgsProcessingException(
                f"'{raster.name()}' looks like a picture (whole numbers from 0 to 255, such as a "
                "hillshade), not depths. Pick the depth grid. If this really is a depth grid, "
                "set 'Grid values are' by hand and run again.")

        # are the values depths (positive) or heights (negative below sea level)?
        median = float(np.median(found))
        if values == 0:
            values = 2 if median > 0 else 1
            feedback.pushInfo(f"The grid values look like {'depths (positive)' if values == 2 else 'heights (negative below sea level)'}, "
                              f"middle value {median:.1f}. If that is wrong, set 'Grid values are' by hand.")
        sign = -1.0 if values == 2 else 1.0          # the math works with heights

        def read(r0, r1, c0, c1):
            """One block of the grid, as heights, with empty cells marked."""
            return sign * clean(band.ReadAsArray(int(c0), int(r0), int(c1 - c0), int(r1 - r0)))

        grid = pmcore.Grid(read, ny, nx, gt[0], gt[3], cell)
        grid._ds, grid._band = ds, band             # keep the file open while measuring
        feedback.pushInfo(f"Grid: {nx} x {ny} cells of {cell:g} m")
        return grid

    def _read_outlines(self, source, crs, context, feedback):
        """The outlines as lists of x, y points, moved into the grid's map projection if needed."""
        xform = None
        if source.sourceCrs() != crs:
            xform = QgsCoordinateTransform(source.sourceCrs(), crs, context.transformContext())
            feedback.pushInfo("The outlines are in a different map projection; they are converted to the grid's.")

        feats, geoms, outlines = [], [], []
        warned = False
        for f in source.getFeatures():
            if f.id() < 0 and not warned:            # QGIS gives unsaved features negative ids
                feedback.pushWarning("Some outlines are not saved yet (their ids are negative). "
                                     "Save Layer Edits so pockmark_id stays the same between runs.")
                warned = True
            g = QgsGeometry(f.geometry())
            polys = []
            if not g.isNull() and not g.isEmpty():
                if xform is not None:
                    g.transform(xform)
                if QgsWkbTypes.isCurvedType(g.wkbType()):
                    g = QgsGeometry(g.constGet().segmentize())     # curves to straight edges
                parts = g.asMultiPolygon() if g.isMultipart() else [g.asPolygon()]
                for part in parts:
                    if part:
                        polys.append([np.array([[pt.x(), pt.y()] for pt in ring], float) for ring in part])
            feats.append(f)
            geoms.append(g)
            outlines.append((f.id(), polys))
        if not outlines:
            raise QgsProcessingException("The outline layer is empty.")
        return feats, geoms, outlines

    # --- step 3 helper ---

    @staticmethod
    def _stats_fields(source, T):
        """The columns of the results table: all the measurements, then the
        outline layer's own columns (a name already taken gets 'in_' in front).
        Also gives which of the outline layer's columns to copy."""
        fields = QgsFields()
        for name, typ in pmcore.COLUMNS:
            fields.append(QgsField(name, T[typ]))
        used = {name for name, _ in pmcore.COLUMNS}
        keep = []
        for i, fld in enumerate(source.fields()):
            if fld.name().lower() == "fid":
                continue                            # already given as pockmark_id
            new = fld.name()
            while new in used:
                new = "in_" + new
            used.add(new)
            copy = QgsField(fld)
            copy.setName(new)
            fields.append(copy)
            keep.append(i)
        return fields, keep


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _plain(value, typ):
    """A plain Python number or text for the attribute table (None if missing)."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if typ == "int":
        return int(value)
    if typ == "float":
        return float(value)
    return str(value)


def _depth_at(grid, x, y):
    """Water depth of the grid cell at map position (x, y)."""
    r, c = grid.to_rc(x, y)
    r, c = int(round(float(r))), int(round(float(c)))
    z, _, _ = grid.window(r, r + 1, c, c + 1)
    return float(-z[0, 0]) if z.size and np.isfinite(z[0, 0]) else None
