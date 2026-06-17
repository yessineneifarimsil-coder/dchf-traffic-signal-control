import shutil
from pathlib import Path


BASE_NETWORK_FOLDER = Path("sumo_scenarios/two_intersections/distance_300m")
OUTPUT_BASE = Path("sumo_scenarios/two_intersections/demand_sensitivity")

SPEED = 13.89

DEMAND_SCENARIOS = {
    "low": 0.50,
    "medium": 1.00,
    "high": 1.50,
    "saturation": 2.00,
    "oversaturation": 2.50,
}

BASE_FLOWS = {
    "f_W_E_straight": 630,
    "f_W_J1_right": 135,
    "f_W_J1_left": 135,

    "f_E_W_straight": 490,
    "f_E_J2_right": 105,
    "f_E_J2_left": 105,

    "f_N1_S1_straight": 210,
    "f_N1_W_right": 45,
    "f_N1_E_left": 45,

    "f_S1_N1_straight": 210,
    "f_S1_E_right": 45,
    "f_S1_W_left": 45,

    "f_N2_S2_straight": 210,
    "f_N2_E_right": 45,
    "f_N2_W_left": 45,

    "f_S2_N2_straight": 210,
    "f_S2_W_right": 45,
    "f_S2_E_left": 45,
}


def scaled(flow_id, multiplier):
    return int(round(BASE_FLOWS[flow_id] * multiplier))


def write_routes(folder: Path, multiplier: float):
    route_file = folder / "corridor_turning.rou.xml"

    content = f"""<routes>
    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" maxSpeed="{SPEED}"/>

    <!-- Main corridor demand: West side entering from E0 -->
    <route id="W_to_E_straight" edges="E0 E1 -E2"/>
    <route id="W_to_J1_right" edges="E0 -E5"/>
    <route id="W_to_J1_left" edges="E0 -E4"/>

    <flow id="f_W_E_straight" type="car" route="W_to_E_straight" begin="0" end="3600" vehsPerHour="{scaled('f_W_E_straight', multiplier)}"/>
    <flow id="f_W_J1_right" type="car" route="W_to_J1_right" begin="0" end="3600" vehsPerHour="{scaled('f_W_J1_right', multiplier)}"/>
    <flow id="f_W_J1_left" type="car" route="W_to_J1_left" begin="0" end="3600" vehsPerHour="{scaled('f_W_J1_left', multiplier)}"/>

    <!-- Main corridor demand: East side entering from E2 -->
    <route id="E_to_W_straight" edges="E2 -E1 -E0"/>
    <route id="E_to_J2_right" edges="E2 -E7"/>
    <route id="E_to_J2_left" edges="E2 -E6"/>

    <flow id="f_E_W_straight" type="car" route="E_to_W_straight" begin="0" end="3600" vehsPerHour="{scaled('f_E_W_straight', multiplier)}"/>
    <flow id="f_E_J2_right" type="car" route="E_to_J2_right" begin="0" end="3600" vehsPerHour="{scaled('f_E_J2_right', multiplier)}"/>
    <flow id="f_E_J2_left" type="car" route="E_to_J2_left" begin="0" end="3600" vehsPerHour="{scaled('f_E_J2_left', multiplier)}"/>

    <!-- Side road demand at J1: entering from E4 -->
    <route id="N1_to_S1_straight" edges="E4 -E5"/>
    <route id="N1_to_W_right" edges="E4 -E0"/>
    <route id="N1_to_E_left" edges="E4 E1 -E2"/>

    <flow id="f_N1_S1_straight" type="car" route="N1_to_S1_straight" begin="0" end="3600" vehsPerHour="{scaled('f_N1_S1_straight', multiplier)}"/>
    <flow id="f_N1_W_right" type="car" route="N1_to_W_right" begin="0" end="3600" vehsPerHour="{scaled('f_N1_W_right', multiplier)}"/>
    <flow id="f_N1_E_left" type="car" route="N1_to_E_left" begin="0" end="3600" vehsPerHour="{scaled('f_N1_E_left', multiplier)}"/>

    <!-- Side road demand at J1: entering from E5 -->
    <route id="S1_to_N1_straight" edges="E5 -E4"/>
    <route id="S1_to_E_right" edges="E5 E1 -E2"/>
    <route id="S1_to_W_left" edges="E5 -E0"/>

    <flow id="f_S1_N1_straight" type="car" route="S1_to_N1_straight" begin="0" end="3600" vehsPerHour="{scaled('f_S1_N1_straight', multiplier)}"/>
    <flow id="f_S1_E_right" type="car" route="S1_to_E_right" begin="0" end="3600" vehsPerHour="{scaled('f_S1_E_right', multiplier)}"/>
    <flow id="f_S1_W_left" type="car" route="S1_to_W_left" begin="0" end="3600" vehsPerHour="{scaled('f_S1_W_left', multiplier)}"/>

    <!-- Side road demand at J2: entering from E6 -->
    <route id="N2_to_S2_straight" edges="E6 -E7"/>
    <route id="N2_to_E_right" edges="E6 -E2"/>
    <route id="N2_to_W_left" edges="E6 -E1 -E0"/>

    <flow id="f_N2_S2_straight" type="car" route="N2_to_S2_straight" begin="0" end="3600" vehsPerHour="{scaled('f_N2_S2_straight', multiplier)}"/>
    <flow id="f_N2_E_right" type="car" route="N2_to_E_right" begin="0" end="3600" vehsPerHour="{scaled('f_N2_E_right', multiplier)}"/>
    <flow id="f_N2_W_left" type="car" route="N2_to_W_left" begin="0" end="3600" vehsPerHour="{scaled('f_N2_W_left', multiplier)}"/>

    <!-- Side road demand at J2: entering from E7 -->
    <route id="S2_to_N2_straight" edges="E7 -E6"/>
    <route id="S2_to_W_right" edges="E7 -E1 -E0"/>
    <route id="S2_to_E_left" edges="E7 -E2"/>

    <flow id="f_S2_N2_straight" type="car" route="S2_to_N2_straight" begin="0" end="3600" vehsPerHour="{scaled('f_S2_N2_straight', multiplier)}"/>
    <flow id="f_S2_W_right" type="car" route="S2_to_W_right" begin="0" end="3600" vehsPerHour="{scaled('f_S2_W_right', multiplier)}"/>
    <flow id="f_S2_E_left" type="car" route="S2_to_E_left" begin="0" end="3600" vehsPerHour="{scaled('f_S2_E_left', multiplier)}"/>
</routes>
"""

    route_file.write_text(content, encoding="utf-8")
    return route_file


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


def generate_scenario(name: str, multiplier: float):
    folder = OUTPUT_BASE / f"demand_{name}"
    folder.mkdir(parents=True, exist_ok=True)

    source_net = BASE_NETWORK_FOLDER / "corridor.net.xml"
    target_net = folder / "corridor.net.xml"

    shutil.copyfile(source_net, target_net)

    route_file = write_routes(folder, multiplier)
    cfg_file = write_config(folder)

    total_demand = sum(scaled(flow_id, multiplier) for flow_id in BASE_FLOWS)

    print("\n" + "=" * 70)
    print(f"Generated demand scenario: {name}")
    print(f"Multiplier: {multiplier}")
    print(f"Total demand: {total_demand} veh/h")
    print(f"Folder: {folder}")
    print(f"Network: {target_net}")
    print(f"Routes: {route_file}")
    print(f"Config: {cfg_file}")


def main():
    for name, multiplier in DEMAND_SCENARIOS.items():
        generate_scenario(name, multiplier)

    print("\nAll demand scenarios generated successfully.")
    print("Next step: test medium and oversaturation scenarios with SUMO.")


if __name__ == "__main__":
    main()