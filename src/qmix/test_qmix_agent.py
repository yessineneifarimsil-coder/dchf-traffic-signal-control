from qmix_agent import QMIXAgent


def main():
    agent = QMIXAgent(
        n_agents=2,
        obs_dim=3,
        state_dim=6,
        action_dim=2,
        batch_size=4,
    )

    global_state = [10, 25, 1, 8, 20, 1]
    observations = [
        [10, 25, 1],
        [8, 20, 1],
    ]

    next_global_state = [12, 20, 1, 10, 18, 1]
    next_observations = [
        [12, 20, 1],
        [10, 18, 1],
    ]

    for i in range(20):
        actions = agent.select_actions(observations)
        reward = -100.0
        done = False

        agent.store_transition(
            global_state=global_state,
            observations=observations,
            actions=actions,
            reward=reward,
            next_global_state=next_global_state,
            next_observations=next_observations,
            done=done,
        )

        loss = agent.learn()

        print(
            f"Step {i} | "
            f"Actions: {actions} | "
            f"Epsilon: {agent.epsilon:.3f} | "
            f"Loss: {loss}"
        )


if __name__ == "__main__":
    main()