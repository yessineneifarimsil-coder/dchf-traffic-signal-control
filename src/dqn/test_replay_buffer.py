from replay_buffer import ReplayBuffer


buffer = ReplayBuffer(capacity=10)

for i in range(15):
    state = [i, i + 1, 0]
    action = i % 2
    reward = -i
    next_state = [i + 1, i + 2, 1]
    done = False

    buffer.push(state, action, reward, next_state, done)

print("Buffer size:", len(buffer))

states, actions, rewards, next_states, dones = buffer.sample(batch_size=4)

print("States:")
print(states)

print("Actions:")
print(actions)

print("Rewards:")
print(rewards)

print("Next states:")
print(next_states)

print("Dones:")
print(dones)