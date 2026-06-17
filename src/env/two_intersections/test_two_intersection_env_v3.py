import random
from two_intersection_env_v3 import TwoIntersectionEnvV3


def main():
    env = TwoIntersectionEnvV3(
        sumo_binary="sumo-gui",
        sumo_seed=0,
    )

    state = env.reset()

    print("Initial V3 state:")
    print(state)
    print("State dimension:", len(state))

    done = False
    decision = 0

    while not done and decision < 10:
        action = [random.choice([0, 1]), random.choice([0, 1])]

        next_state, reward, done, info = env.step(action)

        decision += 1

        print(
            f"Decision {decision} | "
            f"Action: {action} | "
            f"State dimension: {len(next_state)} | "
            f"Reward: {reward:.2f} | "
            f"Waiting: {info['total_waiting_time']:.2f} | "
            f"Speed: {info['mean_speed']:.2f} | "
            f"Queue: {info['total_queue']}"
        )

        print("Next state:", next_state)

    env.close()
    print("\nV3 environment test finished.")


if __name__ == "__main__":
    main()