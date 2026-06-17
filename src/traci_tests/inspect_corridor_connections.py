import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict


NET_FILE = Path("sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.net.xml")
OUTPUT_TXT = Path("results/tables/corridor_connections_summary.txt")


def main():
    tree = ET.parse(NET_FILE)
    root = tree.getroot()

    connections = defaultdict(list)

    for conn in root.findall("connection"):
        from_edge = conn.get("from")
        to_edge = conn.get("to")
        from_lane = conn.get("fromLane")
        to_lane = conn.get("toLane")
        tl = conn.get("tl")
        link_index = conn.get("linkIndex")
        direction = conn.get("dir")

        if from_edge is None or to_edge is None:
            continue

        if from_edge.startswith(":") or to_edge.startswith(":"):
            continue

        connections[from_edge].append({
            "to_edge": to_edge,
            "from_lane": from_lane,
            "to_lane": to_lane,
            "tl": tl,
            "link_index": link_index,
            "direction": direction,
        })

    lines = []
    lines.append("=== Corridor Connection Summary ===")
    lines.append(f"Network file: {NET_FILE}")
    lines.append("")
    lines.append("Valid outgoing movements from each incoming edge:")
    lines.append("")

    for from_edge in sorted(connections.keys()):
        lines.append(f"From edge {from_edge}:")

        unique_to_edges = sorted(set(c["to_edge"] for c in connections[from_edge]))

        for to_edge in unique_to_edges:
            lane_connections = [
                c for c in connections[from_edge]
                if c["to_edge"] == to_edge
            ]

            details = []
            for c in lane_connections:
                details.append(
                    f"lane {c['from_lane']} -> lane {c['to_lane']}, "
                    f"tl={c['tl']}, linkIndex={c['link_index']}, dir={c['direction']}"
                )

            lines.append(f"  -> {to_edge}")
            for d in details:
                lines.append(f"     {d}")

        lines.append("")

    lines.append("Interpretation guide:")
    lines.append("- If an edge appears under 'From edge X -> Y', then route X Y is allowed.")
    lines.append("- Through movements and turning movements must use only valid edge sequences.")
    lines.append("- We will use this file to build Scenario B route definitions safely.")

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nSaved connection summary to: {OUTPUT_TXT}")


if __name__ == "__main__":
    main()