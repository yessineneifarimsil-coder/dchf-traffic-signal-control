import traci


class SingleIntersectionEnv:
    """
    Simple SUMO-TraCI environment for one 2x2 signalized intersection.

    State:
        [queue_phase_0, queue_phase_3, current_green]

    Actions:
        0 -> choose green phase 0
        1 -> choose green phase 3

    Reward:
        negative total waiting time
    """

    def __init__(
        self,
        sumo_binary="sumo-gui",
        sumo_config="sumo_scenarios/single_intersection/1tls_2x2/1tls_2x2.sumocfg",
        simulation_steps=3600,
        green_duration=30,
        yellow_duration=3,
        all_red_duration=2,
    ):
        self.sumo_binary = sumo_binary
        self.sumo_config = sumo_config

        self.simulation_steps = simulation_steps
        self.green_duration = green_duration
        self.yellow_duration = yellow_duration
        self.all_red_duration = all_red_duration

        self.step_count = 0
        self.tl_id = None
        self.current_green = None

        # Correct mapping from your inspection script
        self.phase_0_lanes = [
            "gneE0_0",
            "gneE0_1",
            "-gneE2_0",
            "-gneE2_1",
        ]

        self.phase_3_lanes = [
            "-gneE1_0",
            "-gneE1_1",
            "-gneE3_0",
            "-gneE3_1",
        ]

    def reset(self):
        """
        Start a new SUMO simulation and return the initial state.
        """
        try:
            traci.close()
        except Exception:
            pass

        traci.start([self.sumo_binary, "-c", self.sumo_config])

        traffic_lights = traci.trafficlight.getIDList()
        if not traffic_lights:
            raise RuntimeError("No traffic light found in the SUMO scenario.")

        self.tl_id = traffic_lights[0]
        self.step_count = 0
        self.current_green = 0

        traci.trafficlight.setPhase(self.tl_id, self.current_green)
        traci.trafficlight.setPhaseDuration(self.tl_id, self.green_duration)

        # Run one simulation step so vehicles and lanes are initialized
        traci.simulationStep()
        self.step_count += 1

        return self.get_state()

    def get_queue_on_lanes(self, lanes):
        """
        Count halting vehicles on a list of lanes.
        """
        return sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)

    def get_total_waiting_time(self):
        """
        Total waiting time over all vehicles currently in the simulation.
        """
        return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())

    def get_mean_speed(self):
        vehicles = traci.vehicle.getIDList()
        if not vehicles:
            return 0.0
        return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)

    def get_state(self):
        """
        Return a simple numerical state:
        [queue_phase_0, queue_phase_3, current_green_code]

        current_green_code:
            0 if current green is phase 0
            1 if current green is phase 3
        """
        queue_0 = self.get_queue_on_lanes(self.phase_0_lanes)
        queue_3 = self.get_queue_on_lanes(self.phase_3_lanes)

        current_green_code = 0 if self.current_green == 0 else 1

        return [queue_0, queue_3, current_green_code]

    def run_phase(self, phase, duration):
        """
        Apply one phase for a given duration.
        """
        traci.trafficlight.setPhase(self.tl_id, phase)
        traci.trafficlight.setPhaseDuration(self.tl_id, duration)

        for _ in range(duration):
            if self.step_count >= self.simulation_steps:
                break

            traci.simulationStep()
            self.step_count += 1

    def apply_safe_transition(self, new_green):
        """
        Apply safe yellow and all-red transition if switching green phase.
        """
        if self.current_green == new_green:
            return

        if self.current_green == 0 and new_green == 3:
            self.run_phase(1, self.yellow_duration)
            self.run_phase(2, self.all_red_duration)

        elif self.current_green == 3 and new_green == 0:
            self.run_phase(4, self.yellow_duration)
            self.run_phase(5, self.all_red_duration)

        else:
            raise ValueError(f"Unexpected transition: {self.current_green} -> {new_green}")

        self.current_green = new_green

    def step(self, action):
        """
        Apply action and return:
        next_state, reward, done, info

        action:
            0 -> phase 0
            1 -> phase 3
        """
        if action == 0:
            selected_green = 0
        elif action == 1:
            selected_green = 3
        else:
            raise ValueError("Invalid action. Use 0 for phase 0 or 1 for phase 3.")

        self.apply_safe_transition(selected_green)

        self.current_green = selected_green
        self.run_phase(selected_green, self.green_duration)

        next_state = self.get_state()

        total_waiting_time = self.get_total_waiting_time()
        reward = -total_waiting_time

        done = self.step_count >= self.simulation_steps

        info = {
            "step": self.step_count,
            "vehicle_count": len(traci.vehicle.getIDList()),
            "total_waiting_time": total_waiting_time,
            "mean_speed": self.get_mean_speed(),
            "current_green": self.current_green,
            "queue_phase_0": next_state[0],
            "queue_phase_3": next_state[1],
        }

        return next_state, reward, done, info

    def close(self):
        try:
            traci.close()
        except Exception:
            pass