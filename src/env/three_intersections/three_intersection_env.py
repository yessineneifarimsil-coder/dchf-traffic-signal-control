import traci


class ThreeIntersectionEnv:
    def __init__(
        self,
        sumo_binary="sumo",
        sumo_config="sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2_through.sumocfg",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=0,
    ):
        self.sumo_binary = sumo_binary
        self.sumo_config = sumo_config
        self.simulation_steps = simulation_steps
        self.green_duration = green_duration
        self.yellow_duration = yellow_duration
        self.sumo_seed = sumo_seed

        self.tl_ids = ["J1", "J2", "J3"]

        self.SIDE_GREEN = 0
        self.SIDE_YELLOW = 1
        self.MAIN_GREEN = 2
        self.MAIN_YELLOW = 3

        self.current_green = {
            "J1": self.SIDE_GREEN,
            "J2": self.SIDE_GREEN,
            "J3": self.SIDE_GREEN,
        }

        self.step_count = 0

    def _start_sumo(self):
        try:
            if traci.isLoaded():
                traci.close()
        except Exception:
            pass

        sumo_cmd = [
            self.sumo_binary,
            "-c",
            self.sumo_config,
            "--seed",
            str(self.sumo_seed),
            "--no-step-log",
            "true",
        ]

        traci.start(sumo_cmd)

    def reset(self):
        self._start_sumo()

        self.step_count = 0

        self.current_green = {
            "J1": self.SIDE_GREEN,
            "J2": self.SIDE_GREEN,
            "J3": self.SIDE_GREEN,
        }

        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, self.SIDE_GREEN)
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)

        return self.get_state()

    def close(self):
        try:
            if traci.isLoaded():
                traci.close()
        except Exception:
            pass

    def get_lane_queue(self, lane_id):
        return traci.lane.getLastStepHaltingNumber(lane_id)

    def get_edge_queue(self, edge_id):
        total_queue = 0

        for lane_id in traci.lane.getIDList():
            if lane_id.startswith(edge_id + "_"):
                total_queue += traci.lane.getLastStepHaltingNumber(lane_id)

        return total_queue

    def get_total_waiting_time(self):
        return sum(
            traci.vehicle.getWaitingTime(vehicle_id)
            for vehicle_id in traci.vehicle.getIDList()
        )

    def get_total_queue(self):
        total_queue = 0

        for lane_id in traci.lane.getIDList():
            if not lane_id.startswith(":"):
                total_queue += traci.lane.getLastStepHaltingNumber(lane_id)

        return total_queue

    def get_mean_speed(self):
        vehicle_ids = traci.vehicle.getIDList()

        if not vehicle_ids:
            return 0.0

        return sum(traci.vehicle.getSpeed(v) for v in vehicle_ids) / len(vehicle_ids)

    def get_vehicle_count(self):
        return len(traci.vehicle.getIDList())

    def get_junction_queues(self, tl_id):
        """
        Returns:
        side_queue, main_queue

        Main direction:
        - J1: incoming E0 and -E1
        - J2: incoming E1 and -E2
        - J3: incoming E2 and E3

        Side direction:
        - J1: incoming E4 and E5
        - J2: incoming E6 and E7
        - J3: incoming E8 and E9
        """
        if tl_id == "J1":
            main_edges = ["E0", "-E1"]
            side_edges = ["E4", "E5"]

        elif tl_id == "J2":
            main_edges = ["E1", "-E2"]
            side_edges = ["E6", "E7"]

        elif tl_id == "J3":
            main_edges = ["E2", "E3"]
            side_edges = ["E8", "E9"]

        else:
            raise ValueError(f"Unknown traffic light id: {tl_id}")

        main_queue = sum(self.get_edge_queue(edge_id) for edge_id in main_edges)
        side_queue = sum(self.get_edge_queue(edge_id) for edge_id in side_edges)

        return side_queue, main_queue

    def get_state(self):
        """
        Global state dimension = 9.

        For each intersection:
        [side_queue, main_queue, current_phase_binary]

        current_phase_binary:
        0 = side green
        1 = main green
        """
        state = []

        for tl_id in self.tl_ids:
            side_queue, main_queue = self.get_junction_queues(tl_id)

            phase_binary = 0
            if self.current_green[tl_id] == self.MAIN_GREEN:
                phase_binary = 1

            state.extend([
                float(side_queue),
                float(main_queue),
                float(phase_binary),
            ])

        return state

    def action_to_green_phase(self, action):
        if action == 0:
            return self.SIDE_GREEN

        if action == 1:
            return self.MAIN_GREEN

        raise ValueError(f"Invalid action: {action}")

    def yellow_phase_between(self, old_green, new_green):
        if old_green == new_green:
            return None

        if old_green == self.SIDE_GREEN and new_green == self.MAIN_GREEN:
            return self.SIDE_YELLOW

        if old_green == self.MAIN_GREEN and new_green == self.SIDE_GREEN:
            return self.MAIN_YELLOW

        raise ValueError(f"Unexpected transition: {old_green} -> {new_green}")

    def simulation_step(self):
        traci.simulationStep()
        self.step_count += 1

        reward = -self.get_total_waiting_time()

        done = self.step_count >= self.simulation_steps

        return reward, done

    def step(self, actions):
        """
        actions = [action_J1, action_J2, action_J3]
        each action:
        0 = side green
        1 = main green
        """
        if len(actions) != 3:
            raise ValueError("ThreeIntersectionEnv expects exactly 3 actions.")

        selected_green = {
            "J1": self.action_to_green_phase(actions[0]),
            "J2": self.action_to_green_phase(actions[1]),
            "J3": self.action_to_green_phase(actions[2]),
        }

        total_reward = 0.0
        done = False

        yellow_needed = False

        for tl_id in self.tl_ids:
            old_green = self.current_green[tl_id]
            new_green = selected_green[tl_id]

            yellow_phase = self.yellow_phase_between(old_green, new_green)

            if yellow_phase is not None:
                traci.trafficlight.setPhase(tl_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(tl_id, self.yellow_duration)
                yellow_needed = True

        if yellow_needed:
            for _ in range(self.yellow_duration):
                if self.step_count >= self.simulation_steps:
                    break

                reward, done = self.simulation_step()
                total_reward += reward

        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_green[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)
            self.current_green[tl_id] = selected_green[tl_id]

        for _ in range(self.green_duration):
            if self.step_count >= self.simulation_steps:
                break

            reward, done = self.simulation_step()
            total_reward += reward

        next_state = self.get_state()

        info = {
            "step_count": self.step_count,
            "vehicle_count": self.get_vehicle_count(),
            "total_waiting_time": self.get_total_waiting_time(),
            "mean_speed": self.get_mean_speed(),
            "total_queue": self.get_total_queue(),
            "J1_phase": traci.trafficlight.getPhase("J1"),
            "J2_phase": traci.trafficlight.getPhase("J2"),
            "J3_phase": traci.trafficlight.getPhase("J3"),
        }

        return next_state, total_reward, done, info