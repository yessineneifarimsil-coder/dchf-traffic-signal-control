"""Two interchangeable transports for the environment's per-second TraCI reads.

The environment, reward, observation and detector code reads exactly the same
quantities through this one interface in both modes. An A/B comparison
therefore isolates the transport -- explicit getters versus TraCI
subscriptions -- and cannot be confounded by a difference in the consuming
logic, because the consuming logic is literally the same code.

GETTER mode reproduces the pre-optimisation read pattern and exists as an
engineering oracle for the equivalence harness. SUBSCRIPTION mode is the
optimised transport. Neither is a scientific configuration and neither defines
a second scientific method: the experiment is defined by the values, and the
harness in scripts/adaptive_qmix/ab_equivalence.py exists to prove those
values identical.

Per-second call contract, which the environment must honour in this order:

    note_departures(departed_ids)   # subscribe vehicles inserted this second
    refresh()                       # refresh the per-second view
    ... reads ...

note_departures must precede refresh: traci.vehicle.subscribe() returns the
subscribed vehicle's current values immediately, so a vehicle inserted this
second is present in this second's view and contributes its first second of
reward, waiting, arrival and detector state exactly as the getter path does.
"""

from __future__ import absolute_import


GETTER = "getter"
SUBSCRIPTION = "subscription"
MODES = (GETTER, SUBSCRIPTION)

DEFAULT_MODE = SUBSCRIPTION


class TraciAccessError(RuntimeError):
    pass


class _BaseDataSource(object):
    """Shared per-second caching of the active vehicle list.

    Both modes cache the active-vehicle list for the duration of one refresh
    cycle. The simulation does not advance between reads within a simulated
    second, so this is value-preserving in getter mode and keeps the two modes
    structurally parallel for the A/B harness.
    """

    mode = None

    def __init__(self, traci_module):
        self.traci = traci_module
        self.lane_ids = ()
        self._vehicle_ids = None

    def begin_episode(self, lane_ids):
        self.lane_ids = tuple(lane_ids)
        self._vehicle_ids = None

    def note_departures(self, vehicle_ids):
        pass

    def refresh(self):
        self._vehicle_ids = None

    def vehicle_ids(self):
        if self._vehicle_ids is None:
            self._vehicle_ids = list(self.traci.vehicle.getIDList())
        return self._vehicle_ids


class GetterDataSource(_BaseDataSource):
    """Explicit per-quantity getters: the pre-optimisation transport."""

    mode = GETTER

    def vehicle_speed(self, vehicle_id):
        return self.traci.vehicle.getSpeed(vehicle_id)

    def vehicle_waiting_time(self, vehicle_id):
        return self.traci.vehicle.getWaitingTime(vehicle_id)

    def vehicle_lane_id(self, vehicle_id):
        return self.traci.vehicle.getLaneID(vehicle_id)

    def vehicle_lane_position(self, vehicle_id):
        return self.traci.vehicle.getLanePosition(vehicle_id)

    def lane_halting_number(self, lane_id):
        return self.traci.lane.getLastStepHaltingNumber(lane_id)

    def lane_vehicle_number(self, lane_id):
        return self.traci.lane.getLastStepVehicleNumber(lane_id)

    def lane_occupancy(self, lane_id):
        return self.traci.lane.getLastStepOccupancy(lane_id)

    def lane_mean_speed(self, lane_id):
        return self.traci.lane.getLastStepMeanSpeed(lane_id)

    def lane_vehicle_ids(self, lane_id):
        return self.traci.lane.getLastStepVehicleIDs(lane_id)


class SubscriptionDataSource(_BaseDataSource):
    """TraCI subscriptions.

    getAllSubscriptionResults() is a local dictionary read on the client: the
    values arrive with the simulationStep response, so the whole per-second
    read set costs no socket round trips at all. Only the one-off lane
    subscriptions and the per-vehicle subscription at insertion cost a call.
    """

    mode = SUBSCRIPTION

    def __init__(self, traci_module):
        super(SubscriptionDataSource, self).__init__(traci_module)
        constants = getattr(traci_module, "constants", None)
        if constants is None:
            try:
                import traci.constants as constants  # noqa: F401
            except ImportError:
                raise TraciAccessError(
                    "Subscription mode needs traci.constants; use getter mode."
                )
        self._c = constants
        self.vehicle_variables = (
            constants.VAR_SPEED,
            constants.VAR_WAITING_TIME,
            constants.VAR_LANE_ID,
            constants.VAR_LANEPOSITION,
        )
        self.lane_variables = (
            constants.LAST_STEP_VEHICLE_HALTING_NUMBER,
            constants.LAST_STEP_VEHICLE_NUMBER,
            constants.LAST_STEP_OCCUPANCY,
            constants.LAST_STEP_MEAN_SPEED,
            constants.LAST_STEP_VEHICLE_ID_LIST,
        )
        self._vehicle_view = {}
        self._lane_view = {}
        self.subscribed_vehicles = set()
        self.healed_subscriptions = 0

    def begin_episode(self, lane_ids):
        # A new episode is a new SUMO process and a new TraCI connection, so
        # no subscription state may survive from the previous one.
        super(SubscriptionDataSource, self).begin_episode(lane_ids)
        self._vehicle_view = {}
        self._lane_view = {}
        self.subscribed_vehicles = set()
        self.healed_subscriptions = 0
        for lane_id in self.lane_ids:
            self.traci.lane.subscribe(lane_id, list(self.lane_variables))
        self.refresh()

    def note_departures(self, vehicle_ids):
        for vehicle_id in vehicle_ids:
            if vehicle_id in self.subscribed_vehicles:
                continue
            self.traci.vehicle.subscribe(vehicle_id, list(self.vehicle_variables))
            self.subscribed_vehicles.add(vehicle_id)

    def refresh(self):
        super(SubscriptionDataSource, self).refresh()
        self._vehicle_view = self.traci.vehicle.getAllSubscriptionResults()
        self._lane_view = self.traci.lane.getAllSubscriptionResults()
        self._resubscribe_active_vehicles_without_a_view()

    def _resubscribe_active_vehicles_without_a_view(self):
        """Re-subscribe any active vehicle whose subscription SUMO dropped.

        A vehicle that SUMO removes and reinserts -- a teleport -- is not
        reported by getDepartedIDList a second time, so its subscription can be
        gone while the vehicle is active again. Reading it would then raise
        where the getter path would have succeeded, which is a difference in
        transport rather than in science. Healing here keeps the two
        transports equivalent under teleporting. In normal operation the set is
        empty and this costs nothing; the count is kept so a run that needed
        healing is auditable rather than silent.
        """
        missing = [
            vehicle_id for vehicle_id in self.vehicle_ids()
            if vehicle_id not in self._vehicle_view
        ]
        if not missing:
            return
        for vehicle_id in missing:
            self.traci.vehicle.subscribe(vehicle_id, list(self.vehicle_variables))
            self.subscribed_vehicles.add(vehicle_id)
        self._vehicle_view = self.traci.vehicle.getAllSubscriptionResults()
        self.healed_subscriptions += len(missing)

    def _vehicle(self, vehicle_id, variable, name):
        row = self._vehicle_view.get(vehicle_id)
        if row is None or variable not in row:
            raise TraciAccessError(
                "No subscribed {} for vehicle {}; note_departures() must run "
                "before refresh() each second.".format(name, vehicle_id)
            )
        return row[variable]

    def _lane(self, lane_id, variable, name):
        row = self._lane_view.get(lane_id)
        if row is None or variable not in row:
            raise TraciAccessError(
                "No subscribed {} for lane {}; begin_episode() must run after "
                "every reset.".format(name, lane_id)
            )
        return row[variable]

    def vehicle_speed(self, vehicle_id):
        return self._vehicle(vehicle_id, self._c.VAR_SPEED, "speed")

    def vehicle_waiting_time(self, vehicle_id):
        return self._vehicle(vehicle_id, self._c.VAR_WAITING_TIME, "waiting time")

    def vehicle_lane_id(self, vehicle_id):
        return self._vehicle(vehicle_id, self._c.VAR_LANE_ID, "lane id")

    def vehicle_lane_position(self, vehicle_id):
        return self._vehicle(vehicle_id, self._c.VAR_LANEPOSITION, "lane position")

    def lane_halting_number(self, lane_id):
        return self._lane(
            lane_id, self._c.LAST_STEP_VEHICLE_HALTING_NUMBER, "halting number"
        )

    def lane_vehicle_number(self, lane_id):
        return self._lane(
            lane_id, self._c.LAST_STEP_VEHICLE_NUMBER, "vehicle number"
        )

    def lane_occupancy(self, lane_id):
        return self._lane(lane_id, self._c.LAST_STEP_OCCUPANCY, "occupancy")

    def lane_mean_speed(self, lane_id):
        return self._lane(lane_id, self._c.LAST_STEP_MEAN_SPEED, "mean speed")

    def lane_vehicle_ids(self, lane_id):
        return self._lane(
            lane_id, self._c.LAST_STEP_VEHICLE_ID_LIST, "vehicle id list"
        )


def create_data_source(traci_module, mode=DEFAULT_MODE):
    if mode == GETTER:
        return GetterDataSource(traci_module)
    if mode == SUBSCRIPTION:
        return SubscriptionDataSource(traci_module)
    raise ValueError(
        "Unknown TraCI access mode {!r}; expected one of {}.".format(mode, MODES)
    )
