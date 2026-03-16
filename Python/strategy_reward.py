"""
Per-strategy reward shaping functions for hierarchical RL.
Each strategy archetype gets bonus/penalty based on action alignment.
"""

import numpy as np

from boss_env import BossEnv

# Action indices
ACTION_ATTACK = 0
ACTION_BLOCK = 1
ACTION_DODGE = 2
ACTION_APPROACH = 3
ACTION_RETREAT = 4


def aggressive_rush_reward(obs: np.ndarray, action: int, prev_obs: np.ndarray) -> float:
    """
    Strategy 0: Aggressive Rush
    - Bonus for attacking when close
    - Bonus for closing distance
    - Penalty for retreating or staying far
    """
    distance = obs[BossEnv.IDX_DISTANCE]
    prev_distance = prev_obs[BossEnv.IDX_DISTANCE]
    hero_hp = obs[BossEnv.IDX_HERO_HP]
    prev_hero_hp = prev_obs[BossEnv.IDX_HERO_HP]

    bonus = 0.0

    # Reward closing distance
    distance_delta = prev_distance - distance
    if distance_delta > 0:
        bonus += distance_delta * 0.3

    # Reward attacking at close range
    if action == ACTION_ATTACK and distance < 0.3:
        bonus += 0.2

    # Extra reward for damage dealt
    hero_damage = prev_hero_hp - hero_hp
    if hero_damage > 0:
        bonus += hero_damage * 2.0

    # Penalty for retreating
    if action == ACTION_RETREAT:
        bonus -= 0.15

    return bonus


def defensive_attrition_reward(obs: np.ndarray, action: int, prev_obs: np.ndarray) -> float:
    """
    Strategy 1: Defensive Attrition
    - Bonus for blocking/dodging
    - Bonus for HP preservation
    - Penalty for taking damage recklessly
    """
    boss_hp = obs[BossEnv.IDX_BOSS_HP]
    prev_boss_hp = prev_obs[BossEnv.IDX_BOSS_HP]

    bonus = 0.0

    # Reward blocking and dodging
    if action == ACTION_BLOCK:
        bonus += 0.15
    if action == ACTION_DODGE:
        bonus += 0.1

    # Extra reward for not taking damage
    boss_damage = prev_boss_hp - boss_hp
    if boss_damage <= 0:
        bonus += 0.05  # survived this step undamaged
    else:
        bonus -= boss_damage * 1.0  # penalty for damage taken

    # Reward maintaining medium distance (safe spacing)
    distance = obs[BossEnv.IDX_DISTANCE]
    optimal = 0.4
    bonus -= abs(distance - optimal) * 0.1

    return bonus


def hit_and_run_reward(obs: np.ndarray, action: int, prev_obs: np.ndarray,
                       action_history: list[int] | None = None) -> float:
    """
    Strategy 2: Hit-and-Run
    - Bonus for alternating attack->retreat->approach->attack patterns
    - Bonus for attacking then immediately creating distance
    """
    bonus = 0.0

    if action_history and len(action_history) >= 2:
        prev_action = action_history[-1]

        # Attack followed by retreat = hit-and-run pattern
        if prev_action == ACTION_ATTACK and action == ACTION_RETREAT:
            bonus += 0.3

        # Retreat followed by approach = repositioning
        if prev_action == ACTION_RETREAT and action == ACTION_APPROACH:
            bonus += 0.15

        # Approach followed by attack = closing strike
        if prev_action == ACTION_APPROACH and action == ACTION_ATTACK:
            bonus += 0.2

    # Reward damaging hero
    hero_hp = obs[BossEnv.IDX_HERO_HP]
    prev_hero_hp = prev_obs[BossEnv.IDX_HERO_HP]
    hero_damage = prev_hero_hp - hero_hp
    if hero_damage > 0:
        bonus += hero_damage * 1.5

    return bonus


def counter_focused_reward(obs: np.ndarray, action: int, prev_obs: np.ndarray,
                           action_history: list[int] | None = None) -> float:
    """
    Strategy 3: Counter-Focused
    - Bonus for block->attack sequences (parry counter)
    - Bonus for dodging then immediately attacking
    - Reads opponent state to reward reactive play
    """
    bonus = 0.0

    if action_history and len(action_history) >= 1:
        prev_action = action_history[-1]

        # Block followed by attack = counter-attack
        if prev_action == ACTION_BLOCK and action == ACTION_ATTACK:
            bonus += 0.4

        # Dodge followed by attack = dodge counter
        if prev_action == ACTION_DODGE and action == ACTION_ATTACK:
            bonus += 0.35

    # Bonus for blocking while hero is attacking
    hero_attacking = obs[4] > 0.5  # hero_attacking index
    if action == ACTION_BLOCK and hero_attacking:
        bonus += 0.2

    # Bonus for dodging while hero is attacking
    if action == ACTION_DODGE and hero_attacking:
        bonus += 0.15

    return bonus


# Strategy function registry
STRATEGY_FUNCTIONS = {
    0: aggressive_rush_reward,
    1: defensive_attrition_reward,
    2: hit_and_run_reward,
    3: counter_focused_reward,
}

STRATEGY_NAMES = {
    0: "Aggressive Rush",
    1: "Defensive Attrition",
    2: "Hit-and-Run",
    3: "Counter-Focused",
}


def compute_strategy_reward(strategy_id: int, obs: np.ndarray, action: int,
                             prev_obs: np.ndarray,
                             action_history: list[int] | None = None,
                             emotion_scores: tuple[float, float, float] | None = None) -> float:
    """
    Compute strategy-specific reward shaping bonus.

    Args:
        strategy_id: Which strategy archetype (0-3)
        obs: Current observation
        action: Boss action taken
        prev_obs: Previous observation
        action_history: Recent action history for pattern detection
        emotion_scores: (frustration, flow, boredom) from Extension 10
    """
    func = STRATEGY_FUNCTIONS.get(strategy_id)
    if func is None:
        return 0.0

    # Functions that accept action_history
    if strategy_id in (2, 3):
        base_reward = func(obs, action, prev_obs, action_history=action_history)
    else:
        base_reward = func(obs, action, prev_obs)

    # Extension 10: Emotion-aware strategy modulation
    if emotion_scores is not None:
        base_reward += emotion_modulate_strategy_reward(
            strategy_id, emotion_scores
        )

    return base_reward


def emotion_modulate_strategy_reward(
    strategy_id: int,
    emotion_scores: tuple[float, float, float],
) -> float:
    """
    Modulate strategy selection reward based on player emotional state.

    When the player is frustrated, penalize aggressive strategies and
    reward defensive ones (give them breathing room).
    When the player is bored, reward aggressive/exciting strategies.

    Args:
        strategy_id: Current strategy (0-3)
        emotion_scores: (frustration, flow, boredom)

    Returns:
        Reward modifier for this strategy given the emotional context
    """
    frustration, flow, boredom = emotion_scores
    modifier = 0.0

    if frustration > 0.6:
        # Frustrated player: penalize aggressive, reward defensive
        if strategy_id == 0:  # Aggressive Rush
            modifier -= 0.2 * (frustration - 0.3)
        elif strategy_id == 1:  # Defensive Attrition
            modifier += 0.2 * (frustration - 0.3)
        elif strategy_id == 3:  # Counter-Focused (reactive, less punishing)
            modifier += 0.1 * (frustration - 0.3)

    if boredom > 0.6:
        # Bored player: reward exciting strategies
        if strategy_id == 0:  # Aggressive Rush
            modifier += 0.2 * (boredom - 0.3)
        elif strategy_id == 2:  # Hit-and-Run
            modifier += 0.15 * (boredom - 0.3)
        elif strategy_id == 1:  # Defensive Attrition (boring to fight against)
            modifier -= 0.15 * (boredom - 0.3)

    if flow > 0.6:
        # Flow state: small bonus for maintaining current strategy (stability)
        modifier += 0.05

    return modifier
