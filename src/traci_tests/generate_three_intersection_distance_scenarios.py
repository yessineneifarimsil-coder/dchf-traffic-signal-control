import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET


BASE_OUTPUT_DIR = Path("sumo_scenarios/three_intersections/distance_sensitivity")

SPEED = 13.89
LANES = 2

D12 = 300
D23_VALUES = [100, 200, 300, 500, 750, 1000]

EXTERNAL_MAIN_LENGTH = 300
SIDE_LENGTH = 200


def write_nodes(folder: Path, d23: int):
    nodes_file = folder / "corridor_3x2.nod.xml"

    x_j1 = 0
    x_j2 = D12
    x_j3 = D12 + d23

    content = f"""<nodes>
    <node id="W"  x="{-EXTERNAL_MAIN_LENGTH}" y="0" type="priority"/>
    <node id="J1" x="{x_j1}" y="0" type="traffic_light"/>
    <node id="J2" x="{x_j2}" y="0" type="traffic_light"/>
    <node id="J3" x="{x_j3}" y="0" type="traffic_light"/>
    <node id="E"  x="{x_j3 + EXTERNAL_MAIN_LENGTH}" y="0" type="priority"/>

    <node id="N1" x="{x_j1}" y="{SIDE_LENGTH}" type="priority"/>
    <node id="S1" x="{x_j1}" y="{-SIDE_LENGTH}" type="priority"/>

    <node id="N2" x="{x_j2}" y="{SIDE_LENGTH}" type="priority"/>
    <node id="S2" x="{x_j2}" y="{-SIDE_LENGTH}" type="priority"/>

    <node id="N3" x="{x_j3}" y="{SIDE_LENGTH}" type="priority"/>
    <node id="S3" x="{x_j3}" y="{-SIDE_LENGTH}" type="priority"/>
</nodes>
"""
    nodes_file.write_text(content, encoding="utf-8")
    return nodes_file


def write_edges(folder: Path):
    edges_file = folder / "corridor_3x2.edg.xml"

    content = f"""<edges>
    <edge id="E0" from="W" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E0" from="J1" to="W" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <edge id="E1" from="J1" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E1" from="J2" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <edge id="E2" from="J2" to="J3" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E2" from="J3" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <edge id="E3" from="E" to="J3" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E3" from="J3" to="E" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <edge id="E4" from="N1" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E4" from="J1" to="N1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="E5" from="S1" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E5" from="J1" to="S1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>

    <edge id="E6" from="N2" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E6" from="J2" to="N2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="E7" from="S2" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E7" from="J2" to="S2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>

    <edge id="E8" from="N3" to="J3" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E8" from="J3" to="N3" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="E9" from="S3" to="J3" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E9" from="J3" to="S3" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
</edges>
"""
    edges_file.write_text(content, encoding="utf-8")
    return edges_file


def write_routes(folder: Path):
    route_file = folder / "corridor_3x2_through.rou.xml"

    content = f"""<routes>
    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" maxSpeed="{SPEED}"/>

    <route id="W_to_E" edges="E0 E1 E2 -E3"/>
    <route id="E_to_W" edges="E3 -E2 -E1 -E0"/>

    <flow id="f_W_to_E" type="car" route="W_to_E" begin="0" end="3600" vehsPerHour="900"/>
    <flow id="f_E_to_W" type="car" route="E_to_W" begin="0" end="3600" vehsPerHour="700"/>

    <route id="N1_to_S1" edges="E4 -E5"/>
    <route id="S1_to_N1" edges="E5 -E4"/>
    <flow id="f_N1_to_S1" type="car" route="N1_to_S1" begin="0" end="3600" vehsPerHour="300"/>
    <flow id="f_S1_to_N1" type="car" route="S1_to_N1" begin="0" end="3600" vehsPerHour="300"/>

    <route id="N2_to_S2" edges="E6 -E7"/>
    <route id="S2_to_N2" edges="E7 -E6"/>
    <flow id="f_N2_to_S2" type="car" route="N2_to_S2" begin="0" end="3600" vehsPerHour="300"/>
    <flow id="f_S2_to_N2" type="car" route="S2_to_N2" begin="0" end="3600" vehsPerHour="300"/>

    <route id="N3_to_S3" edges="E8 -E9"/>
    <route id="S3_to_N3" edges="E9 -E8"/>
    <flow id="f_N3_to_S3" type="car" route="N3_to_S3" begin="0" end="3600" vehsPerHour="300"/>
    <flow id="f_S3_to_N3" type="car" route="S3_to_N3" begin="0" end="3600" vehsPerHour="300"/>
</routes>
"""
    route_file.write_text(content, encoding="utf-8")
    return route_file


def write_config(folder: Path):
    cfg_file = folder / "corridor_3x2_through.sumocfg"

    content = """<configuration>
    <input>
        <net-file value="corridor_3x2.net.xml"/>
        <route-files value="corridor_3x2_through.rou.xml"/>
    </input>

    <time>
        <begin value="0"/>
        <end value="3600"/>
        <step-length value="1"/>
    </time>

    <processing>
        <time-to-teleport value="-1"/>
    </processing>
</configuration>
"""
    cfg_file.write_text(content, encoding="utf-8")
    return cfg_file


def run_netconvert(folder: Path, nodes_file: Path, edges_file: Path):
    net_file = folder / "corridor_3x2.net.xml"

    cmd = [
        "netconvert",
        "--node-files", str(nodes_file),
        "--edge-files", str(edges_file),
        "--output-file", str(net_file),
        "--no-turnarounds", "true",
        "--tls.discard-simple", "false",
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    return net_file


def replace_tllogic_in_net(net_file: Path):
    tree = ET.parse(net_file)
    root = tree.getroot()

    for tl_logic in list(root.findall("tlLogic")):
        root.remove(tl_logic)

    custom_tls_elements = []

    for tl_id in ["J1", "J2", "J3"]:
        tl_logic = ET.Element(
            "tlLogic",
            {
                "id": tl_id,
                "type": "static",
                "programID": "0",
                "offset": "0",
            },
        )

        phases = [
            ("42", "GGGgrrrrGGGgrrrr"),
            ("3", "yyyyrrrryyyyrrrr"),
            ("42", "rrrrGGGgrrrrGGGg"),
            ("3", "rrrryyyyrrrryyyy"),
        ]

        for duration, state in phases:
            ET.SubElement(tl_logic, "phase", {"duration": duration, "state": state})

        custom_tls_elements.append(tl_logic)

    insert_index = len(root)
    for i, child in enumerate(list(root)):
        if child.tag in ["junction", "connection"]:
            insert_index = i
            break

    for tl_logic in reversed(custom_tls_elements):
        root.insert(insert_index, tl_logic)

    tree.write(net_file, encoding="utf-8", xml_declaration=True)


def generate_scenario(d23: int):
    folder = BASE_OUTPUT_DIR / f"d23_{d23}m"
    folder.mkdir(parents=True, exist_ok=True)

    nodes_file = write_nodes(folder, d23)
    edges_file = write_edges(folder)
    write_routes(folder)
    write_config(folder)

    net_file = run_netconvert(folder, nodes_file, edges_file)
    replace_tllogic_in_net(net_file)

    print("\n" + "=" * 70)
    print(f"Generated 3-intersection distance scenario: d12=300 m, d23={d23} m")
    print(f"Folder: {folder}")
    print("=" * 70)


def main():
    for d23 in D23_VALUES:
        generate_scenario(d23)

    print("\nAll three-intersection distance scenarios generated successfully.")


if __name__ == "__main__":
    main()