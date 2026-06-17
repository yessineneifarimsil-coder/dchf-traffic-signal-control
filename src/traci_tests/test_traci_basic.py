import traci

SUMO_BINARY = "sumo-gui"
SUMO_CONFIG = "sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg"

traci.start([SUMO_BINARY, "-c", SUMO_CONFIG])

tl_id = traci.trafficlight.getIDList()[0]
logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]

print("Traffic light:", tl_id)
print("Number of phases:", len(logic.phases))

for i, phase in enumerate(logic.phases):
    print(f"Phase {i}: duration={phase.duration}, state={phase.state}")

traci.close()