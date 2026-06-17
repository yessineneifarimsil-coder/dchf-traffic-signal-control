import os
import subprocess
import xml.etree.ElementTree as ET


BASE_DIR = "sumo_scenarios/scalability"
N_INTERSECTIONS = 5
DISTANCE = 300
SIDE_LENGTH = 300

OUT_DIR = os.path.join(BASE_DIR, f"corridor_{N_INTERSECTIONS}x2_d{DISTANCE}m")

NODE_FILE = os.path.join(OUT_DIR, "corridor.nod.xml")
EDGE_FILE = os.path.join(OUT_DIR, "corridor.edg.xml")
NET_FILE = os.path.join(OUT_DIR, "corridor.net.xml")
ROUTE_FILE = os.path.join(OUT_DIR, "corridor.rou.xml")
SUMOCFG_FILE = os.path.join(OUT_DIR, "corridor.sumocfg")


def indent(elem, level=0):
    i = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "    "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def write_nodes():
    root = ET.Element("nodes")

    # West and east boundary nodes
    ET.SubElement(root, "node", {
        "id": "W",
        "x": str(-DISTANCE),
        "y": "0",
        "type": "priority",
    })

    ET.SubElement(root, "node", {
        "id": "E",
        "x": str((N_INTERSECTIONS - 1) * DISTANCE + DISTANCE),
        "y": "0",
        "type": "priority",
    })

    for i in range(1, N_INTERSECTIONS + 1):
        x = (i - 1) * DISTANCE

        ET.SubElement(root, "node", {
            "id": f"J{i}",
            "x": str(x),
            "y": "0",
            "type": "traffic_light",
        })

        ET.SubElement(root, "node", {
            "id": f"N{i}",
            "x": str(x),
            "y": str(SIDE_LENGTH),
            "type": "priority",
        })

        ET.SubElement(root, "node", {
            "id": f"S{i}",
            "x": str(x),
            "y": str(-SIDE_LENGTH),
            "type": "priority",
        })

    indent(root)
    ET.ElementTree(root).write(NODE_FILE, encoding="utf-8", xml_declaration=True)


def add_edge(root, edge_id, from_node, to_node, num_lanes=2, speed=13.89):
    ET.SubElement(root, "edge", {
        "id": edge_id,
        "from": from_node,
        "to": to_node,
        "numLanes": str(num_lanes),
        "speed": str(speed),
    })


def write_edges():
    root = ET.Element("edges")

    # Main corridor west to east
    add_edge(root, "E0", "W", "J1")
    for i in range(1, N_INTERSECTIONS):
        add_edge(root, f"E{i}", f"J{i}", f"J{i+1}")
    add_edge(root, f"E{N_INTERSECTIONS}", f"J{N_INTERSECTIONS}", "E")

    # Main corridor east to west
    add_edge(root, "-E0", "J1", "W")
    for i in range(1, N_INTERSECTIONS):
        add_edge(root, f"-E{i}", f"J{i+1}", f"J{i}")
    add_edge(root, f"-E{N_INTERSECTIONS}", "E", f"J{N_INTERSECTIONS}")

    # Side roads
    for i in range(1, N_INTERSECTIONS + 1):
        add_edge(root, f"N{i}_in", f"N{i}", f"J{i}")
        add_edge(root, f"N{i}_out", f"J{i}", f"N{i}")
        add_edge(root, f"S{i}_in", f"S{i}", f"J{i}")
        add_edge(root, f"S{i}_out", f"J{i}", f"S{i}")

    indent(root)
    ET.ElementTree(root).write(EDGE_FILE, encoding="utf-8", xml_declaration=True)


def write_routes():
    root = ET.Element("routes")

    ET.SubElement(root, "vType", {
        "id": "car",
        "accel": "2.6",
        "decel": "4.5",
        "sigma": "0.5",
        "length": "5.0",
        "maxSpeed": "13.89",
    })

    # Main through routes
    west_to_east_edges = " ".join([f"E{i}" for i in range(0, N_INTERSECTIONS + 1)])
    east_to_west_edges = " ".join([f"-E{i}" for i in range(N_INTERSECTIONS, -1, -1)])

    ET.SubElement(root, "route", {
        "id": "W_to_E",
        "edges": west_to_east_edges,
    })

    ET.SubElement(root, "route", {
        "id": "E_to_W",
        "edges": east_to_west_edges,
    })

    ET.SubElement(root, "flow", {
        "id": "f_W_to_E",
        "type": "car",
        "route": "W_to_E",
        "begin": "0",
        "end": "3600",
        "vehsPerHour": "900",
    })

    ET.SubElement(root, "flow", {
        "id": "f_E_to_W",
        "type": "car",
        "route": "E_to_W",
        "begin": "0",
        "end": "3600",
        "vehsPerHour": "700",
    })

    # Side-road straight crossing flows
    for i in range(1, N_INTERSECTIONS + 1):
        ET.SubElement(root, "route", {
            "id": f"N{i}_to_S{i}",
            "edges": f"N{i}_in S{i}_out",
        })

        ET.SubElement(root, "route", {
            "id": f"S{i}_to_N{i}",
            "edges": f"S{i}_in N{i}_out",
        })

        ET.SubElement(root, "flow", {
            "id": f"f_N{i}_to_S{i}",
            "type": "car",
            "route": f"N{i}_to_S{i}",
            "begin": "0",
            "end": "3600",
            "vehsPerHour": "300",
        })

        ET.SubElement(root, "flow", {
            "id": f"f_S{i}_to_N{i}",
            "type": "car",
            "route": f"S{i}_to_N{i}",
            "begin": "0",
            "end": "3600",
            "vehsPerHour": "300",
        })

    indent(root)
    ET.ElementTree(root).write(ROUTE_FILE, encoding="utf-8", xml_declaration=True)


def write_sumocfg():
    root = ET.Element("configuration")

    input_elem = ET.SubElement(root, "input")
    ET.SubElement(input_elem, "net-file", {"value": "corridor.net.xml"})
    ET.SubElement(input_elem, "route-files", {"value": "corridor.rou.xml"})

    time_elem = ET.SubElement(root, "time")
    ET.SubElement(time_elem, "begin", {"value": "0"})
    ET.SubElement(time_elem, "end", {"value": "3600"})
    ET.SubElement(time_elem, "step-length", {"value": "1"})

    report_elem = ET.SubElement(root, "report")
    ET.SubElement(report_elem, "no-step-log", {"value": "true"})

    indent(root)
    ET.ElementTree(root).write(SUMOCFG_FILE, encoding="utf-8", xml_declaration=True)


def run_netconvert():
    cmd = [
        "netconvert",
        "--node-files", NODE_FILE,
        "--edge-files", EDGE_FILE,
        "--output-file", NET_FILE,
        "--tls.guess",
        "--tls.default-type", "static",
        "--no-turnarounds", "true",
    ]

    print("Running netconvert:")
    print(" ".join(cmd))

    subprocess.run(cmd, check=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    write_nodes()
    write_edges()
    run_netconvert()
    write_routes()
    write_sumocfg()

    print("\nN-intersection corridor generated successfully.")
    print(f"N = {N_INTERSECTIONS}")
    print(f"Distance = {DISTANCE} m")
    print(f"Output folder: {OUT_DIR}")
    print(f"SUMO config: {SUMOCFG_FILE}")


if __name__ == "__main__":
    main()