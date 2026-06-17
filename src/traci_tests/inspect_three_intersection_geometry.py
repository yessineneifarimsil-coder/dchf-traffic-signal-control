import xml.etree.ElementTree as ET
from pathlib import Path


NET_FILE = Path("sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2.net.xml")
OUTPUT_FILE = Path("results/tables/three_intersection_geometry_summary.txt")


def main():
    tree = ET.parse(NET_FILE)
    root = tree.getroot()

    lines = []
    lines.append("=== Three-Intersection Corridor Geometry Summary ===")
    lines.append(f"Network file: {NET_FILE}")
    lines.append("")

    lines.append("Edges:")
    for edge in root.findall("edge"):
        edge_id = edge.get("id")

        if edge_id is None or edge_id.startswith(":"):
            continue

        lanes = edge.findall("lane")
        if not lanes:
            continue

        first_lane = lanes[0]
        length = float(first_lane.get("length"))
        speed = float(first_lane.get("speed"))
        free_flow_time = length / speed if speed > 0 else 0.0

        lane_ids = [lane.get("id") for lane in lanes]

        lines.append(
            f"- {edge_id}: lanes={len(lanes)}, "
            f"length={length:.2f} m, speed={speed:.2f} m/s, "
            f"free_flow_time={free_flow_time:.2f} s"
        )
        lines.append(f"  lane_ids={', '.join(lane_ids)}")

    lines.append("")
    lines.append("Traffic lights:")

    for tl in root.findall("tlLogic"):
        tl_id = tl.get("id")
        phases = tl.findall("phase")

        lines.append("")
        lines.append(f"Traffic light: {tl_id}")
        lines.append(f"Number of phases: {len(phases)}")

        for i, phase in enumerate(phases):
            duration = phase.get("duration")
            state = phase.get("state")
            lines.append(f"  Phase {i}: duration={duration}, state={state}")

    lines.append("")
    lines.append("Key corridor interpretation:")
    lines.append("- Main corridor links are expected to be E1 between J1--J2 and E2 between J2--J3.")
    lines.append("- Reverse-direction links are expected to be -E1 and -E2.")
    lines.append("- The initial 3-intersection corridor uses d12 = 300 m and d23 = 300 m.")
    lines.append("- This distance is used as a reference configuration because 300 m belonged to the effective coordination zone identified in the two-intersection analysis.")
    lines.append("- It is not assumed to be universally optimal for three intersections; this must be tested later by varying d23.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nSaved geometry summary to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()