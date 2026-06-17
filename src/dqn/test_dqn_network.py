import torch
from dqn_network import DQNNetwork


def main():
    model = DQNNetwork(state_dim=3, action_dim=2)

    # Example state:
    # queue phase 0 = 10 vehicles
    # queue phase 3 = 5 vehicles
    # current green = phase 0
    state = torch.tensor([[10.0, 5.0, 0.0]])

    q_values = model(state)

    print("Input state:", state)
    print("Q-values:", q_values)
    print("Best action:", torch.argmax(q_values, dim=1).item())


if __name__ == "__main__":
    main()