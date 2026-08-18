"""
paper_style.py — companion helpers for paper.mplstyle.

The mplstyle file handles all the rcParams-level styling (fonts, colors,
grid, ticks, spines, legend, color cycle). This module adds the things
mplstyle CAN'T express:

  * draw_rounded_panel — the rounded cream panel that sits BEHIND the axes
  * round_bar_corners  — replaces matplotlib's rectangle bars with
                         FancyBboxPatch versions whose corners stay
                         visually circular under skewed data aspect ratios
  * fmt_value          — clean numeric label formatter (hides zeros,
                         integers when whole, one decimal otherwise)

Color constants are exposed for direct use when you need them outside
matplotlib (e.g. an INK-colored fig.text() title, or a tinted
fill_between for confidence bands).

Usage:
    import matplotlib.pyplot as plt
    plt.style.use("paper.mplstyle")
    from paper_style import (
        OUTER_BG, INNER_BG, INK, MUTED,
        SET2_TEAL_DARK, SET2_ORANGE_DARK,
        draw_rounded_panel, round_bar_corners, fmt_value,
    )

    fig = plt.figure(figsize=(11, 5.8))
    ax = fig.add_axes([0.075, 0.16, 0.88, 0.62])
    ax.bar(...)
    draw_rounded_panel(ax, fig)
    round_bar_corners(ax, fig)
"""

from matplotlib.patches import FancyBboxPatch, Rectangle

# -----------------------------------------------------------------------------
# Color tokens — kept in sync with paper.mplstyle
# -----------------------------------------------------------------------------
OUTER_BG = "#F1EEE7"   # figure background ("page")
INNER_BG = "#FAF9F5"   # rounded panel behind each axes
INK      = "#2C2A24"   # primary text — warm dark gray, not pure black
MUTED    = "#7A746A"   # ticks, gridlines, secondary text
SOFT_BORDER = "#D6CFC2"  # subtle border for nested elements (chat bubbles, etc.)

# ColorBrewer Set2 — paper's categorical palette
SET2_TEAL_DARK    = "#66C2A5"
SET2_TEAL_LIGHT   = "#B3E0D2"
SET2_ORANGE_DARK  = "#FC8D62"
SET2_ORANGE_LIGHT = "#FCC8A8"
SET2_PURPLE_BLUE  = "#8DA0CB"
SET2_PINK         = "#E78AC3"
SET2_GREEN        = "#A6D854"
SET2_GOLD         = "#FFD92F"

# Sign-encoding pair used in the cosine-similarity chart
NEG_COLOR = SET2_ORANGE_DARK   # negative direction
POS_COLOR = SET2_TEAL_DARK     # positive direction


# -----------------------------------------------------------------------------
# Rounded panel behind the axes
# -----------------------------------------------------------------------------
def draw_rounded_panel(ax, fig,
                       left_pad=0.020, right_pad=0.005,
                       top_pad=0.025,  bottom_pad=0.045):
    """Draw a rounded INNER_BG panel BEHIND the given axes.

    The default asymmetric padding is chosen so the panel encompasses the
    tick labels (left, bottom) but NOT the y-axis label — the y-label is
    intentionally left in the outer cream area, which reads cleaner.

    Bump top_pad up to ~0.10 if you want a panel-internal subtitle drawn
    via fig.text() to fit inside the panel.
    Bump bottom_pad up to ~0.090 if your x-tick labels wrap to two lines.
    """
    ax.patch.set_visible(False)
    bbox = ax.get_position()
    panel = FancyBboxPatch(
        (bbox.x0 - left_pad, bbox.y0 - bottom_pad),
        bbox.width + left_pad + right_pad,
        bbox.height + top_pad + bottom_pad,
        boxstyle="round,pad=0.002,rounding_size=0.018",
        transform=fig.transFigure,
        facecolor=INNER_BG,
        edgecolor="none",
        zorder=-1,
        figure=fig,
    )
    # Insert before existing patches so it sits underneath everything
    fig.patches.insert(0, panel)
    return panel


# -----------------------------------------------------------------------------
# Rounded bar corners
# -----------------------------------------------------------------------------
def round_bar_corners(ax, fig, rounding_px=3.5, min_height=None):
    """Replace ax.bar() Rectangles with rounded-corner FancyBboxPatches.

    Computes the right mutation_aspect so corners stay visually circular
    in display space under skewed data aspect ratios (which most bar
    charts have, because their y-range is much larger than their x-range
    in data units).

    Preserves the bar's facecolor + hatch + edgecolor, so the cosine
    chart's diagonal-hatched bars survive the rounding.

    Args:
        ax: the axes containing the bars
        fig: the parent figure (needed for the canvas draw to measure pixels)
        rounding_px: corner radius in display pixels (default 3.5)
        min_height: if set, bars shorter than this in data units are
            skipped (i.e. left as flat rectangles); useful for "zero"
            placeholder bars that look strange when rounded
    """
    fig.canvas.draw()
    ax_pix = ax.get_window_extent()
    x_range = ax.get_xlim()[1] - ax.get_xlim()[0]
    y_range = ax.get_ylim()[1] - ax.get_ylim()[0]
    x_per_px = x_range / ax_pix.width
    y_per_px = y_range / ax_pix.height
    rx_data = rounding_px * x_per_px
    mut_aspect = (y_per_px / x_per_px)

    to_remove, new_patches = [], []
    for p in list(ax.patches):
        if type(p) is not Rectangle:
            continue
        h = p.get_height()
        if h < (min_height if min_height is not None else 0.0001):
            continue
        x, y = p.get_x(), p.get_y()
        w = p.get_width()
        color = p.get_facecolor()
        hatch = p.get_hatch()
        ec = p.get_edgecolor() if hatch else 'none'
        to_remove.append(p)
        new_patches.append(FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={rx_data}",
            facecolor=color,
            edgecolor=ec,
            linewidth=0,
            hatch=hatch,
            mutation_aspect=mut_aspect,
            zorder=2,
        ))
    for p in to_remove:
        p.remove()
    for p in new_patches:
        ax.add_patch(p)


# -----------------------------------------------------------------------------
# Numeric label formatter
# -----------------------------------------------------------------------------
def fmt_value(v):
    """Clean numeric label: hide zeros, show ints when whole, else 1 decimal.

    Examples:
        fmt_value(0)    -> ""       (zero is hidden — placeholder bars
                                     shouldn't get a "0.0" label)
        fmt_value(53.0) -> "53"
        fmt_value(52.3) -> "52.3"
    """
    if v == 0:
        return ""
    if abs(v - round(v)) < 0.05:
        return f"{int(round(v))}"
    return f"{v:.1f}"


# -----------------------------------------------------------------------------
# Convenience: nicer legend defaults beyond what mplstyle handles
# -----------------------------------------------------------------------------
def add_legend(ax, **kwargs):
    """Add a legend with the paper's defaults (cream face, muted border).

    Any kwargs override the defaults. Returns the Legend instance.
    """
    defaults = dict(
        loc="upper right",
        frameon=True,
        fontsize=10,
        labelcolor=INK,
        handlelength=1.4,
        handleheight=1.0,
        borderpad=0.7,
    )
    defaults.update(kwargs)
    leg = ax.legend(**defaults)
    leg.get_frame().set_facecolor(OUTER_BG)
    leg.get_frame().set_edgecolor(MUTED)
    leg.get_frame().set_linewidth(0.6)
    leg.get_frame().set_alpha(0.9)
    return leg
