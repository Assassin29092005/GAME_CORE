"""
Feature engineering for Inverse Reinforcement Learning player modeling.
Converts raw 17-dim observations into enriched feature vectors for MaxEntIRL.
"""

import numpy as np


# Raw observation indices (from boss_env.py)
IDX_HERO_VEL_X = 0
IDX_HERO_VEL_Y = 1
IDX_HERO_VEL_Z = 2
IDX_HERO_COMBO = 3
IDX_HERO_ATTACKING = 4
IDX_HERO_HP = 5
IDX_DISTANCE = 6
IDX_ANGLE = 7
IDX_BOSS_HP = 8
IDX_PROFILE_START = 9

# IRL feature indices
FEATURE_DIM = 20


def obs_to_irl_features(obs: np.ndarray) -> np.ndarray:
    """
    Convert a 17-dim raw observation to a ~20-dim IRL feature vector.

    The IRL feature vector includes the raw game state plus derived
    situational features that help a linear reward model capture
    meaningful player preferences.

    Features:
        0:  hero_hp
        1:  boss_hp
        2:  distance (normalized)
        3:  angle (normalized)
        4:  hero_attacking (binary)
        5:  hero_combo_step
        6:  hero_speed (magnitude of velocity)
        7:  hp_difference (hero_hp - boss_hp)
        8:  is_close_range (distance < 0.3)
        9:  is_mid_range (0.3 <= distance < 0.6)
        10: is_far_range (distance >= 0.6)
        11: is_hero_low_hp (hero_hp < 0.3)
        12: is_boss_low_hp (boss_hp < 0.3)
        13: is_attacking_close (attacking AND close range)
        14: is_retreating (inferred from velocity direction)
        15: hp_advantage (1 if hero > boss, else 0)
        16: aggression_profile (from player profile)
        17: dodge_tendency (from player profile)
        18: kiting_score (from player profile)
        19: pressure_response (from player profile)
    """
    features = np.zeros(FEATURE_DIM, dtype=np.float32)

    hero_hp = obs[IDX_HERO_HP]
    boss_hp = obs[IDX_BOSS_HP]
    distance = obs[IDX_DISTANCE]
    angle = obs[IDX_ANGLE]
    attacking = obs[IDX_HERO_ATTACKING]
    combo = obs[IDX_HERO_COMBO]
    vel_x, vel_y, vel_z = obs[IDX_HERO_VEL_X], obs[IDX_HERO_VEL_Y], obs[IDX_HERO_VEL_Z]
    speed = np.sqrt(vel_x**2 + vel_y**2 + vel_z**2)

    # Core state features
    features[0] = hero_hp
    features[1] = boss_hp
    features[2] = distance
    features[3] = angle
    features[4] = attacking
    features[5] = combo
    features[6] = speed

    # Derived situational features
    features[7] = hero_hp - boss_hp  # HP difference
    features[8] = 1.0 if distance < 0.3 else 0.0  # close range
    features[9] = 1.0 if 0.3 <= distance < 0.6 else 0.0  # mid range
    features[10] = 1.0 if distance >= 0.6 else 0.0  # far range
    features[11] = 1.0 if hero_hp < 0.3 else 0.0  # hero low HP
    features[12] = 1.0 if boss_hp < 0.3 else 0.0  # boss low HP
    features[13] = 1.0 if (attacking > 0.5 and distance < 0.3) else 0.0  # attacking close
    features[14] = 1.0 if (speed > 0.3 and angle > 0.5) else 0.0  # retreating
    features[15] = 1.0 if hero_hp > boss_hp else 0.0  # HP advantage

    # Player profile features (select the most informative)
    if len(obs) > IDX_PROFILE_START + 3:
        features[16] = obs[IDX_PROFILE_START + 0]  # aggression
        features[17] = obs[IDX_PROFILE_START + 1]  # dodge tendency
        features[18] = obs[IDX_PROFILE_START + 5]  # kiting score
        features[19] = obs[IDX_PROFILE_START + 4]  # pressure response

    return features


def trajectories_from_replays(replay_episodes: list[dict]) -> list[list[tuple]]:
    """
    Convert replay episode data (from ReplayBufferManager) into trajectory format
    for MaxEntIRL training.

    Args:
        replay_episodes: List of episode dicts with 'obs' and 'actions' arrays

    Returns:
        List of trajectories, each being a list of (feature_vector, action) tuples
    """
    trajectories = []

    for episode in replay_episodes:
        obs_arr = episode["obs"]
        actions_arr = episode["actions"]
        trajectory = []

        for i in range(len(actions_arr)):
            features = obs_to_irl_features(obs_arr[i])
            action = int(actions_arr[i])
            trajectory.append((features, action))

        if trajectory:
            trajectories.append(trajectory)

    return trajectories


def batch_obs_to_features(obs_batch: np.ndarray) -> np.ndarray:
    """Vectorized feature extraction for a batch of observations."""
    n = obs_batch.shape[0]
    features = np.zeros((n, FEATURE_DIM), dtype=np.float32)

    hero_hp = obs_batch[:, IDX_HERO_HP]
    boss_hp = obs_batch[:, IDX_BOSS_HP]
    distance = obs_batch[:, IDX_DISTANCE]
    angle = obs_batch[:, IDX_ANGLE]
    attacking = obs_batch[:, IDX_HERO_ATTACKING]
    combo = obs_batch[:, IDX_HERO_COMBO]
    speed = np.sqrt(
        obs_batch[:, IDX_HERO_VEL_X]**2 +
        obs_batch[:, IDX_HERO_VEL_Y]**2 +
        obs_batch[:, IDX_HERO_VEL_Z]**2
    )

    features[:, 0] = hero_hp
    features[:, 1] = boss_hp
    features[:, 2] = distance
    features[:, 3] = angle
    features[:, 4] = attacking
    features[:, 5] = combo
    features[:, 6] = speed
    features[:, 7] = hero_hp - boss_hp
    features[:, 8] = (distance < 0.3).astype(np.float32)
    features[:, 9] = ((distance >= 0.3) & (distance < 0.6)).astype(np.float32)
    features[:, 10] = (distance >= 0.6).astype(np.float32)
    features[:, 11] = (hero_hp < 0.3).astype(np.float32)
    features[:, 12] = (boss_hp < 0.3).astype(np.float32)
    features[:, 13] = ((attacking > 0.5) & (distance < 0.3)).astype(np.float32)
    features[:, 14] = ((speed > 0.3) & (angle > 0.5)).astype(np.float32)
    features[:, 15] = (hero_hp > boss_hp).astype(np.float32)

    if obs_batch.shape[1] > IDX_PROFILE_START + 5:
        features[:, 16] = obs_batch[:, IDX_PROFILE_START + 0]
        features[:, 17] = obs_batch[:, IDX_PROFILE_START + 1]
        features[:, 18] = obs_batch[:, IDX_PROFILE_START + 5]
        features[:, 19] = obs_batch[:, IDX_PROFILE_START + 4]

    return features
