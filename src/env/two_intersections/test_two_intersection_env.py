import random
from two_intersection_env import TwoIntersectionEnv


def main():
    env = TwoIntersectionEnv(sumo_binary="sumo-gui")

    state = env.reset()
    print("Initial state:", state)

    done = False
    decision = 0
    episode_reward = 0.0

    while not done:
        action = [random.choice([0, 1]), random.choice([0, 1])]

        next_state, reward, done, info = env.step(action)

        decision += 1
        episode_reward += reward

        print(
            f"Decision {decision} | "
            f"Action: {action} | "
            f"State: {next_state} | "
            f"Reward: {reward:.2f} | "
            f"Vehicles: {info['vehicle_count']} | "
            f"Waiting: {info['total_waiting_time']:.2f} | "
            f"Speed: {info['mean_speed']:.2f} | "
            f"Queue: {info['total_queue']}"
        )

    env.close()

    print("\nTwo-intersection environment test finished.")
    print(f"Total episode reward: {episode_reward:.2f}")


if __name__ == "__main__":
    main()