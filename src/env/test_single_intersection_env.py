import random
from single_intersection_env import SingleIntersectionEnv


def main():
    env = SingleIntersectionEnv(sumo_binary="sumo-gui")

    state = env.reset()
    print("Initial state:", state)

    done = False
    episode_reward = 0
    step_number = 0

    while not done:
        action = random.choice([0, 1])

        next_state, reward, done, info = env.step(action)

        episode_reward += reward
        step_number += 1

        print(
            f"Decision {step_number} | "
            f"Action: {action} | "
            f"State: {next_state} | "
            f"Reward: {reward:.2f} | "
            f"Vehicles: {info['vehicle_count']} | "
            f"Waiting: {info['total_waiting_time']:.2f} | "
            f"Speed: {info['mean_speed']:.2f}"
        )

    env.close()

    print("Episode finished.")
    print("Total episode reward:", episode_reward)


if __name__ == "__main__":
    main()