from dqn_agent import DQNAgent


def main():
    agent = DQNAgent(state_dim=3, action_dim=2, batch_size=4)

    state = [10, 5, 0]
    next_state = [8, 7, 1]

    for i in range(20):
        action = agent.select_action(state)
        reward = -100
        done = False

        agent.store_transition(state, action, reward, next_state, done)

        loss = agent.learn()

        print(
            f"Step {i} | Action: {action} | "
            f"Epsilon: {agent.epsilon:.3f} | Loss: {loss}"
        )


if __name__ == "__main__":
    main()