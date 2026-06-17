from generic_corridor_env import GenericCorridorEnv


def main():
    env = GenericCorridorEnv(
        sumo_binary="sumo",
        sumo_config="sumo_scenarios/scalability/corridor_5x2_d300m/corridor.sumocfg",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
    )

    state = env.reset()

    print("Traffic lights:", env.tl_ids)
    print("Number of agents:", len(env.tl_ids))
    print("Initial state:", state)
    print("State dimension:", len(state))
    print("\nDetected phase-lane groups:")

    for tl in env.tl_ids:
        print(f"\n{tl}")
        print("Phase 0 lanes:", env.phase0_lanes[tl])
        print("Phase 2 lanes:", env.phase2_lanes[tl])

    done = False
    decision = 0

    while not done and decision < 5:
        actions = [decision % 2 for _ in env.tl_ids]
        next_state, reward, done, info = env.step(actions)

        print("\nDecision:", decision)
        print("Actions:", actions)
        print("Next state:", next_state)
        print("Reward:", reward)
        print("Info:", info)

        decision += 1

    env.close()
    print("\nGeneric N-intersection environment test finished.")


if __name__ == "__main__":
    main()