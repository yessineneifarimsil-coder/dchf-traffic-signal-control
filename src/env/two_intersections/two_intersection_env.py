import traci


class TwoIntersectionEnv:
    """
    SUMO-TraCI environment for a two-intersection corridor.

    Traffic lights:
        J1 and J2

    Actions:
        action = (a1, a2)
        a1 controls J1:
            0 -> side green phase 0
            1 -> main green phase 2
        a2 controls J2:
            0 -> side green phase 0
            1 -> main green phase 2

    State:
        [
            J1_side_queue,
            J1_main_queue,
            J1_current_green_code,
            J2_side_queue,
            J2_main_queue,
            J2_current_green_code
        ]

    Reward:
        negative total waiting time over the whole corridor
    """

    def __init__(
        self,
        sumo_binary="sumo-gui",
        sumo_config="sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.sumocfg",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=None,
    ):
        self.sumo_binary = sumo_binary
        self.sumo_config = sumo_config
        self.simulation_steps = simulation_steps
        self.green_duration = green_duration
        self.yellow_duration = yellow_duration
        self.sumo_seed = sumo_seed

        self.step_count = 0

        self.tl_ids = ["J1", "J2"]

        self.SIDE_GREEN = 0
        self.SIDE_YELLOW = 1
        self.MAIN_GREEN = 2
        self.MAIN_YELLOW = 3

        self.current_green = {
            "J1": self.MAIN_GREEN,
            "J2": self.MAIN_GREEN,
        }

        # Phase-to-lane mappings from inspect_two_intersections.py
        self.J1_SIDE_LANES = ["E4_0", "E4_1", "E5_0", "E5_1"]
        self.J1_MAIN_LANES = ["-E1_0", "-E1_1", "E0_0", "E0_1"]

        self.J2_SIDE_LANES = ["E7_0", "E7_1", "E6_0", "E6_1"]
        self.J2_MAIN_LANES = ["E2_0", "E2_1", "E1_0", "E1_1"]

    def reset(self):
        try:
            traci.close()
        except Exception:
            pass

        sumo_cmd = [self.sumo_binary, "-c", self.sumo_config]

        if self.sumo_seed is not None:
            sumo_cmd += ["--seed", str(self.sumo_seed)]

        traci.start(sumo_cmd)

        traffic_lights = traci.trafficlight.getIDList()
        for tl_id in self.tl_ids:
            if tl_id not in traffic_lights:
                raise RuntimeError(f"Traffic light {tl_id} not found.")

        self.step_count = 0

        self.current_green = {
            "J1": self.MAIN_GREEN,
            "J2": self.MAIN_GREEN,
        }

        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, self.MAIN_GREEN)
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)

        traci.simulationStep()
        self.step_count += 1

        return self.get_state()
    def get_queue(self, lanes):
        return sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)

    def get_total_waiting_time(self):
        return sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())

    def get_mean_speed(self):
        vehicles = traci.vehicle.getIDList()
        if not vehicles:
            return 0.0
        return sum(traci.vehicle.getSpeed(v) for v in vehicles) / len(vehicles)

    def get_total_queue(self):
        total_queue = 0
        for lane_id in traci.lane.getIDList():
            if not lane_id.startswith(":"):
                total_queue += traci.lane.getLastStepHaltingNumber(lane_id)
        return total_queue

    def get_state(self):
        j1_side_q = self.get_queue(self.J1_SIDE_LANES)
        j1_main_q = self.get_queue(self.J1_MAIN_LANES)

        j2_side_q = self.get_queue(self.J2_SIDE_LANES)
        j2_main_q = self.get_queue(self.J2_MAIN_LANES)

        j1_green_code = 0 if self.current_green["J1"] == self.SIDE_GREEN else 1
        j2_green_code = 0 if self.current_green["J2"] == self.SIDE_GREEN else 1

        return [
            j1_side_q,
            j1_main_q,
            j1_green_code,
            j2_side_q,
            j2_main_q,
            j2_green_code,
        ]

    def action_to_phase(self, action):
        if action == 0:
            return self.SIDE_GREEN
        if action == 1:
            return self.MAIN_GREEN
        raise ValueError("Invalid action. Use 0 for side green or 1 for main green.")

    def yellow_phase_between(self, old_green, new_green):
        if old_green == new_green:
            return None

        if old_green == self.SIDE_GREEN and new_green == self.MAIN_GREEN:
            return self.SIDE_YELLOW

        if old_green == self.MAIN_GREEN and new_green == self.SIDE_GREEN:
            return self.MAIN_YELLOW

        raise ValueError(f"Unexpected phase transition: {old_green} -> {new_green}")

    def run_yellow_if_needed(self, selected_phases):
        """
        Apply yellow transitions for J1 and/or J2 if their selected phase changes.
        """
        yellow_needed = False

        for tl_id in self.tl_ids:
            old_green = self.current_green[tl_id]
            new_green = selected_phases[tl_id]

            yellow_phase = self.yellow_phase_between(old_green, new_green)

            if yellow_phase is not None:
                traci.trafficlight.setPhase(tl_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(tl_id, self.yellow_duration)
                yellow_needed = True

        if yellow_needed:
            for _ in range(self.yellow_duration):
                if self.step_count >= self.simulation_steps:
                    break
                traci.simulationStep()
                self.step_count += 1

    def run_green(self, selected_phases):
        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)
            self.current_green[tl_id] = selected_phases[tl_id]

        cumulative_reward = 0.0

        for _ in range(self.green_duration):
            if self.step_count >= self.simulation_steps:
                break

            traci.simulationStep()
            self.step_count += 1

            cumulative_reward += -self.get_total_waiting_time()

        return cumulative_reward

    def step(self, action):
        """
        action:
            tuple/list (a1, a2)
            a1 for J1, a2 for J2
        """
        if len(action) != 2:
            raise ValueError("Action must be a tuple/list with two elements: (a1, a2).")

        selected_phases = {
            "J1": self.action_to_phase(action[0]),
            "J2": self.action_to_phase(action[1]),
        }

        self.run_yellow_if_needed(selected_phases)

        reward = self.run_green(selected_phases)

        next_state = self.get_state()
        done = self.step_count >= self.simulation_steps

        info = {
            "step": self.step_count,
            "vehicle_count": len(traci.vehicle.getIDList()),
            "total_waiting_time": self.get_total_waiting_time(),
            "mean_speed": self.get_mean_speed(),
            "total_queue": self.get_total_queue(),
            "J1_phase": traci.trafficlight.getPhase("J1"),
            "J2_phase": traci.trafficlight.getPhase("J2"),
            "J1_current_green": self.current_green["J1"],
            "J2_current_green": self.current_green["J2"],
            "J1_side_queue": next_state[0],
            "J1_main_queue": next_state[1],
            "J2_side_queue": next_state[3],
            "J2_main_queue": next_state[4],
        }

        return next_state, reward, done, info

    def close(self):
        try:
            traci.close()
        except Exception:
            pass