import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from backend.app.models import Base

OUTPUT = Path(__file__).resolve().parent / "class_diagram.png"
EXTRA_LINKS = [("tariffs", "vehicles", "by vehicle_type")]
CHAR_WIDTH = 0.072
LINE_HEIGHT = 0.2
PADDING = 0.16
COLUMN_GAP = 0.9
ROW_GAP = 1.1


def type_name(column):
    try:
        return column.type.python_type.__name__
    except NotImplementedError:
        return str(column.type).lower()


def collect_classes():
    classes = {}
    edges = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        foreign = {fk.parent.name for fk in table.foreign_keys}
        lines = []
        for column in table.columns:
            tags = [tag for tag, flag in (("PK", column.primary_key), ("FK", column.name in foreign)) if flag]
            suffix = " {" + ", ".join(tags) + "}" if tags else ""
            optional = "?" if column.nullable and not column.primary_key else ""
            lines.append("+ " + column.name + ": " + type_name(column) + optional + suffix)
        classes[table.name] = {"name": mapper.class_.__name__, "lines": lines}
        for fk in table.foreign_keys:
            edges.append((table.name, fk.column.table.name, fk.parent.nullable))
    return classes, edges


def assign_levels(classes, edges):
    levels = {name: 0 for name in classes}
    for _ in range(len(classes)):
        for child, parent, _nullable in edges:
            levels[child] = max(levels[child], levels[parent] + 1)
    for name in classes:
        children = [levels[child] for child, parent, _nullable in edges if parent == name]
        has_parent = any(child == name for child, _parent, _nullable in edges)
        if children and not has_parent and name not in {parent for child, parent, _n in edges if child == name}:
            levels[name] = min(children) - 1
    for source, target, _label in EXTRA_LINKS:
        if source in levels and target in levels and not any(source in edge[:2] for edge in edges):
            levels[source] = levels[target]
    return levels


def order_rows(levels, edges):
    rows = {}
    for name, level in sorted(levels.items()):
        rows.setdefault(level, []).append(name)
    position = {name: index for row in rows.values() for index, name in enumerate(row)}
    for level in sorted(rows):
        if level == min(rows):
            continue

        def barycenter(name):
            parents = [position[parent] for child, parent, _n in edges if child == name]
            return (0, sum(parents) / len(parents)) if parents else (1, 0)

        rows[level].sort(key=lambda name: (barycenter(name), name))
        for index, name in enumerate(rows[level]):
            position[name] = index
    return rows


def box_size(entry):
    width = max(len(line) for line in entry["lines"] + [entry["name"]]) * CHAR_WIDTH + PADDING * 2
    height = (len(entry["lines"]) + 2) * LINE_HEIGHT + PADDING
    return width, height


def layout(classes, rows):
    sizes = {name: box_size(entry) for name, entry in classes.items()}
    row_widths = {level: sum(sizes[n][0] for n in names) + COLUMN_GAP * (len(names) - 1) for level, names in rows.items()}
    canvas_width = max(row_widths.values())
    positions = {}
    y = 0.0
    for level in sorted(rows):
        names = rows[level]
        row_height = max(sizes[n][1] for n in names)
        x = (canvas_width - row_widths[level]) / 2
        for name in names:
            width, height = sizes[name]
            positions[name] = (x, y, width, height)
            x += width + COLUMN_GAP
        y += row_height + ROW_GAP
    return positions, canvas_width, y - ROW_GAP


def draw_box(ax, entry, x, y, width, height, top):
    draw_y = top - y - height
    ax.add_patch(Rectangle((x, draw_y), width, height, facecolor="#ffffff", edgecolor="#1f3864", linewidth=1.4, zorder=3))
    header = (len(entry["lines"]) + 2) * LINE_HEIGHT + PADDING - (len(entry["lines"]) * LINE_HEIGHT) - PADDING / 2
    ax.add_patch(Rectangle((x, draw_y + height - header), width, header, facecolor="#dfe7f7", edgecolor="#1f3864", linewidth=1.4, zorder=4))
    ax.text(x + width / 2, draw_y + height - header * 0.28, "\u00abentity\u00bb", ha="center", va="top", fontsize=7, color="#444444", zorder=5)
    ax.text(x + width / 2, draw_y + height - header * 0.62, entry["name"], ha="center", va="top", fontsize=10, fontweight="bold", zorder=5)
    for index, line in enumerate(entry["lines"]):
        ax.text(x + PADDING, draw_y + height - header - LINE_HEIGHT * (index + 0.75), line, ha="left", va="center", fontsize=7.6, family="monospace", zorder=5)


def anchors(positions, edges, top):
    sides = {}
    for index, (child, parent, _nullable) in enumerate(edges):
        cx, cy, cw, ch = positions[child]
        px, py, pw, ph = positions[parent]
        child_below = cy > py
        sides.setdefault((child, "top" if child_below else "bottom"), []).append((index, "child"))
        sides.setdefault((parent, "bottom" if child_below else "top"), []).append((index, "parent"))
    result = {}
    for (name, side), items in sides.items():
        x, y, width, height = positions[name]

        def partner_center(item):
            index, role = item
            child, parent, _nullable = edges[index]
            px, _py, pw, _ph = positions[parent if role == "child" else child]
            return px + pw / 2

        items.sort(key=partner_center)
        for slot, (index, role) in enumerate(items):
            fraction = (slot + 1) / (len(items) + 1)
            edge_y = top - y if side == "top" else top - y - height
            result[(index, role)] = (x + width * fraction, edge_y)
    return result


def build():
    classes, edges = collect_classes()
    levels = assign_levels(classes, edges)
    rows = order_rows(levels, edges)
    positions, canvas_width, canvas_height = layout(classes, rows)
    top = canvas_height
    margin = 0.7
    fig = plt.figure(figsize=(canvas_width + margin * 2, canvas_height + margin * 2 + 0.5))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-margin, canvas_width + margin)
    ax.set_ylim(-margin, canvas_height + margin + 0.5)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.text(canvas_width / 2, canvas_height + margin * 0.8, "UML Class Diagram: APMS domain model", ha="center", fontsize=13, fontweight="bold")
    points = anchors(positions, edges, top)
    for index, (child, parent, nullable) in enumerate(edges):
        start = points[(index, "child")]
        end = points[(index, "parent")]
        ax.plot([start[0], end[0]], [start[1], end[1]], color="#1f3864", linewidth=1.3, zorder=1)
        ax.text(start[0] + 0.12, start[1] + (0.14 if positions[child][1] > positions[parent][1] else -0.14), "0..*", fontsize=8, ha="left", va="center", zorder=6)
        ax.text(end[0] + 0.12, end[1] + (-0.14 if positions[child][1] > positions[parent][1] else 0.14), "0..1" if nullable else "1", fontsize=8, ha="left", va="center", zorder=6)
    for source, target, label in EXTRA_LINKS:
        if source in positions and target in positions:
            sx, sy, sw, sh = positions[source]
            tx, ty, tw, th = positions[target]
            start = (sx + sw, top - sy - sh / 2)
            end = (tx, top - ty - th / 2)
            ax.plot([start[0], end[0]], [start[1], end[1]], color="#777777", linewidth=1.1, linestyle="--", zorder=1)
            ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.12, label, fontsize=7, ha="center", color="#555555", zorder=6)
    for name, entry in classes.items():
        x, y, width, height = positions[name]
        draw_box(ax, entry, x, y, width, height, top)
    fig.savefig(OUTPUT, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("Saved", OUTPUT)


if __name__ == "__main__":
    build()
