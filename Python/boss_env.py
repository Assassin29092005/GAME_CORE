"""
Gymnasium environment for Boss RL training.
Connects to UE5 via TCP socket (RLBridgeComponent).

Supports dynamic observation augmentation:
  - Base: 17 dims (9 game state + 8 player profile)
  - +IRL: 5 dims (predicted player action distribution)
  - +Emotion: 3 dims (frustration, flow, boredom)
"""

import json
import socket
import threading
import time

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class BossEnv(gym.Env):
    """
    Observation space: dynamically sized float vector (17-25 dims depending on config)

    Base 17-dim:
        [hero_vel_x, hero_vel_y, hero_vel_z, hero_combo, hero_attacking,
         hero_hp, distance, angle, boss_hp,
         aggression, dodge, block, opener, pressure, kiting, combo_completion, positional_var]

    +IRL (5 dims): predicted P(attack|s), P(block|s), P(dodge|s), P(approach|s), P(retreat|s)
    +Emotion (3 dims): frustration, flow, boredom

    Action space: Discrete(5)
        0: Attack, 1: Block, 2: Dodge, 3: Approach, 4: Retreat
    """

    metadata = {"render_modes": []}

    # Named indices for base observation vector (always present)
    IDX_HERO_HP = 5
    IDX_DISTANCE = 6
    IDX_BOSS_HP = 8
    IDX_PROFILE_START = 9
    IDX_PROFILE_END = 17
    BASE_OBS_SIZE = 17

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5555,
        timeout: float = 60.0,  # generous: UE shader-compile/hitches can stall obs >10s
        step_delay: float = 0.066,  # ~15 Hz to match UE tick rate
        player_id: str = "default",
        cfg: dict | None = None,
        heartbeat_interval: float = 0.0,  # >0: no-op {"action": -1} keeps the C++ watchdog fed
    ):
        super().__init__()

        self.host = host
        self.port = port
        self.timeout = timeout
        self.step_delay = step_delay
        self.player_id = player_id
        self._cfg = cfg or {}
        self.heartbeat_interval = heartbeat_interval

        # --- Determine observation size from config flags ---
        self._irl_enabled = self._cfg.get("irl", {}).get("enabled", False)
        self._emotion_enabled = self._cfg.get("emotion", {}).get("enabled", False)
        self._record_hero_actions = self._cfg.get("world_model", {}).get(
            "record_player_actions", False
        )

        # Compute dynamic observation dimensions
        obs_size = self.BASE_OBS_SIZE
        self._irl_start = obs_size
        if self._irl_enabled:
            obs_size += 5  # P(a|s) for 5 actions
        self._emotion_start = obs_size
        if self._emotion_enabled:
            obs_size += 3  # frustration, flow, boredom

        self.OBS_SIZE = obs_size

        # IRL model (lazy loaded)
        self._irl_model = None
        if self._irl_enabled:
            self._load_irl_model()

        # Observation: dynamic size
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.OBS_SIZE,), dtype=np.float32
        )

        # 5 discrete actions
        self.action_space = spaces.Discrete(5)

        self._socket: socket.socket | None = None
        self._buffer = ""
        self._prev_boss_hp = 1.0
        self._prev_hero_hp = 1.0
        self._steps = 0
        self._max_steps = 2000
        self._last_hero_action: int | None = None  # for world model training

        # Action mask + bridge telemetry (valid pre-reset: safe all-ones default)
        self._last_action_mask = np.ones(5, dtype=bool)
        self._last_exec = -1
        self._last_dropped = 0
        self._last_busy = 0

        # Heartbeat plumbing (thread only started when heartbeat_interval > 0)
        self._send_lock = threading.Lock()
        self._last_send_time = time.monotonic()
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    def action_masks(self) -> np.ndarray:
        """Legal-action mask for the CURRENT observation (bool, shape (5,)).

        Consumed by MaskablePPO via ActionMasker; half-step stale by design
        (C++ ApplyActionMask re-checks at dispatch).
        """
        return self._last_action_mask.copy()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._connect()

        # Identify the player to load correct memory/model
        self._send({"command": "set_player_id", "player_id": self.player_id})

        # Request initial observation
        self._send({"command": "reset"})
        obs = self._receive_observation()

        self._prev_boss_hp = obs[self.IDX_BOSS_HP]
        self._prev_hero_hp = obs[self.IDX_HERO_HP]
        self._steps = 0
        self._last_hero_action = None

        return obs, {}

    def step(self, action: int):
        self._steps += 1

        # Mask the policy actually sampled `action` under (the previous
        # observation's mask) — _receive_observation below overwrites
        # _last_action_mask with the NEW obs's mask, so capture it first.
        # Exposed as info["action_mask_pre"] for legality metrics.
        pre_mask = self._last_action_mask.copy()

        # Send action to UE5
        self._send({"action": int(action)})

        # Small delay to let UE5 process the action
        time.sleep(self.step_delay)

        # Request and receive new observation
        self._send({"command": "observe"})
        obs = self._receive_observation()

        # Calculate reward
        reward = self._compute_reward(obs)

        # Check termination
        boss_hp = obs[self.IDX_BOSS_HP]
        hero_hp = obs[self.IDX_HERO_HP]
        terminated = boss_hp <= 0.0 or hero_hp <= 0.0
        truncated = self._steps >= self._max_steps

        # Update previous state
        self._prev_boss_hp = boss_hp
        self._prev_hero_hp = hero_hp

        info = {
            "boss_hp": boss_hp,
            "hero_hp": hero_hp,
            "steps": self._steps,
            "action_mask": self._last_action_mask.copy(),
            "action_mask_pre": pre_mask,
            "exec_action": self._last_exec,
            "dropped_actions": self._last_dropped,
            "busy": self._last_busy,
        }

        # Include hero action for world model training data
        if self._last_hero_action is not None:
            info["hero_action"] = self._last_hero_action

        return obs, reward, terminated, truncated, info

    def _compute_reward(self, obs: np.ndarray) -> float:
        """
        Phase-based reward function:
        - Aggressive phase (boss HP 100-51%): reward for dealing damage to hero
        - Reactive phase (boss HP 50-0%): reward for blocking/dodging + survival
        """
        boss_hp = obs[self.IDX_BOSS_HP]
        hero_hp = obs[self.IDX_HERO_HP]
        distance = obs[self.IDX_DISTANCE]

        reward = 0.0

        # Damage dealt to hero (positive reward)
        hero_hp_delta = self._prev_hero_hp - hero_hp
        if hero_hp_delta > 0:
            reward += hero_hp_delta * 10.0

        # Damage taken by boss (negative reward)
        boss_hp_delta = self._prev_boss_hp - boss_hp
        if boss_hp_delta > 0:
            reward -= boss_hp_delta * 5.0

        # Phase-based modifiers
        if boss_hp > 0.5:
            # Aggressive phase: reward closing distance
            reward -= distance * 0.1
        else:
            # Reactive phase: reward maintaining medium distance
            optimal_dist = 0.5  # normalized
            dist_penalty = abs(distance - optimal_dist) * 0.2
            reward -= dist_penalty

            # Survival bonus in reactive phase
            reward += 0.1

        # Terminal rewards
        if hero_hp <= 0.0:
            reward += 50.0  # Boss wins
        if boss_hp <= 0.0:
            reward -= 50.0  # Boss loses

        # Small step penalty to encourage action
        reward -= 0.01

        return reward

    def _connect(self):
        """Connect to UE5 TCP server."""
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass

        # Retry loop: mitigates the reset-reconnect race where UE is still
        # tearing down the previous client socket when we come back.
        backoffs = [0.5, 1.0]
        for attempt in range(3):
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            try:
                self._socket.connect((self.host, self.port))
                break
            except ConnectionRefusedError:
                self._socket.close()
                self._socket = None
                if attempt >= 2:
                    raise
                time.sleep(backoffs[attempt])
        self._buffer = ""

        # Start heartbeat thread once (daemon; survives across reconnects
        # since _send always targets the current socket).
        if self.heartbeat_interval > 0 and self._hb_thread is None:
            self._hb_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self._hb_thread.start()

    def _heartbeat_loop(self):
        """Send a no-op {"action": -1} after heartbeat_interval s of send silence.

        No reply, no dispatch: ExecuteAction refreshes the C++ 45s connected
        watchdog before rejecting -1 as out-of-range (G4), so learn()/
        checkpoint pauses can't trip the watchdog. UE logs one benign
        "Invalid action index" warning per beat.
        """
        while not self._hb_stop.wait(self.heartbeat_interval / 4):
            if time.monotonic() - self._last_send_time >= self.heartbeat_interval:
                try:
                    self._send({"action": -1})
                except OSError:
                    pass

    def _send(self, data: dict):
        """Send JSON message to UE5 (lock: heartbeat thread shares the socket)."""
        if not self._socket:
            raise ConnectionError("Not connected to UE5")
        msg = json.dumps(data) + "\n"
        with self._send_lock:
            self._socket.sendall(msg.encode("utf-8"))
            self._last_send_time = time.monotonic()

    def _receive_observation(self) -> np.ndarray:
        """Receive and parse observation JSON from UE5, with dynamic augmentation."""
        if not self._socket:
            raise ConnectionError("Not connected to UE5")

        # Read complete lines; skip unsolicited SendReward payloads — a bare
        # {"reward": ...} line would otherwise parse as an all-zero obs.
        while True:
            while "\n" not in self._buffer:
                chunk = self._socket.recv(4096).decode("utf-8")
                if not chunk:
                    raise ConnectionError("UE5 disconnected")
                self._buffer += chunk

            line, self._buffer = self._buffer.split("\n", 1)
            data = json.loads(line)
            if "reward" in data and "boss_hp" not in data:
                continue  # not an observation — wait for the next line
            break

        # Legal-action mask (G5): 5 ints, index = EBossAction. Absent /
        # malformed / all-zero → all-ones (all-zero would crash MaskablePPO).
        raw = data.get("mask")
        if isinstance(raw, (list, tuple)) and len(raw) == 5:
            mask = np.asarray(raw, dtype=bool)
        else:
            mask = np.ones(5, dtype=bool)
        if not mask.any():
            mask = np.ones(5, dtype=bool)
        self._last_action_mask = mask

        # Forward-compat bridge telemetry (G6): absent until the C++ pass lands.
        self._last_exec = int(data.get("exec", -1))
        self._last_dropped = int(data.get("dropped", 0))
        self._last_busy = int(data.get("busy", 0))

        # Parse into observation vector
        obs = np.zeros(self.OBS_SIZE, dtype=np.float32)

        # --- Base 17 dims ---
        if "hero_vel" in data:
            obs[0] = data["hero_vel"][0]
            obs[1] = data["hero_vel"][1]
            obs[2] = data["hero_vel"][2]

        obs[3] = float(data.get("hero_combo", 0))
        obs[4] = 1.0 if data.get("hero_attacking", False) else 0.0
        obs[5] = float(data.get("hero_hp", 1.0))
        obs[6] = float(data.get("dist", 0.0))
        obs[7] = float(data.get("angle", 0.0))
        obs[8] = float(data.get("boss_hp", 1.0))

        # Parse player profile (8 dimensions, indices 9-16)
        profile = data.get("profile", [0.5] * 8)
        for i, val in enumerate(profile[:8]):
            obs[self.IDX_PROFILE_START + i] = float(val)

        # --- IRL augmentation: append P(a|s) for 5 player actions ---
        if self._irl_enabled and self._irl_model is not None:
            base_obs = obs[:self.BASE_OBS_SIZE]
            action_probs = self._irl_model.predict_action_distribution(base_obs)
            for i, prob in enumerate(action_probs[:5]):
                obs[self._irl_start + i] = prob

        # --- Emotion augmentation: parse from UE5 JSON ---
        if self._emotion_enabled:
            emotion = data.get("emotion", [0.0, 0.0, 0.0])
            for i, val in enumerate(emotion[:3]):
                obs[self._emotion_start + i] = float(val)

        # --- Store hero action for world model ---
        if self._record_hero_actions:
            self._last_hero_action = int(data.get("hero_action", 5))

        return obs

    def _receive_json(self) -> dict:
        """Receive and parse a single JSON message from UE5."""
        if not self._socket:
            raise ConnectionError("Not connected to UE5")

        while "\n" not in self._buffer:
            chunk = self._socket.recv(4096).decode("utf-8")
            if not chunk:
                raise ConnectionError("UE5 disconnected")
            self._buffer += chunk

        line, self._buffer = self._buffer.split("\n", 1)
        return json.loads(line)

    def _load_irl_model(self):
        """Load the trained IRL model if available."""
        try:
            from irl_player_model import MaxEntIRL
            irl_cfg = self._cfg.get("irl", {})
            model_dir = irl_cfg.get("model_dir", "./models/irl")
            player_model_path = f"{model_dir}/{self.player_id}"
            default_model_path = f"{model_dir}/default"

            import os
            if os.path.exists(f"{player_model_path}/irl_model.npz"):
                self._irl_model = MaxEntIRL.load(player_model_path)
            elif os.path.exists(f"{default_model_path}/irl_model.npz"):
                self._irl_model = MaxEntIRL.load(default_model_path)
            else:
                # No trained model yet — IRL dims will be zeros
                self._irl_model = None
        except ImportError:
            self._irl_model = None

    def close(self):
        self._hb_stop.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
