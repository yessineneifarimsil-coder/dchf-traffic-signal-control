import traci


SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg"


def main():
    traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

    traffic_lights = traci.trafficlight.getIDList()
    print("Traffic lights:", traffic_lights)

    for tl_id in traffic_lights:
        print("\n" + "=" * 60)
        print(f"Traffic light: {tl_id}")

        controlled_lanes = list(dict.fromkeys(traci.trafficlight.getControlledLanes(tl_id)))

        print("\nControlled lanes:")
        for i, lane in enumerate(controlled_lanes):
            print(f"{i}: {lane}")

        logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]

        print("\nNumber of phases:", len(logic.phases))

        print("\nPhase-to-lane green mapping:")
        for phase_index, phase in enumerate(logic.phases):
            state = phase.state
            green_lanes = []

            for lane, signal_char in zip(traci.trafficlight.getControlledLanes(tl_id), state):
                if signal_char.lower() == "g":
                    green_lanes.append(lane)

            green_lanes = list(dict.fromkeys(green_lanes))

            print(f"\nPhase {phase_index}")
            print(f"Duration: {phase.duration}")
            print(f"State: {state}")
            print("Green lanes:")
            if green_lanes:
                for lane in green_lanes:
                    print(f"- {lane}")
            else:
                print("- none")

    traci.close()
    print("\nTwo-intersection inspection finished.")


if __name__ == "__main__":
    main()