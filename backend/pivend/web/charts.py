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


# ---------------------------------------------------------------- dashboard charts

def nice_ticks(peak: float, count: int = 4) -> list[float]:
    """Clean y-axis ticks from 0 to just above the peak (0 / 50만 / 100만 ...)."""
    if peak <= 0:
        return [0, 1]
    raw = peak / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    ticks = [0.0]
    while ticks[-1] < peak:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks


def won_short(value: float) -> str:
    """Axis labels in Korean units: 1억, 350만, 9,500."""
    value = float(value)
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}".rstrip("0").rstrip(".") + "억"
    if value >= 10_000:
        return f"{value / 10_000:.0f}만" if value % 10_000 == 0 or value >= 1_000_000 else f"{value / 10_000:.1f}만"
    return f"{value:,.0f}"


def line_chart(days: list, series: list[dict], width: int = 760, height: int = 260) -> dict:
    """Line/area chart on ONE y-axis. series: [{"name", "values", "role": "primary"|"compare"}]."""
    pad_l, pad_r, pad_t, pad_b = 48, 16, 16, 30
    inner_w, inner_h = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(days)
    peak = max((max(s["values"]) for s in series if s["values"]), default=0)
    ticks = nice_ticks(peak)
    top = ticks[-1] or 1
    xs = [pad_l + (i * inner_w / (n - 1) if n > 1 else inner_w / 2) for i in range(n)]

    def y(v):
        return pad_t + inner_h * (1 - v / top)

    base = pad_t + inner_h
    out_series = []
    for s in series:
        ys = [y(v) for v in s["values"]]
        path = monotone_path(xs, ys)
        out_series.append({
            **s,
            "line": path,
            "area": f"{path} L{xs[-1]:.1f},{base:.1f} L{xs[0]:.1f},{base:.1f} Z" if s.get("role") == "primary" else "",
            "end": {"x": round(xs[-1], 1), "y": round(ys[-1], 1)},
        })
    step = max(1, math.ceil(n / 6))
    x_labels = [{"x": round(xs[i], 1), "text": f"{days[i].month}.{days[i].day}"} for i in range(0, n, step)]
    return {
        "width": width, "height": height, "series": out_series, "base": base,
        "left": pad_l, "right": width - pad_r,
        "y_ticks": [{"y": round(y(t), 1), "text": won_short(t)} for t in ticks],
        "x_labels": x_labels, "label_y": height - 8,
        "hover": {
            "x": [round(v, 1) for v in xs],
            "labels": [f"{d.month}월 {d.day}일" for d in days],
            "series": [{"name": s["name"], "role": s.get("role", "primary"), "values": s["values"]} for s in series],
        },
    }


def column_chart(items: list[dict], width: int = 360, height: int = 200) -> dict:
    """Columns from one baseline. items: [{"label", "value", "highlight"}]."""
    pad_l, pad_r, pad_t, pad_b = 8, 8, 24, 26
    inner_w, inner_h = width - pad_l - pad_r, height - pad_t - pad_b
    peak = max((i["value"] for i in items), default=0) or 1
    band = inner_w / max(len(items), 1)
    bar_w = min(24, band - 8)
    base = pad_t + inner_h
    cols = []
    for idx, item in enumerate(items):
        h = max(inner_h * item["value"] / peak, 2 if item["value"] else 0)
        x = pad_l + band * idx + (band - bar_w) / 2
        top = base - h
        r = min(4, h)
        # 4px rounded data-end, square at the baseline.
        d = (f"M{x:.1f},{base:.1f} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} "
             f"H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{top:.1f} {x + bar_w:.1f},{top + r:.1f} V{base:.1f} Z")
        cols.append({**item, "d": d, "cx": round(x + bar_w / 2, 1), "top": round(top, 1),
                     "hit_x": round(pad_l + band * idx, 1), "hit_w": round(band, 1)})
    return {"width": width, "height": height, "base": base, "cols": cols, "label_y": height - 8, "hit_y": pad_t, "hit_h": inner_h}


def sparkline(values: list[float], width: int = 120, height: int = 32) -> dict | None:
    if len(values) < 2 or not any(values):
        return None
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = 3
    xs = [pad + i * (width - 2 * pad) / (len(values) - 1) for i in range(len(values))]
    ys = [pad + (height - 2 * pad) * (1 - (v - lo) / span) for v in values]
    return {"width": width, "height": height, "d": monotone_path(xs, ys), "end": {"x": round(xs[-1], 1), "y": round(ys[-1], 1)}}
