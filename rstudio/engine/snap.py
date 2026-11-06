"""Magnetic edges for dragging layers (page edges, centre, margins, other layers) - pure geometry, no Qt."""

def snap_move(rect, xs, ys, thresh):
    """rect=(x0, y0, x1, y1) of the moving layer. xs / ys: positions to snap to. Returns (dx, dy, guide_xs, guide_ys): shift to apply and the guide lines to draw."""
    x0, y0, x1, y1 = rect; ax = (x0, (x0 + x1) / 2.0, x1); ay = (y0, (y0 + y1) / 2.0, y1)
    def best(anchors, targets):
        d_best, t_best = None, None
        for a in anchors:
            for t in targets:
                d = t - a
                if abs(d) <= thresh and (d_best is None or abs(d) < abs(d_best) - 1e-9): d_best, t_best = d, t
        return d_best, t_best
    dx, tx = best(ax, xs); dy, ty = best(ay, ys)
    return (dx or 0.0), (dy or 0.0), ([tx] if tx is not None else []), ([ty] if ty is not None else [])

def targets_for(page_w, page_h, margin_px, others):
    """Snap lines: page edges, centre, margins and every other visible layer's edges / centre. others: [(x0, y0, x1, y1)]."""
    xs = [0, page_w / 2.0, page_w]; ys = [0, page_h / 2.0, page_h]
    if margin_px: xs += [margin_px, page_w - margin_px]; ys += [margin_px, page_h - margin_px]
    for (a, b, c, d) in others: xs += [a, (a + c) / 2.0, c]; ys += [b, (b + d) / 2.0, d]
    return xs, ys
