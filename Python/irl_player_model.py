"""
Maximum Entropy Inverse Reinforcement Learning for player modeling.
Recovers a player's implicit reward function from observed (state, action) trajectories.

Reference: Ziebart et al., "Maximum Entropy Inverse Reinforcement Learning", AAAI 2008

Usage:
    irl = MaxEntIRL(feature_dim=20, num_actions=5)
    irl.train(player_trajectories)
    action_probs = irl.predict_action_distribution(obs)
    weights = irl.get_reward_weights()
"""

import os
from pathlib import Path

import numpy as np

from irl_feature_engineering import (
    FEATURE_DIM,
    batch_obs_to_features,
    obs_to_irl_features,
)


class MaxEntIRL:
    """
    Maximum Entropy IRL with linear reward approximation.

    Learns reward weights theta such that R(s) = theta^T * phi(s),
    where phi(s) is the feature vector. The learned reward explains
    the player's observed behavior under the maximum entropy principle.

    The key insight: instead of just knowing a player attacks a lot (EMA profile),
    IRL recovers *why* — e.g., they value close-range HP advantage and
    penalize retreating. This enables predicting behavior in novel situations.
    """

    def __init__(
        self,
        feature_dim: int = FEATURE_DIM,
        num_actions: int = 5,
        learning_rate: float = 0.01,
        n_iterations: int = 200,
        discount: float = 0.99,
    ):
        self.feature_dim = feature_dim
        self.num_actions = num_actions
        self.learning_rate = learning_rate
        self.n_iterations = n_iterations
        self.discount = discount

        # Learned reward weights
        self.theta = np.zeros(feature_dim, dtype=np.float64)

        # Transition model learned from data (state-action -> next state features)
        self._transition_features: dict[int, np.ndarray] | None = None
        self._state_action_counts: np.ndarray | None = None

    def train(self, trajectories: list[list[tuple]], verbose: bool = True):
        """
        Train IRL on player trajectories.

        Args:
            trajectories: List of episodes, each a list of (feature_vector, action) tuples
            verbose: Print training progress
        """
        if not trajectories:
            raise ValueError("No trajectories provided for IRL training")

        # Compute expert feature expectations (what the player actually does)
        expert_fe = self._compute_feature_expectations(trajectories)

        # Build empirical transition model from trajectory data
        self._build_transition_model(trajectories)

        # Gradient descent on theta
        for iteration in range(self.n_iterations):
            # Compute learner feature expectations under current reward
            learner_fe = self._compute_learner_feature_expectations(trajectories)

            # MaxEntIRL gradient: expert - learner
            gradient = expert_fe - learner_fe

            # Update theta
            self.theta += self.learning_rate * gradient

            if verbose and (iteration + 1) % 50 == 0:
                grad_norm = np.linalg.norm(gradient)
                print(f"  IRL iteration {iteration + 1}/{self.n_iterations}, "
                      f"gradient norm: {grad_norm:.6f}")

        if verbose:
            print(f"  IRL training complete. Top reward features:")
            top_indices = np.argsort(np.abs(self.theta))[::-1][:5]
            feature_names = _get_feature_names()
            for idx in top_indices:
                name = feature_names[idx] if idx < len(feature_names) else f"feature_{idx}"
                print(f"    {name}: {self.theta[idx]:+.4f}")

    def predict_action_distribution(self, obs: np.ndarray) -> np.ndarray:
        """
        Predict the player's action probability distribution for a given state.

        Uses the learned reward and a soft Q-value approximation:
        P(a|s) = exp(Q(s,a)) / sum_a' exp(Q(s,a'))

        Args:
            obs: Raw 17-dim observation from boss_env

        Returns:
            Array of shape (num_actions,) with P(a|s) for each action
        """
        features = obs_to_irl_features(obs)
        reward = np.dot(self.theta, features)

        # Compute Q-values via 1-step lookahead with transition model
        q_values = np.zeros(self.num_actions, dtype=np.float64)

        if self._transition_features is not None:
            for a in range(self.num_actions):
                if a in self._transition_features:
                    next_features = self._transition_features[a]
                    next_reward = np.dot(self.theta, next_features)
                    q_values[a] = reward + self.discount * next_reward
                else:
                    q_values[a] = reward
        else:
            # Fallback: use current reward as Q-value (no transition model)
            q_values[:] = reward

        # Softmax for MaxEnt policy
        q_values -= np.max(q_values)  # numerical stability
        exp_q = np.exp(q_values)
        action_probs = exp_q / (exp_q.sum() + 1e-10)

        return action_probs.astype(np.float32)

    def get_reward_weights(self) -> np.ndarray:
        """Return the learned reward weight vector."""
        return self.theta.copy()

    def get_reward(self, obs: np.ndarray) -> float:
        """Compute the learned reward for a given observation."""
        features = obs_to_irl_features(obs)
        return float(np.dot(self.theta, features))

    def save(self, path: str):
        """Save IRL model to disk."""
        save_dir = Path(path)
        save_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            save_dir / "irl_model.npz",
            theta=self.theta,
            feature_dim=self.feature_dim,
            num_actions=self.num_actions,
        )
        if self._transition_features is not None:
            trans_data = {}
            for a, feat in self._transition_features.items():
                trans_data[f"trans_{a}"] = feat
            np.savez(save_dir / "irl_transitions.npz", **trans_data)

    @classmethod
    def load(cls, path: str) -> "MaxEntIRL":
        """Load IRL model from disk."""
        save_dir = Path(path)
        data = np.load(save_dir / "irl_model.npz")
        irl = cls(
            feature_dim=int(data["feature_dim"]),
            num_actions=int(data["num_actions"]),
        )
        irl.theta = data["theta"]

        trans_path = save_dir / "irl_transitions.npz"
        if trans_path.exists():
            trans_data = np.load(trans_path)
            irl._transition_features = {}
            for key in trans_data:
                action_idx = int(key.split("_")[1])
                irl._transition_features[action_idx] = trans_data[key]

        return irl

    # --- Internal Methods ---

    def _compute_feature_expectations(
        self, trajectories: list[list[tuple]]
    ) -> np.ndarray:
        """
        Compute average feature vector across all (state, action) pairs.
        This is the "expert" feature expectation mu_E.
        """
        total_features = np.zeros(self.feature_dim, dtype=np.float64)
        total_steps = 0

        for trajectory in trajectories:
            discount_factor = 1.0
            for features, action in trajectory:
                total_features += discount_factor * features
                discount_factor *= self.discount
                total_steps += 1

        if total_steps > 0:
            total_features /= len(trajectories)

        return total_features

    def _build_transition_model(self, trajectories: list[list[tuple]]):
        """
        Build a simple empirical transition model from trajectory data.
        For each action, compute the average next-state feature vector.
        """
        action_next_features = {a: [] for a in range(self.num_actions)}

        for trajectory in trajectories:
            for i in range(len(trajectory) - 1):
                features_t, action_t = trajectory[i]
                features_t1, _ = trajectory[i + 1]
                action_next_features[action_t].append(features_t1)

        self._transition_features = {}
        for a in range(self.num_actions):
            if action_next_features[a]:
                self._transition_features[a] = np.mean(
                    action_next_features[a], axis=0
                ).astype(np.float64)

    def _compute_learner_feature_expectations(
        self, trajectories: list[list[tuple]]
    ) -> np.ndarray:
        """
        Compute expected feature counts under the current reward (MaxEnt policy).
        Uses the soft value iteration approach on the empirical state visitation.
        """
        total_features = np.zeros(self.feature_dim, dtype=np.float64)

        for trajectory in trajectories:
            discount_factor = 1.0
            for features, _ in trajectory:
                # Compute MaxEnt action distribution at this state
                reward = np.dot(self.theta, features)
                q_values = np.zeros(self.num_actions, dtype=np.float64)

                if self._transition_features is not None:
                    for a in range(self.num_actions):
                        if a in self._transition_features:
                            next_r = np.dot(
                                self.theta, self._transition_features[a]
                            )
                            q_values[a] = reward + self.discount * next_r
                        else:
                            q_values[a] = reward
                else:
                    q_values[:] = reward

                q_values -= np.max(q_values)
                exp_q = np.exp(q_values)
                policy = exp_q / (exp_q.sum() + 1e-10)

                # Weight features by state visitation (uniform in MaxEnt)
                total_features += discount_factor * features
                discount_factor *= self.discount

        if trajectories:
            total_features /= len(trajectories)

        return total_features


def _get_feature_names() -> list[str]:
    """Return human-readable feature names for logging."""
    return [
        "hero_hp", "boss_hp", "distance", "angle",
        "hero_attacking", "hero_combo", "hero_speed",
        "hp_difference", "is_close", "is_mid", "is_far",
        "hero_low_hp", "boss_low_hp", "attacking_close",
        "retreating", "hp_advantage",
        "aggression_profile", "dodge_profile",
        "kiting_profile", "pressure_profile",
    ]
