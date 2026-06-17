import random
from three_intersection_env import ThreeIntersectionEnv


def main():
    env = ThreeIntersectionEnv(
        sumo_binary="sumo",
        sumo_config="sumo_scenarios/three_intersections/corridor_3x2/corridor_3x2_through.sumocfg",
        simulation_steps=3600,
        green_duration=42,
        yellow_duration=3,
        sumo_seed=0,
    )

    state = env.reset()

    print("Initial state:")
    print(state)
    print(f"State dimension: {len(state)}")

    done = False
    decision = 0
    total_reward = 0.0

    while not done:
        actions = [
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
        ]

        next_state, reward, done, info = env.step(actions)

        decision += 1
        total_reward += reward

        if decision % 10 == 0 or done:
            print(
                f"Decision {decision} | "
                f"Step {info['step_count']} | "
                f"Actions {actions} | "
                f"Vehicles {info['vehicle_count']} | "
                f"Waiting {info['total_waiting_time']:.2f} | "
                f"Speed {info['mean_speed']:.2f} | "
                f"Queue {info['total_queue']} | "
                f"Reward {reward:.2f}"
            )

    env.close()

    print("\nThreeIntersectionEnv test finished.")
    print(f"Total reward: {total_reward:.2f}")


if __name__ == "__main__":
    main()