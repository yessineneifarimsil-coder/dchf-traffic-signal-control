import traci

SUMO_BINARY = "sumo"
SUMO_CONFIG = "sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg"

traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

tls = list(traci.trafficlight.getIDList())
print("Traffic lights:", tls)

for tl in tls:
    logic = traci.trafficlight.getAllProgramLogics(tl)[0]
    print("\n" + "=" * 60)
    print("Traffic light:", tl)
    print("Number of phases:", len(logic.phases))

    for idx, phase in enumerate(logic.phases):
        print(f"Phase {idx}: duration={phase.duration}, state={phase.state}")

traci.close()