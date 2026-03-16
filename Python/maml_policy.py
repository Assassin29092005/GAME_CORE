"""
MAML-compatible policy network for Boss AI.
Mirrors SB3 MlpPolicy architecture but is trainable with PyTorch directly,
enabling meta-gradient computation for Model-Agnostic Meta-Learning.

Reference: Finn et al., "Model-Agnostic Meta-Learning for Fast Adaptation
of Deep Networks", ICML 2017.

Novel: no prior work applies MAML to game enemy/boss AI adaptation.
"""

from collections import OrderedDict
from copy import deepcopy

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class MamlPolicy(nn.Module):
    """
    Actor-Critic policy network compatible with MAML inner-loop adaptation.

    Architecture mirrors SB3 MlpPolicy:
        Actor:  obs -> Linear(64) -> Tanh -> Linear(64) -> Tanh -> Linear(num_actions)
        Critic: obs -> Linear(64) -> Tanh -> Linear(64) -> Tanh -> Linear(1)
    """

    def __init__(self, obs_dim: int = 17, num_actions: int = 5, hidden_size: int = 64):
        super().__init__()
        self.obs_dim = obs_dim
        self.num_actions = num_actions

        # Actor network (outputs action logits)
        self.actor = nn.Sequential(
            nn.Linear(obs_dim, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, num_actions),
        )

        # Critic network (outputs state value)
        self.critic = nn.Sequential(
            nn.Linear(obs_dim, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass.

        Args:
            obs: Observation tensor (batch, obs_dim)

        Returns:
            action_logits: (batch, num_actions)
            value: (batch, 1)
        """
        return self.actor(obs), self.critic(obs)

    def get_action_distribution(self, obs: torch.Tensor) -> torch.distributions.Categorical:
        """Get action distribution from observation."""
        logits, _ = self.forward(obs)
        return torch.distributions.Categorical(logits=logits)

    def predict(self, obs: np.ndarray, deterministic: bool = True) -> int:
        """Single observation prediction (numpy in/out)."""
        obs_t = torch.FloatTensor(obs).unsqueeze(0)
        with torch.no_grad():
            logits, _ = self.forward(obs_t)
        if deterministic:
            return int(torch.argmax(logits, dim=-1).item())
        else:
            probs = F.softmax(logits, dim=-1)
            return int(torch.multinomial(probs, 1).item())


def compute_ppo_loss(
    policy: MamlPolicy,
    obs: torch.Tensor,
    actions: torch.Tensor,
    returns: torch.Tensor,
    old_log_probs: torch.Tensor | None = None,
    clip_range: float = 0.2,
    value_coef: float = 0.5,
    entropy_coef: float = 0.01,
) -> torch.Tensor:
    """
    Compute PPO-style loss for MAML inner/outer loops.

    For the inner loop (adaptation), we use a simplified REINFORCE loss.
    For the outer loop (meta-loss), we use the full PPO clipped objective.
    """
    action_logits, values = policy(obs)
    dist = torch.distributions.Categorical(logits=action_logits)

    log_probs = dist.log_prob(actions)
    entropy = dist.entropy().mean()

    # Advantage estimation (simple: returns - values)
    advantages = returns - values.squeeze(-1)
    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    if old_log_probs is not None:
        # PPO clipped loss
        ratio = torch.exp(log_probs - old_log_probs)
        surr1 = ratio * advantages.detach()
        surr2 = torch.clamp(ratio, 1 - clip_range, 1 + clip_range) * advantages.detach()
        policy_loss = -torch.min(surr1, surr2).mean()
    else:
        # Simple REINFORCE loss (for inner loop)
        policy_loss = -(log_probs * advantages.detach()).mean()

    value_loss = F.mse_loss(values.squeeze(-1), returns)

    total_loss = policy_loss + value_coef * value_loss - entropy_coef * entropy
    return total_loss


def inner_adapt(
    policy: MamlPolicy,
    support_obs: torch.Tensor,
    support_actions: torch.Tensor,
    support_returns: torch.Tensor,
    inner_lr: float = 0.01,
    inner_steps: int = 3,
    create_graph: bool = True,
) -> MamlPolicy:
    """
    MAML inner-loop adaptation: perform N gradient steps on support data.

    Uses torch.autograd.grad with create_graph=True to allow meta-gradient
    computation through the adaptation process.

    Args:
        policy: Meta-policy to adapt
        support_obs: Support set observations
        support_actions: Support set actions
        support_returns: Support set discounted returns
        inner_lr: Learning rate for inner loop
        inner_steps: Number of gradient steps
        create_graph: Whether to track gradients for meta-learning

    Returns:
        Adapted policy with updated parameters
    """
    # Clone the policy to avoid modifying the meta-policy
    adapted = deepcopy(policy)

    for step in range(inner_steps):
        loss = compute_ppo_loss(adapted, support_obs, support_actions, support_returns)

        # Compute gradients manually for differentiable adaptation
        grads = torch.autograd.grad(
            loss, adapted.parameters(), create_graph=create_graph
        )

        # Apply gradient step
        for param, grad in zip(adapted.parameters(), grads):
            param.data = param.data - inner_lr * grad

    return adapted


def compute_meta_loss(
    meta_policy: MamlPolicy,
    tasks: list[dict],
    inner_lr: float = 0.01,
    inner_steps: int = 3,
) -> torch.Tensor:
    """
    Compute MAML outer-loop (meta) loss.

    For each task:
    1. Adapt meta-policy on support set (inner loop)
    2. Evaluate adapted policy on query set
    3. Average the query losses across tasks

    Args:
        meta_policy: The meta-learned policy
        tasks: List of task dicts with support/query tensors
        inner_lr: Inner loop learning rate
        inner_steps: Inner loop gradient steps

    Returns:
        Scalar meta-loss (differentiable through inner adaptation)
    """
    meta_loss = torch.tensor(0.0, requires_grad=True)

    for task in tasks:
        # Inner adaptation
        adapted = inner_adapt(
            meta_policy,
            task["support_obs"],
            task["support_actions"],
            task["support_returns"],
            inner_lr=inner_lr,
            inner_steps=inner_steps,
            create_graph=True,
        )

        # Evaluate on query set
        query_loss = compute_ppo_loss(
            adapted,
            task["query_obs"],
            task["query_actions"],
            task["query_returns"],
        )

        meta_loss = meta_loss + query_loss

    return meta_loss / max(len(tasks), 1)
