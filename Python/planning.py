"""
Boss AI planning module using world model + IRL player prediction.
Enables 1-2 step lookahead so the boss can evaluate consequences
before selecting actions.

Novel: no prior work applies learned world models to boss AI planning
in real-time action combat games.
"""

import numpy as np
import torch


class BossPlanner:
    """
    Plans boss actions using lookahead with a learned world model.

    For each candidate boss action:
      1. Predict player's likely response via IRL model
      2. Predict next state via world model
      3. Evaluate next state (value function or recursive lookahead)
      4. Select boss action with highest expected value

    This transforms the boss from purely reactive (model-free RL) to
    deliberative (model-based planning), enabling anticipatory behavior
    like feinting and reading player patterns mid-combo.
    """

    def __init__(
        self,
        world_model,
        irl_model=None,
        value_function=None,
        lookahead_depth: int = 2,
        num_boss_actions: int = 5,
        num_player_actions: int = 6,
        top_k_player_actions: int = 2,
        discount: float = 0.99,
    ):
        """
        Args:
            world_model: Trained WorldModel instance
            irl_model: Trained MaxEntIRL for predicting player actions (optional)
            value_function: Callable obs -> value estimate (optional, e.g., PPO critic)
            lookahead_depth: How many steps to plan ahead (1 or 2)
            num_boss_actions: Number of available boss actions
            num_player_actions: Number of possible player actions (including idle)
            top_k_player_actions: Consider top-K most likely player actions per step
            discount: Discount factor for future rewards
        """
        self.world_model = world_model
        self.irl_model = irl_model
        self.value_function = value_function
        self.lookahead_depth = lookahead_depth
        self.num_boss_actions = num_boss_actions
        self.num_player_actions = num_player_actions
        self.top_k = top_k_player_actions
        self.discount = discount

    def plan(self, obs: np.ndarray) -> int:
        """
        Select the best boss action via lookahead planning.

        Args:
            obs: Current observation (base 17-dim, not augmented)

        Returns:
            Best boss action index (0-4)
        """
        best_action = 0
        best_value = float("-inf")

        for boss_action in range(self.num_boss_actions):
            value = self.evaluate_action(obs, boss_action, depth=self.lookahead_depth)
            if value > best_value:
                best_value = value
                best_action = boss_action

        return best_action

    def evaluate_action(
        self, obs: np.ndarray, boss_action: int, depth: int
    ) -> float:
        """
        Recursively evaluate a boss action via world model simulation.

        At each step:
        1. Get player action distribution from IRL (or uniform)
        2. For top-K likely player actions, predict next state via world model
        3. Weight by player action probability
        4. Either recurse (depth > 1) or estimate terminal value

        Args:
            obs: Current observation
            boss_action: Boss action to evaluate
            depth: Remaining lookahead steps

        Returns:
            Expected value of taking this action
        """
        # Get player action probabilities
        player_probs = self._get_player_action_probs(obs)

        # Select top-K player actions by probability
        top_actions, top_probs = self._get_top_k_actions(player_probs)

        # Renormalize top-K probabilities
        prob_sum = np.sum(top_probs)
        if prob_sum > 0:
            top_probs = top_probs / prob_sum

        expected_value = 0.0

        for player_action, prob in zip(top_actions, top_probs):
            # Predict next state and immediate reward
            next_obs, immediate_reward = self.world_model.predict(
                obs, boss_action, player_action
            )

            # Compute future value
            if depth > 1:
                # Recursive lookahead: try all boss actions at the next state
                future_value = float("-inf")
                for next_boss_action in range(self.num_boss_actions):
                    v = self.evaluate_action(next_obs, next_boss_action, depth - 1)
                    future_value = max(future_value, v)
            else:
                # Terminal: use value function or zero
                future_value = self._estimate_value(next_obs)

            total_value = immediate_reward + self.discount * future_value
            expected_value += prob * total_value

        return expected_value

    def plan_with_info(self, obs: np.ndarray) -> dict:
        """
        Plan with detailed debug information.

        Returns:
            Dict with 'action', 'values' (per action), 'player_probs',
            and 'best_value'.
        """
        action_values = {}
        player_probs = self._get_player_action_probs(obs)

        for boss_action in range(self.num_boss_actions):
            action_values[boss_action] = self.evaluate_action(
                obs, boss_action, depth=self.lookahead_depth
            )

        best_action = max(action_values, key=action_values.get)

        return {
            "action": best_action,
            "values": action_values,
            "player_probs": player_probs.tolist(),
            "best_value": action_values[best_action],
        }

    def _get_player_action_probs(self, obs: np.ndarray) -> np.ndarray:
        """Get predicted player action distribution."""
        if self.irl_model is not None:
            # IRL model predicts P(a|s) for 5 game actions
            probs = self.irl_model.predict_action_distribution(obs)
            # Extend to include idle action (index 5) with small probability
            full_probs = np.zeros(self.num_player_actions, dtype=np.float32)
            full_probs[:len(probs)] = probs * 0.95  # 95% for game actions
            full_probs[-1] = 0.05  # 5% idle
            return full_probs
        else:
            # Uniform distribution as fallback
            return np.ones(self.num_player_actions, dtype=np.float32) / self.num_player_actions

    def _get_top_k_actions(
        self, probs: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Select top-K actions by probability."""
        k = min(self.top_k, len(probs))
        top_indices = np.argsort(probs)[::-1][:k]
        return top_indices, probs[top_indices]

    def _estimate_value(self, obs: np.ndarray) -> float:
        """Estimate state value at leaf nodes of the planning tree."""
        if self.value_function is not None:
            return float(self.value_function(obs))

        # Simple heuristic: boss HP advantage over hero
        # obs[5] = hero_hp, obs[8] = boss_hp
        if len(obs) > 8:
            boss_hp = obs[8]
            hero_hp = obs[5]
            return (boss_hp - hero_hp) * 10.0

        return 0.0
