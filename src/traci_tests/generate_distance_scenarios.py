import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET


BASE_DIR = Path("sumo_scenarios/two_intersections")
DISTANCES = [100, 200, 300, 500, 750, 1000]

SPEED = 13.89
LANES = 2

# External link lengths used to keep enough storage around the corridor
EXTERNAL_MAIN_LENGTH = 300
SIDE_LENGTH = 200


def write_nodes(folder: Path, distance: int):
    nodes_file = folder / "corridor.nod.xml"

    x_j1 = 0
    x_j2 = distance

    content = f"""<nodes>
    <node id="W"  x="{-EXTERNAL_MAIN_LENGTH}" y="0" type="priority"/>
    <node id="J1" x="{x_j1}" y="0" type="traffic_light"/>
    <node id="J2" x="{x_j2}" y="0" type="traffic_light"/>
    <node id="E"  x="{x_j2 + EXTERNAL_MAIN_LENGTH}" y="0" type="priority"/>

    <node id="N1" x="{x_j1}" y="{SIDE_LENGTH}" type="priority"/>
    <node id="S1" x="{x_j1}" y="{-SIDE_LENGTH}" type="priority"/>

    <node id="N2" x="{x_j2}" y="{SIDE_LENGTH}" type="priority"/>
    <node id="S2" x="{x_j2}" y="{-SIDE_LENGTH}" type="priority"/>
</nodes>
"""

    nodes_file.write_text(content, encoding="utf-8")
    return nodes_file


def write_edges(folder: Path):
    edges_file = folder / "corridor.edg.xml"

    content = f"""<edges>
    <!-- Main corridor: W <-> J1 <-> J2 <-> E -->
    <edge id="E0" from="W" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E0" from="J1" to="W" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <edge id="E1" from="J1" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E1" from="J2" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <!-- IMPORTANT:
         E2 is the incoming edge from East to J2.
         -E2 is the outgoing edge from J2 to East.
         This keeps the same convention as the previous corridor scenario.
    -->
    <edge id="E2" from="E" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="3"/>
    <edge id="-E2" from="J2" to="E" numLanes="{LANES}" speed="{SPEED}" priority="3"/>

    <!-- Side roads at J1 -->
    <edge id="E4" from="N1" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E4" from="J1" to="N1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>

    <edge id="E5" from="S1" to="J1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E5" from="J1" to="S1" numLanes="{LANES}" speed="{SPEED}" priority="2"/>

    <!-- Side roads at J2 -->
    <edge id="E6" from="N2" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E6" from="J2" to="N2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>

    <edge id="E7" from="S2" to="J2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
    <edge id="-E7" from="J2" to="S2" numLanes="{LANES}" speed="{SPEED}" priority="2"/>
</edges>
"""

    edges_file.write_text(content, encoding="utf-8")
    return edges_file


def write_routes_turning(folder: Path):
    route_file = folder / "corridor_turning.rou.xml"

    content = f"""<routes>
    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" maxSpeed="{SPEED}"/>

    <!-- ========================================================= -->
    <!-- Main corridor demand: West side entering from E0           -->
    <!-- Total demand: 900 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="W_to_E_straight" edges="E0 E1 -E2"/>
    <route id="W_to_J1_right" edges="E0 -E5"/>
    <route id="W_to_J1_left" edges="E0 -E4"/>

    <flow id="f_W_E_straight" type="car" route="W_to_E_straight" begin="0" end="3600" vehsPerHour="630"/>
    <flow id="f_W_J1_right" type="car" route="W_to_J1_right" begin="0" end="3600" vehsPerHour="135"/>
    <flow id="f_W_J1_left" type="car" route="W_to_J1_left" begin="0" end="3600" vehsPerHour="135"/>

    <!-- ========================================================= -->
    <!-- Main corridor demand: East side entering from E2           -->
    <!-- Total demand: 700 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="E_to_W_straight" edges="E2 -E1 -E0"/>
    <route id="E_to_J2_right" edges="E2 -E7"/>
    <route id="E_to_J2_left" edges="E2 -E6"/>

    <flow id="f_E_W_straight" type="car" route="E_to_W_straight" begin="0" end="3600" vehsPerHour="490"/>
    <flow id="f_E_J2_right" type="car" route="E_to_J2_right" begin="0" end="3600" vehsPerHour="105"/>
    <flow id="f_E_J2_left" type="car" route="E_to_J2_left" begin="0" end="3600" vehsPerHour="105"/>

    <!-- ========================================================= -->
    <!-- Side road demand at J1: entering from E4                   -->
    <!-- Total demand: 300 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="N1_to_S1_straight" edges="E4 -E5"/>
    <route id="N1_to_W_right" edges="E4 -E0"/>
    <route id="N1_to_E_left" edges="E4 E1 -E2"/>

    <flow id="f_N1_S1_straight" type="car" route="N1_to_S1_straight" begin="0" end="3600" vehsPerHour="210"/>
    <flow id="f_N1_W_right" type="car" route="N1_to_W_right" begin="0" end="3600" vehsPerHour="45"/>
    <flow id="f_N1_E_left" type="car" route="N1_to_E_left" begin="0" end="3600" vehsPerHour="45"/>

    <!-- ========================================================= -->
    <!-- Side road demand at J1: entering from E5                   -->
    <!-- Total demand: 300 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="S1_to_N1_straight" edges="E5 -E4"/>
    <route id="S1_to_E_right" edges="E5 E1 -E2"/>
    <route id="S1_to_W_left" edges="E5 -E0"/>

    <flow id="f_S1_N1_straight" type="car" route="S1_to_N1_straight" begin="0" end="3600" vehsPerHour="210"/>
    <flow id="f_S1_E_right" type="car" route="S1_to_E_right" begin="0" end="3600" vehsPerHour="45"/>
    <flow id="f_S1_W_left" type="car" route="S1_to_W_left" begin="0" end="3600" vehsPerHour="45"/>

    <!-- ========================================================= -->
    <!-- Side road demand at J2: entering from E6                   -->
    <!-- Total demand: 300 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="N2_to_S2_straight" edges="E6 -E7"/>
    <route id="N2_to_E_right" edges="E6 -E2"/>
    <route id="N2_to_W_left" edges="E6 -E1 -E0"/>

    <flow id="f_N2_S2_straight" type="car" route="N2_to_S2_straight" begin="0" end="3600" vehsPerHour="210"/>
    <flow id="f_N2_E_right" type="car" route="N2_to_E_right" begin="0" end="3600" vehsPerHour="45"/>
    <flow id="f_N2_W_left" type="car" route="N2_to_W_left" begin="0" end="3600" vehsPerHour="45"/>

    <!-- ========================================================= -->
    <!-- Side road demand at J2: entering from E7                   -->
    <!-- Total demand: 300 veh/h                                    -->
    <!-- 70% straight, 15% right, 15% left                          -->
    <!-- ========================================================= -->
    <route id="S2_to_N2_straight" edges="E7 -E6"/>
    <route id="S2_to_W_right" edges="E7 -E1 -E0"/>
    <route id="S2_to_E_left" edges="E7 -E2"/>

    <flow id="f_S2_N2_straight" type="car" route="S2_to_N2_straight" begin="0" end="3600" vehsPerHour="210"/>
    <flow id="f_S2_W_right" type="car" route="S2_to_W_right" begin="0" end="3600" vehsPerHour="45"/>
    <flow id="f_S2_E_left" type="car" route="S2_to_E_left" begin="0" end="3600" vehsPerHour="45"/>
</routes>
"""

    route_file.write_text(content, encoding="utf-8")
    return route_file


def write_tllogic(folder: Path):
    add_file = folder / "corridor_tls.add.xml"

    # Same 4-phase logic used in the current two-intersection corridor.
    # r = red, y = yellow, G/g = green.
    content = """<additional>
    <tlLogic id="J1" type="static" programID="0" offset="0">
        <phase duration="42" state="GGGgrrrrGGGgrrrr"/>
        <phase duration="3"  state="yyyyrrrryyyyrrrr"/>
        <phase duration="42" state="rrrrGGGgrrrrGGGg"/>
        <phase duration="3"  state="rrrryyyyrrrryyyy"/>
    </tlLogic>

    <tlLogic id="J2" type="static" programID="0" offset="0">
        <phase duration="42" state="GGGgrrrrGGGgrrrr"/>
        <phase duration="3"  state="yyyyrrrryyyyrrrr"/>
        <phase duration="42" state="rrrrGGGgrrrrGGGg"/>
        <phase duration="3"  state="rrrryyyyrrrryyyy"/>
    </tlLogic>
</additional>
"""

    add_file.write_text(content, encoding="utf-8")
    return add_file


def write_config(folder: Path):
    cfg_file = folder / "corridor_turning.sumocfg"

    content = """<configuration>
    <input>
        <net-file value="corridor.net.xml"/>
        <route-files value="corridor_turning.rou.xml"/>
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
    net_file = folder / "corridor.net.xml"

    cmd = [
        "netconvert",
        "--node-files", str(nodes_file),
        "--edge-files", str(edges_file),
        "--output-file", str(net_file),
        "--no-turnarounds",
        "true",
        "--tls.discard-simple",
        "false",
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    return net_file


def replace_tllogic_in_net(net_file: Path):
    """
    Replace automatically generated traffic-light programs inside the SUMO net.xml
    with our fixed 4-phase program.

    Important:
    The tlLogic elements must be inserted BEFORE the <connection> elements,
    because SUMO reads connections that reference tls='J1' and tls='J2'.
    If tlLogic is appended at the end of the file, SUMO may say:
    'The tls J1 is not known.'
    """
    tree = ET.parse(net_file)
    root = tree.getroot()

    removed = 0
    for tl_logic in list(root.findall("tlLogic")):
        root.remove(tl_logic)
        removed += 1

    custom_tls_elements = []

    for tl_id in ["J1", "J2"]:
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
            ET.SubElement(
                tl_logic,
                "phase",
                {
                    "duration": duration,
                    "state": state,
                },
            )

        custom_tls_elements.append(tl_logic)

    # Find the first <junction> or <connection>.
    # We insert tlLogic before that point so SUMO knows J1/J2 before reading connections.
    insert_index = len(root)

    for i, child in enumerate(list(root)):
        if child.tag in ["junction", "connection"]:
            insert_index = i
            break

    for tl_logic in reversed(custom_tls_elements):
        root.insert(insert_index, tl_logic)

    tree.write(net_file, encoding="utf-8", xml_declaration=True)

    print(
        f"Replaced {removed} existing tlLogic element(s) "
        f"and inserted custom J1/J2 programs before connections in {net_file}"
    )

def generate_scenario(distance: int):
    folder = BASE_DIR / f"distance_{distance}m"
    folder.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print(f"Generating distance scenario: {distance} m")
    print("=" * 70)

    nodes_file = write_nodes(folder, distance)
    edges_file = write_edges(folder)
    route_file = write_routes_turning(folder)
    add_file = write_tllogic(folder)
    cfg_file = write_config(folder)

    net_file = run_netconvert(folder, nodes_file, edges_file)
    replace_tllogic_in_net(net_file)

    print(f"Created folder: {folder}")
    print(f"Nodes: {nodes_file}")
    print(f"Edges: {edges_file}")
    print(f"Network: {net_file}")
    print(f"Routes: {route_file}")
    print(f"TLS: {add_file}")
    print(f"Config: {cfg_file}")


def main():
    for distance in DISTANCES:
        generate_scenario(distance)

    print("\nAll distance scenarios generated successfully.")
    print("Next step: test one scenario with SUMO before running experiments.")


if __name__ == "__main__":
    main()