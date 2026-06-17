from replay_buffer import QMIXReplayBuffer


def main():
    buffer = QMIXReplayBuffer(capacity=10)

    for i in range(15):
        global_state = [i, i + 1, 1, i + 2, i + 3, 1]

        observations = [
            [i, i + 1, 1],      # J1 observation
            [i + 2, i + 3, 1],  # J2 observation
        ]

        actions = [i % 2, (i + 1) % 2]

        reward = -100.0 - i

        next_global_state = [i + 1, i + 2, 1, i + 3, i + 4, 1]

        next_observations = [
            [i + 1, i + 2, 1],
            [i + 3, i + 4, 1],
        ]

        done = False

        buffer.push(
            global_state,
            observations,
            actions,
            reward,
            next_global_state,
            next_observations,
            done,
        )

    print("Buffer size:", len(buffer))

    batch = buffer.sample(batch_size=4)

    names = [
        "global_states",
        "observations",
        "actions",
        "rewards",
        "next_global_states",
        "next_observations",
        "dones",
    ]

    for name, value in zip(names, batch):
        print(f"\n{name}:")
        print(value)
        print("shape:", value.shape)


if __name__ == "__main__":
    main()