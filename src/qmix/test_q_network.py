import torch
from q_network import AgentQNetwork


def main():
    net = AgentQNetwork(obs_dim=3, action_dim=2)

    # Example local observation:
    # side queue = 10, main queue = 25, current green = main
    obs = torch.tensor([[10.0, 25.0, 1.0]])

    q_values = net(obs)

    print("Observation:", obs)
    print("Q-values:", q_values)
    print("Best action:", torch.argmax(q_values, dim=1).item())


if __name__ == "__main__":
    main()