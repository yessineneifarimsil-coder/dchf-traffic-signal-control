import traci


class GenericCorridorEnv:
    """
    Generic SUMO-TraCI environment for an N-intersection corridor.

    It assumes each traffic light has:
        phase 0 = green group A
        phase 1 = yellow group A
        phase 2 = green group B
        phase 3 = yellow group B

    Each agent has two actions:
        action 0 -> phase 0
        action 1 -> phase 2

    Observation per agent:
        [
            queue_on_phase0_green_lanes,
            queue_on_phase2_green_lanes,
            current_green_code
        ]

    Global state:
        concatenation of all local observations.
    """

    def __init__(
        self,
        sumo_binary="sumo",
        sumo_config="sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg",
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

        self.PHASE0_GREEN = 0
        self.PHASE0_YELLOW = 1
        self.PHASE2_GREEN = 2
        self.PHASE2_YELLOW = 3

        self.step_count = 0
        self.tl_ids = []
        self.current_green = {}
        self.phase0_lanes = {}
        self.phase2_lanes = {}

    def reset(self):
        try:
            traci.close()
        except Exception:
            pass

        sumo_cmd = [
            self.sumo_binary,
            "-c",
            self.sumo_config,
            "--no-step-log",
            "true",
        ]

        if self.sumo_seed is not None:
            sumo_cmd += ["--seed", str(self.sumo_seed)]

        traci.start(sumo_cmd)

        self.tl_ids = list(traci.trafficlight.getIDList())
        self.tl_ids.sort(key=lambda x: int(x.replace("J", "")) if x.startswith("J") else x)

        if not self.tl_ids:
            raise RuntimeError("No traffic lights found in SUMO network.")

        self.step_count = 0
        self.current_green = {tl_id: self.PHASE2_GREEN for tl_id in self.tl_ids}

        self._build_phase_lane_groups()

        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, self.PHASE2_GREEN)
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)

        traci.simulationStep()
        self.step_count += 1

        return self.get_state()

    def _unique(self, items):
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _build_phase_lane_groups(self):
        """
        Automatically identifies the lanes served by phase 0 and phase 2
        using traffic-light controlled lanes and phase states.
        """
        self.phase0_lanes = {}
        self.phase2_lanes = {}

        for tl_id in self.tl_ids:
            lanes = list(traci.trafficlight.getControlledLanes(tl_id))
            logic = traci.trafficlight.getAllProgramLogics(tl_id)[0]

            if len(logic.phases) < 3:
                raise RuntimeError(f"Traffic light {tl_id} has fewer than 3 phases.")

            phase0_state = logic.phases[self.PHASE0_GREEN].state
            phase2_state = logic.phases[self.PHASE2_GREEN].state

            p0_lanes = []
            p2_lanes = []

            for idx, lane in enumerate(lanes):
                if idx < len(phase0_state) and phase0_state[idx] in ["G", "g"]:
                    p0_lanes.append(lane)
                if idx < len(phase2_state) and phase2_state[idx] in ["G", "g"]:
                    p2_lanes.append(lane)

            self.phase0_lanes[tl_id] = self._unique(p0_lanes)
            self.phase2_lanes[tl_id] = self._unique(p2_lanes)

            if not self.phase0_lanes[tl_id]:
                raise RuntimeError(f"No phase-0 green lanes detected for {tl_id}.")
            if not self.phase2_lanes[tl_id]:
                raise RuntimeError(f"No phase-2 green lanes detected for {tl_id}.")

    def action_to_phase(self, action):
        if action == 0:
            return self.PHASE0_GREEN
        if action == 1:
            return self.PHASE2_GREEN
        raise ValueError(f"Invalid action: {action}")

    def green_to_code(self, phase):
        return 0 if phase == self.PHASE0_GREEN else 1

    def get_queue(self, lanes):
        total = 0
        for lane in lanes:
            try:
                total += traci.lane.getLastStepHaltingNumber(lane)
            except Exception:
                pass
        return total

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
        state = []

        for tl_id in self.tl_ids:
            q0 = self.get_queue(self.phase0_lanes[tl_id])
            q2 = self.get_queue(self.phase2_lanes[tl_id])
            current_code = self.green_to_code(self.current_green[tl_id])

            state.extend([q0, q2, current_code])

        return state

    def step(self, actions):
        if len(actions) != len(self.tl_ids):
            raise ValueError(
                f"Expected {len(self.tl_ids)} actions, got {len(actions)}."
            )

        selected_phases = {
            tl_id: self.action_to_phase(actions[i])
            for i, tl_id in enumerate(self.tl_ids)
        }

        # Yellow phase when switching
        yellow_needed = False

        for tl_id in self.tl_ids:
            old_green = self.current_green[tl_id]
            new_green = selected_phases[tl_id]

            if old_green != new_green:
                yellow_phase = (
                    self.PHASE0_YELLOW
                    if old_green == self.PHASE0_GREEN
                    else self.PHASE2_YELLOW
                )
                traci.trafficlight.setPhase(tl_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(tl_id, self.yellow_duration)
                yellow_needed = True

        if yellow_needed:
            for _ in range(self.yellow_duration):
                traci.simulationStep()
                self.step_count += 1

        # Green phase
        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, selected_phases[tl_id])
            traci.trafficlight.setPhaseDuration(tl_id, self.green_duration)
            self.current_green[tl_id] = selected_phases[tl_id]

        for _ in range(self.green_duration):
            traci.simulationStep()
            self.step_count += 1

        next_state = self.get_state()
        reward = -self.get_total_waiting_time()

        done = self.step_count >= self.simulation_steps

        info = {
            "step": self.step_count,
            "vehicle_count": len(traci.vehicle.getIDList()),
            "total_waiting_time": self.get_total_waiting_time(),
            "mean_speed": self.get_mean_speed(),
            "total_queue": self.get_total_queue(),
            "departed": traci.simulation.getDepartedNumber(),
            "arrived": traci.simulation.getArrivedNumber(),
        }

        return next_state, reward, done, info

    def close(self):
        try:
            traci.close()
        except Exception:
            pass