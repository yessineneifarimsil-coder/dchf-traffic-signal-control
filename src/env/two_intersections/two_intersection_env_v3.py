from two_intersection_env import TwoIntersectionEnv
import traci


class TwoIntersectionEnvV3(TwoIntersectionEnv):
    """
    V3 environment with richer state for QMIX V3.

    Local observation per agent:
        [
            side_queue,
            main_queue,
            side_density,
            main_density,
            side_mean_speed,
            main_mean_speed,
            current_green_code
        ]

    Global state:
        J1 local observation + J2 local observation
        dimension = 14
    """

    def __init__(self, *args, max_speed=13.89, vehicle_length=7.5, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_speed = max_speed
        self.vehicle_length = vehicle_length

    def get_lane_capacity(self, lane_id):
        lane_length = traci.lane.getLength(lane_id)
        return max(lane_length / self.vehicle_length, 1.0)

    def get_density(self, lanes):
        densities = []

        for lane in lanes:
            vehicle_number = traci.lane.getLastStepVehicleNumber(lane)
            capacity = self.get_lane_capacity(lane)
            densities.append(vehicle_number / capacity)

        if not densities:
            return 0.0

        return sum(densities) / len(densities)

    def get_lane_group_mean_speed(self, lanes):
        speeds = []

        for lane in lanes:
            speeds.append(traci.lane.getLastStepMeanSpeed(lane))

        if not speeds:
            return 0.0

        return sum(speeds) / len(speeds)

    def get_local_state(self, side_lanes, main_lanes, tl_id):
        side_queue = self.get_queue(side_lanes)
        main_queue = self.get_queue(main_lanes)

        side_density = self.get_density(side_lanes)
        main_density = self.get_density(main_lanes)

        side_speed = self.get_lane_group_mean_speed(side_lanes)
        main_speed = self.get_lane_group_mean_speed(main_lanes)

        current_green_code = 0 if self.current_green[tl_id] == self.SIDE_GREEN else 1

        return [
            side_queue,
            main_queue,
            side_density,
            main_density,
            side_speed,
            main_speed,
            current_green_code,
        ]

    def get_state(self):
        j1_state = self.get_local_state(
            self.J1_SIDE_LANES,
            self.J1_MAIN_LANES,
            "J1",
        )

        j2_state = self.get_local_state(
            self.J2_SIDE_LANES,
            self.J2_MAIN_LANES,
            "J2",
        )

        return j1_state + j2_state