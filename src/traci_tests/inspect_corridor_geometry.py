import math
import xml.etree.ElementTree as ET
from pathlib import Path


NET_FILE = Path("sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.net.xml")
OUTPUT_TXT = Path("results/tables/corridor_geometry_summary.txt")


def parse_shape_length(shape):
    """
    Computes approximate polyline length from a SUMO shape string:
    'x1,y1 x2,y2 x3,y3 ...'
    """
    points = []

    for pair in shape.strip().split():
        x_str, y_str = pair.split(",")[:2]
        points.append((float(x_str), float(y_str)))

    length = 0.0

    for (x1, y1), (x2, y2) in zip(points[:-1], points[1:]):
        length += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    return length


def main():
    tree = ET.parse(NET_FILE)
    root = tree.getroot()

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)

    lines = []

    lines.append("=== Corridor Geometry Summary ===")
    lines.append(f"Network file: {NET_FILE}")
    lines.append("")

    edges = []

    for edge in root.findall("edge"):
        edge_id = edge.get("id")

        if edge_id is None:
            continue

        # Ignore internal junction edges
        if edge_id.startswith(":"):
            continue

        lanes = edge.findall("lane")

        if not lanes:
            continue

        lane_lengths = []
        lane_speeds = []
        lane_ids = []

        for lane in lanes:
            lane_ids.append(lane.get("id"))
            lane_lengths.append(float(lane.get("length", 0)))
            lane_speeds.append(float(lane.get("speed", 0)))

        avg_length = sum(lane_lengths) / len(lane_lengths)
        avg_speed = sum(lane_speeds) / len(lane_speeds)

        edges.append({
            "edge_id": edge_id,
            "num_lanes": len(lanes),
            "lane_ids": lane_ids,
            "avg_length": avg_length,
            "avg_speed": avg_speed,
            "free_flow_time": avg_length / avg_speed if avg_speed > 0 else None,
        })

    lines.append("Edges:")
    for e in edges:
        lines.append(
            f"- {e['edge_id']}: "
            f"lanes={e['num_lanes']}, "
            f"length={e['avg_length']:.2f} m, "
            f"speed={e['avg_speed']:.2f} m/s, "
            f"free_flow_time={e['free_flow_time']:.2f} s"
        )
        lines.append(f"  lane_ids={', '.join(e['lane_ids'])}")

    lines.append("")
    lines.append("Traffic lights and controlled lanes:")

    for tl_logic in root.findall("tlLogic"):
        tl_id = tl_logic.get("id")
        phases = tl_logic.findall("phase")

        lines.append("")
        lines.append(f"Traffic light: {tl_id}")
        lines.append(f"Number of phases: {len(phases)}")

        for i, phase in enumerate(phases):
            lines.append(
                f"  Phase {i}: duration={phase.get('duration')}, state={phase.get('state')}"
            )

    lines.append("")
    lines.append("Key corridor interpretation:")
    lines.append("- The main corridor link between J1 and J2 is expected to be edge E1 or -E1 depending on direction.")
    lines.append("- Check the edge list above for the exact J1-J2 link length and free-flow travel time.")
    lines.append("- Free-flow travel time = edge length / speed limit.")
    lines.append("- This value helps interpret why certain signal offsets perform better than others.")

    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nSaved geometry summary to: {OUTPUT_TXT}")


if __name__ == "__main__":
    main()