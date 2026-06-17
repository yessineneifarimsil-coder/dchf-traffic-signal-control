import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    tl_id = traci.trafficlight.getIDList()[0]
    print("Traffic light:", tl_id)

    controlled_lanes = list(dict.fromkeys(traci.trafficlight.getControlledLanes(tl_id)))
    print("\nControlled lanes:")
    for i, lane in enumerate(controlled_lanes):
        print(f"{i}: {lane}")

    logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]

    print("\nPhase-to-lane green mapping:")
    for phase_index, phase in enumerate(logic.phases):
        state = phase.state
        green_lanes = []

        for lane, signal_char in zip(traci.trafficlight.getControlledLanes(tl_id), state):
            if signal_char.lower() == "g":
                green_lanes.append(lane)

        green_lanes = list(dict.fromkeys(green_lanes))

        print(f"\nPhase {phase_index}")
        print(f"State: {state}")
        print("Green lanes:")
        for lane in green_lanes:
            print(f"- {lane}")

    traci.close()


if __name__ == "__main__":
    main()