"""Server-side SVG chart geometry (no JS charting library needed)."""

from __future__ import annotations

import math


def monotone_path(xs: list[float], ys: list[float]) -> str:
    """Smooth path through the points without overshooting (Fritsch–Carlson)."""
    n = len(xs)
    if n == 1:
        return f"M{xs[0]:.1f},{ys[0]:.1f}"
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    slopes = [(ys[i + 1] - ys[i]) / dx[i] for i in range(n - 1)]
    tangents = [slopes[0]] + [
        0.0 if slopes[i - 1] * slopes[i] <= 0 else (slopes[i - 1] + slopes[i]) / 2 for i in range(1, n - 1)
    ] + [slopes[-1]]
    for i, slope in enumerate(slopes):
        if slope == 0:
            tangents[i] = tangents[i + 1] = 0.0
            continue
        a, b = tangents[i] / slope, tangents[i + 1] / slope
        if (s := a * a + b * b) > 9:
            tau = 3 / math.sqrt(s)
            tangents[i], tangents[i + 1] = tau * a * slope, tau * b * slope
    path = [f"M{xs[0]:.1f},{ys[0]:.1f}"]
    for i in range(n - 1):
        h = dx[i] / 3
        path.append(
            f"C{xs[i] + h:.1f},{ys[i] + tangents[i] * h:.1f} "
            f"{xs[i + 1] - h:.1f},{ys[i + 1] - tangents[i + 1] * h:.1f} "
            f"{xs[i + 1]:.1f},{ys[i + 1]:.1f}"
        )
    return " ".join(path)


def _period_label(period: str, time_unit: str, with_year: bool = False) -> str:
    year, month, day = period[:10].split("-")
    if time_unit != "month":
        return f"{int(month)}.{int(day)}"
    return f"{year[2:]}년 {int(month)}월" if with_year else f"{int(month)}월"


def area_chart(points: list[dict], time_unit: str = "month", width: int = 680, height: int = 200) -> dict | None:
    if len(points) < 2:
        return None
    pad_x, pad_top, pad_bottom = 12, 30, 28
    values = [float(p["ratio"]) for p in points]
    top = max(values) or 1.0
    inner_w, inner_h = width - 2 * pad_x, height - pad_top - pad_bottom
    base = pad_top + inner_h
    xs = [pad_x + i * inner_w / (len(values) - 1) for i in range(len(values))]
    ys = [pad_top + inner_h * (1 - v / top) for v in values]
    line = monotone_path(xs, ys)
    peak = max(range(len(values)), key=values.__getitem__)
    step = max(1, math.ceil(len(points) / 7))
    labels = [
        {
            "x": round(xs[i], 1),
            # The year shows on the first label and wherever January starts a new one.
            "text": _period_label(points[i]["period"], time_unit, with_year=i == 0 or points[i]["period"][5:7] == "01"),
        }
        for i in range(0, len(points), step)
    ]
    return {
        "width": width,
        "height": height,
        "line": line,
        "area": f"{line} L{xs[-1]:.1f},{base:.1f} L{xs[0]:.1f},{base:.1f} Z",
        "grid": [round(pad_top + inner_h * f, 1) for f in (0, 0.5, 1)],
        "labels": labels,
        "label_y": height - 6,
        "peak": {
            "x": round(xs[peak], 1),
            "y": round(ys[peak], 1),
            "label_y": round(max(ys[peak] - 12, 12), 1),
            "text": _period_label(points[peak]["period"], time_unit),
            "anchor": "start" if peak < len(values) * 0.15 else "end" if peak > len(values) * 0.85 else "middle",
        },
        "last": {"x": round(xs[-1], 1), "y": round(ys[-1], 1)},
    }


def price_positions(price: dict) -> dict | None:
    """Percent positions of min/p25/median/p75/max on a 0–100 track."""
    if not price or price.get("max", 0) <= price.get("min", 0):
        return None
    low, high = price["min"], price["max"]
    span = high - low
    pos = {k: round((price[k] - low) / span * 100, 2) for k in ("p25", "median", "p75")}
    pos["iqr_width"] = round(pos["p75"] - pos["p25"], 2)
    return pos
