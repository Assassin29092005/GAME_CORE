"""
Constrained learning wrapper for Boss RL training.
Caps boss win rate, adds incompetence budget, rewards engaging fights,
and modulates behavior based on estimated player emotional state.
"""

from collections import deque

import gymnasium as gym
import numpy as np

from boss_env import BossEnv


class ConstrainedBossEnv(gym.Wrapper):
    """
    Wraps BossEnv with:
    1. Win rate tracking and dynamic incompetence (epsilon)
    2. Engagement reward shaping (HP lead changes, close fights)
    3. Boss win rate cap via action noise
    4. Emotion-aware adaptation (Extension 10):
       - Frustrated player → boss becomes easier (epsilon boost + reduced damage reward)
       - Bored player → boss becomes harder (epsilon reduction + aggression bonus)
       - Flow state → maintain current difficulty (stability bonus)

    When the boss wins too often, epsilon increases — the boss occasionally
    replaces its optimal action with a suboptimal one, keeping fights fair.
    """

    def __init__(
        self,
        env: gym.Env,
        target_win_rate: float = 0.45,
        win_rate_window: int = 100,
        max_epsilon: float = 0.3,
        lead_change_bonus: float = 0.5,
        close_fight_bonus: float = 0.1,
        close_fight_threshold: float = 0.2,
        # Extension 10: Emotion-aware parameters
        emotion_enabled: bool = False,
        emotion_obs_start: int = -1,
        frustration_epsilon_boost: float = 0.15,
        frustration_reward_scale: float = 0.5,
        boredom_aggression_bonus: float = 0.3,
        flow_maintenance_bonus: float = 0.2,
    ):
        super().__init__(env)

        self.target_win_rate = target_win_rate
        self.max_epsilon = max_epsilon
        self.lead_change_bonus = lead_change_bonus
        self.close_fight_bonus = close_fight_bonus
        self.close_fight_threshold = close_fight_threshold

        self.win_history: deque[float] = deque(maxlen=win_rate_window)
        self.current_epsilon = 0.0
        self._base_epsilon = 0.0  # epsilon before emotion modulation

        # Per-episode tracking for engagement metrics
        self._prev_hp_leader: str | None = None
        self._hp_lead_changes = 0

        # Extension 10: Emotion tracking
        self._emotion_enabled = emotion_enabled
        self._emotion_obs_start = emotion_obs_start
        self._frustration_epsilon_boost = frustration_epsilon_boost
        self._frustration_reward_scale = frustration_reward_scale
        self._boredom_aggression_bonus = boredom_aggression_bonus
        self._flow_maintenance_bonus = flow_maintenance_bonus

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self._prev_hp_leader = None
        self._hp_lead_changes = 0
        return obs, info

    def step(self, action):
        # Dynamic incompetence: sometimes replace optimal action
        effective_epsilon = self.current_epsilon
        if np.random.random() < effective_epsilon:
            action = self._suboptimal_action(int(action))

        obs, reward, terminated, truncated, info = self.env.step(action)

        # Add engagement reward
        reward += self._engagement_reward(obs)

        # Extension 10: Emotion-aware reward modulation
        if self._emotion_enabled:
            reward = self._emotion_modulate_reward(obs, reward, action)

        # Track win/loss on episode end
        if terminated:
            boss_hp = obs[BossEnv.IDX_BOSS_HP]
            hero_hp = obs[BossEnv.IDX_HERO_HP]
            boss_won = hero_hp <= 0.0 and boss_hp > 0.0
            self.win_history.append(1.0 if boss_won else 0.0)
            self._update_epsilon()

            # Apply emotion modulation to epsilon
            if self._emotion_enabled:
                self._emotion_modulate_epsilon(obs)

            # Add info for logging
            info["boss_won"] = boss_won
            info["win_rate"] = self.get_win_rate()
            info["epsilon"] = self.current_epsilon
            info["hp_lead_changes"] = self._hp_lead_changes

            if self._emotion_enabled:
                frustration, flow, boredom = self._get_emotion_scores(obs)
                info["frustration"] = frustration
                info["flow"] = flow
                info["boredom"] = boredom

        return obs, reward, terminated, truncated, info

    def _suboptimal_action(self, optimal_action: int) -> int:
        """Replace optimal action with a contextually reasonable but weaker one."""
        alternatives = [a for a in range(self.action_space.n) if a != optimal_action]
        return int(np.random.choice(alternatives))

    def _engagement_reward(self, obs: np.ndarray) -> float:
        """Reward back-and-forth fights with HP lead swings."""
        boss_hp = obs[BossEnv.IDX_BOSS_HP]
        hero_hp = obs[BossEnv.IDX_HERO_HP]

        bonus = 0.0

        # Track HP lead changes
        current_leader = "boss" if boss_hp > hero_hp else "hero"
        if self._prev_hp_leader is not None and current_leader != self._prev_hp_leader:
            self._hp_lead_changes += 1
            bonus += self.lead_change_bonus
        self._prev_hp_leader = current_leader

        # Bonus for close fights (both HPs within threshold of each other)
        hp_diff = abs(boss_hp - hero_hp)
        if hp_diff < self.close_fight_threshold:
            bonus += self.close_fight_bonus

        return bonus

    def _update_epsilon(self):
        """Adjust incompetence probability based on rolling win rate."""
        if len(self.win_history) < 10:
            self._base_epsilon = 0.0
            self.current_epsilon = 0.0
            return

        win_rate = float(np.mean(self.win_history))

        if win_rate > self.target_win_rate + 0.05:
            # Too dominant — increase incompetence
            excess = win_rate - self.target_win_rate
            self._base_epsilon = min(self.max_epsilon, excess * 2.0)
        else:
            # Slowly reduce incompetence
            self._base_epsilon = max(0.0, self._base_epsilon - 0.01)

        self.current_epsilon = self._base_epsilon

    # --- Extension 10: Emotion-Aware Modulation ---

    def _get_emotion_scores(self, obs: np.ndarray) -> tuple[float, float, float]:
        """Extract emotion scores from observation vector."""
        if not self._emotion_enabled or self._emotion_obs_start < 0:
            return 0.0, 0.0, 0.0

        idx = self._emotion_obs_start
        if idx + 2 >= len(obs):
            return 0.0, 0.0, 0.0

        frustration = float(obs[idx])
        flow = float(obs[idx + 1])
        boredom = float(obs[idx + 2])
        return frustration, flow, boredom

    def _emotion_modulate_epsilon(self, obs: np.ndarray):
        """
        Modulate incompetence epsilon based on player emotional state.
        - Frustrated → boost epsilon (easier boss, gives breathing room)
        - Bored → reduce epsilon to near 0 (harder boss, more challenging)
        - Flow → maintain current epsilon (optimal difficulty)
        """
        frustration, flow, boredom = self._get_emotion_scores(obs)

        epsilon = self._base_epsilon

        if frustration > 0.6:
            # Player is frustrated — make boss easier
            epsilon += self._frustration_epsilon_boost * (frustration - 0.3)
            epsilon = min(epsilon, self.max_epsilon + self._frustration_epsilon_boost)

        if boredom > 0.6:
            # Player is bored — make boss harder (reduce incompetence)
            boredom_reduction = self._boredom_aggression_bonus * (boredom - 0.3)
            epsilon = max(0.0, epsilon - boredom_reduction)

        # Flow: maintain current epsilon (no change)

        self.current_epsilon = max(0.0, min(1.0, epsilon))

    def _emotion_modulate_reward(
        self, obs: np.ndarray, reward: float, action: int
    ) -> float:
        """
        Modulate reward based on player emotional state.
        - Frustrated → scale down damage reward (boss less rewarded for hurting player)
        - Bored → bonus for aggressive/varied play (boss rewarded for exciting behavior)
        - Flow → small stability bonus (reward maintaining current difficulty)
        """
        frustration, flow, boredom = self._get_emotion_scores(obs)

        if frustration > 0.6:
            # Scale down positive reward from dealing damage
            if reward > 0:
                reward *= self._frustration_reward_scale
            # Small bonus for non-aggressive actions (give player breathing room)
            if action in (1, 2, 4):  # Block, Dodge, Retreat
                reward += 0.05

        if boredom > 0.6:
            # Bonus for aggressive, engaging actions
            if action == 0:  # Attack
                reward += self._boredom_aggression_bonus * (boredom - 0.3)
            # Penalty for passive actions when player is bored
            if action == 4:  # Retreat
                reward -= 0.1

        if flow > 0.6:
            # Small bonus for maintaining the current engagement level
            reward += self._flow_maintenance_bonus * 0.5

        return reward

    def get_win_rate(self) -> float:
        """Get current rolling win rate."""
        if len(self.win_history) == 0:
            return 0.0
        return float(np.mean(self.win_history))

    def get_epsilon(self) -> float:
        """Get current incompetence probability."""
        return self.current_epsilon
