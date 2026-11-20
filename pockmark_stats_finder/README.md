# Pockmark Stats Finder: guide

Pick your bathymetry grid and your layer of pockmark outlines, then click **Run**.
The plugin adds three layers to the map:

| Layer | What it holds |
|---|---|
| **Pockmark stats** | your outlines, with all the measurements in the attribute table |
| **Pockmark centers** | the center of each outline, with the water depth there |
| **Pockmark bottoms** | the deepest point near each center, with its depth and how far it is below the rim |

Your own outline layer is never changed. Nothing extra needs to be installed.

## Install (once)

1. In QGIS, go to **Plugins > Manage and Install Plugins > Install from ZIP**.
2. Pick `pockmark_stats_finder.zip` (no need to unzip it) and click **Install Plugin**.
3. A pit-shaped button appears on the toolbar. The tool is also under
   **Plugins > Pockmark Stats Finder** and in the **Processing Toolbox**.

To update, install the new zip the same way.

## Use

1. Load your bathymetry grid (`.asc` or `.tif`) and your outline layer in QGIS. The
   grid must be in meters, in a map projection such as UTM. The outlines can be in any
   projection; they are converted to match the grid.
2. Save your edits to the outline layer (**Save Layer Edits**).
3. Click the toolbar button.
4. Under **Bathymetry grid**, pick the depth grid itself, not a hillshade made from it.
   (The tool stops with a message if the grid looks like a picture.)
   Under **Pockmark outlines**, pick your outline layer. Tick **Selected features only**
   to measure just the outlines you have selected.
5. Leave **Grid values are** on *Automatic*, unless the message in the log gets it
   wrong (it says whether it read the values as depths or as heights).
6. Click **Run**. About 1,000 outlines take a few seconds. The log says how many
   outlines are flagged for checking.

The new layers are temporary (a small chip icon next to their names). To keep one,
right-click it and choose **Make Permanent**. Or, before clicking Run, click the
**...** next to each result and choose **Save to File**.

Run the tool again whenever you add or change outlines. It makes fresh layers each time.

**Tip:** to find the outlines worth checking, open the attribute table of
*Pockmark stats* and sort by `flags`.

## How depth is measured

1. **Find the tilt of the seafloor.** A tilted flat surface is fitted to a strip of
   seafloor just outside the outline. The strip is 0.6 of the pit's radius wide (at
   least 4 grid cells). Other pockmarks are left out of the strip, and the 30% of
   cells that fit worst are ignored, so bumps and nearby pits don't throw it off. A
   larger pit that surrounds this one is kept in.
2. **Take the tilt away**, so a pit on a slope is measured as if it were on flat ground.
3. **Bottom:** the deepest grid cell within half the pit's radius of the outline's
   center. The deepest cell anywhere in the outline is given too.
4. **Rim level:** the middle value of the depths read along your outline, every half
   grid cell.
5. **Depth and volume** are measured from the rim level down. Volume is the space
   between the rim level and the seafloor inside the outline.

Depth and volume can come out a little low for pits only a few grid cells across,
because the cells miss the very lowest point. On test pits with a 6 m radius on a
1 m grid, they were 7 to 13% low. Use the finest grid you have.

## Columns

Depths are water depths in meters, given as positive numbers. Directions are in
degrees clockwise from north. Positions are in the grid's map projection.

| Column | What it is |
|---|---|
| `pockmark_id` | the outline's number in your layer |
| `flags` | anything worth checking, separated by `;` (see the next table); blank if none |
| `center_x`, `center_y` | center of the outline (the middle of its area) |
| `bottom_x`, `bottom_y` | deepest point near the center (step 3 above) |
| `bottom_offset_m` | distance from the center to the bottom |
| `bottom_offset_azimuth_deg` | direction from the center to the bottom |
| `bottom_is_deepest` | 1 if the bottom is also the deepest point in the whole outline, otherwise 0 |
| `area_m2` | area inside the outline |
| `perimeter_m` | length of the outline |
| `equiv_diameter_m` | diameter of a circle with the same area |
| `rim_depth_m` | middle water depth along the outline |
| `rim_depth_min_m`, `rim_depth_max_m` | shallowest and deepest water depth along the outline |
| `bottom_depth_m` | water depth at the bottom |
| `deepest_depth_m` | water depth at the deepest point in the outline (with the seafloor tilt taken away) |
| `depth_below_rim_m` | how far the bottom is below the rim level |
| `max_depth_below_rim_m` | how far the deepest point in the outline is below the rim level |
| `mean_depth_below_rim_m` | average depth below the rim level (volume divided by area) |
| `rim_spread_m` | how uneven the rim is: the range of the middle 80% of rim depths |
| `volume_m3` | volume below the rim level |
| `depth_to_diameter` | `max_depth_below_rim_m` divided by `equiv_diameter_m` |
| `volume_ratio` | how full the pit's shape is: about 0.33 for a cone, 0.5 for a bowl, close to 1 for a flat floor with steep walls |
| `ellipse_major_m`, `ellipse_minor_m` | long and short axes of the ellipse that best matches the outline |
| `elongation` | long axis divided by short axis (1 means round) |
| `long_axis_azimuth_deg` | direction of the long axis, 0 to 180. Left blank for outlines that are nearly round |
| `box_length_m`, `box_width_m` | sides of the smallest rectangle that fits around the outline |
| `circularity` | how close to a circle: 1 for a circle, lower for a more ragged edge |
| `solidity` | area divided by the area with the dents filled in (lower means more dented) |
| `convexity` | length of the outline with the dents filled in, divided by its real length |
| `mean_slope_inside_deg` | average slope of the seafloor inside the outline |
| `steep_slope_inside_deg` | slope of the steepest walls (95% of the inside is gentler than this) |
| `seafloor_slope_deg` | slope of the seafloor around the pit |
| `seafloor_downslope_azimuth_deg` | which way is downhill around the pit |
| `long_axis_vs_downslope_deg` | angle between the long axis and downhill: 0 means the pit is stretched downhill, 90 means across the slope |
| `nearest_id`, `nearest_distance_m` | the nearest other pockmark, and the distance between the two centers |
| `inside_of` | the number of the smallest larger outline that this one sits inside (for pits within pits) |
| `n_inside` | how many outlines sit inside this one |
| `n_cells` | number of grid cells inside the outline |
| `nodata_fraction` | share of those cells that have no data |
| `deepest_x`, `deepest_y` | position of the deepest point in the outline |

After these come the columns from your own outline layer. If a name is already used
above, `in_` is put in front of it (for example `in_area_m2`).

## Flags

| Flag | Meaning |
|---|---|
| `few_cells` | fewer than 9 grid cells inside, so the numbers are rough |
| `very_steep` | walls steeper than 45 degrees on average: check that the grid is depths, not a hillshade |
| `shallow` | less than 5 cm below the rim: maybe not a pit |
| `not_a_dip` | the inside is not lower than the rim |
| `nodata_inside` | more than 5% of the inside has no data, so the numbers are partial |
| `near_grid_edge` | the outline, or the strip around it, reaches the edge of the grid |
| `center_outside_outline` | the center falls outside the outline (for example a crescent shape) |
| `crosses_itself` | the outline crosses over itself: fix it with the Vertex Tool (no numbers until then) |
| `multipart` | one outline holds several shapes: only the largest was measured |
| `hole_ignored` | the outline has a hole in it: only the outer edge was used |
| `no_plane` | not enough seafloor around the outline to find the tilt |
| `no_cells` | no grid cell center falls inside the outline (smaller than one cell) |
| `outside_grid`, `no_data` | the outline is not on the grid |

## Settings

Under **Advanced Parameters** in the tool's box:

| Setting | Normally | What it does |
|---|---|---|
| Bottom search zone | 0.5 | look for the bottom within this share of the pit's radius from its center |
| Seafloor strip width | 0.6 | width of the seafloor strip used to find the tilt, as a share of the pit's radius |

Everyone working on one project should use the same settings, so the numbers can be
compared.

## A note on small pits

For pits only a few grid cells across, one or two cells more or less inside the outline
can change depth and volume by 10% or more. Treat the numbers for `few_cells` outlines
as rough, and use the finest grid you have.
