import torch
from mixing_network import MixingNetwork


def main():
    mixer = MixingNetwork(n_agents=2, state_dim=6)

    # Example individual Q-values:
    # agent J1 selected-action Q = 1.5
    # agent J2 selected-action Q = 2.0
    agent_qs = torch.tensor([[1.5, 2.0]])

    # Example global state:
    # [J1_side_q, J1_main_q, J1_phase, J2_side_q, J2_main_q, J2_phase]
    global_state = torch.tensor([[10.0, 25.0, 1.0, 8.0, 20.0, 1.0]])

    q_total = mixer(agent_qs, global_state)

    print("Agent Q-values:", agent_qs)
    print("Global state:", global_state)
    print("Mixed Q_total:", q_total)


if __name__ == "__main__":
    main()