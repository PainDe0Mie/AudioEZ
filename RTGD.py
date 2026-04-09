# RTGD.py — Real-Time Genre Detection + Adaptive EQ for AudioEZ
#
# This module provides two classes:
#   - RTGD: continuously captures system audio and classifies it with an AST model.
#   - AudioEZAdaptiveIntegration: maps detections to EQ profiles, smoothly
#     transitions the AudioEngine between them, and exposes a customisable
#     configuration surface for the UI.
#
# v1.1 overhaul highlights:
#   * Thread-safe state with proper locks and shutdown.
#   * Throttled APO writes during transitions (no more thrashing config.txt).
#   * Manual-override detection: any user EQ change pauses adaptive switches.
#   * Live status callback so the UI can show what's currently playing.
#   * Runtime-configurable thresholds, hysteresis, cooldown, transition speed,
#     and a per-profile enable/disable list.
#   * Custom user profiles can be merged on top of the defaults.
#   * Robust capture init, fallback to default mic, safe teardown.

import threading
import time
import logging
import warnings
import copy
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, Optional, List, Any

import numpy as np

try:
    from soundcard import SoundcardRuntimeWarning
except Exception:  # pragma: no cover - soundcard might be missing
    class SoundcardRuntimeWarning(Warning):
        pass

try:
    import librosa
except ImportError:
    librosa = None

_torch = None
_transformers = None
try:
    import torch as _torch
    import transformers as _transformers
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("RTGD")


# --------------------------------------------------------------------------- #
#  RTGD: audio capture + AST classification                                   #
# --------------------------------------------------------------------------- #

class RTGD:
    """Buffered audio classifier driven by a worker thread.

    The worker pulls the most recent `analysis_window` seconds from the buffer,
    runs the AST model, and invokes `callback(detections_dict)`.
    """

    DEFAULT_CONFIG = {
        'refine_model_name': 'MIT/ast-finetuned-audioset-10-10-0.4593',
        'analysis_window': 4.0,         # seconds of audio fed to the model
        'analysis_interval': 2.0,       # min seconds between two analyses
        'queue_max_seconds': 8.0,       # ring buffer length
        'device': None,                 # auto-pick if None
    }

    def __init__(self, config: Optional[Dict] = None):
        self.config: Dict[str, Any] = dict(self.DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        if not self.config.get('device'):
            self.config['device'] = 'cuda' if (_torch and _torch.cuda.is_available()) else 'cpu'

        self.buffer: deque = deque()
        self.buffer_sr: Optional[int] = None
        self.buffer_lock = threading.Lock()

        self.worker_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.stop_event = threading.Event()

        self.callback: Optional[Callable[[Dict], None]] = None
        self.status_callback: Optional[Callable[[str], None]] = None

        self._refine_model = None
        self._refine_feature_extractor = None
        self._model_loaded = False

    # ---- public API ------------------------------------------------------ #

    def register_callback(self, fn: Callable[[Dict], None]):
        self.callback = fn

    def register_status_callback(self, fn: Callable[[str], None]):
        self.status_callback = fn

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="RTGD-Worker")
        self.worker_thread.start()
        self._emit_status("RTGD started")
        log.info("RTGD started (device=%s)", self.config['device'])

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.stop_event.set()
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)
        self.worker_thread = None
        with self.buffer_lock:
            self.buffer.clear()
            self.buffer_sr = None
        self._emit_status("RTGD stopped")
        log.info("RTGD stopped")

    def update_config(self, partial: Dict):
        """Hot-update analysis window/interval/device. Safe to call while running."""
        if not partial:
            return
        for key in ('analysis_window', 'analysis_interval', 'queue_max_seconds'):
            if key in partial:
                try:
                    self.config[key] = float(partial[key])
                except (TypeError, ValueError):
                    pass

    def enqueue_audio(self, frame: np.ndarray, sr: int):
        if frame is None or frame.size == 0:
            return
        frame_mono = np.mean(frame, axis=1) if frame.ndim > 1 else frame.astype(np.float32)
        with self.buffer_lock:
            if self.buffer_sr is None:
                self.buffer_sr = int(sr)
            if sr != self.buffer_sr and librosa:
                try:
                    frame_mono = librosa.resample(frame_mono, orig_sr=sr, target_sr=self.buffer_sr)
                except Exception:
                    pass
            self.buffer.append(frame_mono)
            max_samples = int(self.buffer_sr * self.config['queue_max_seconds'])
            total = sum(len(x) for x in self.buffer)
            while total > max_samples and self.buffer:
                total -= len(self.buffer.popleft())

    # ---- internals ------------------------------------------------------- #

    def _emit_status(self, msg: str):
        try:
            if self.status_callback:
                self.status_callback(msg)
        except Exception:
            pass

    def _load_refine(self) -> bool:
        if self._refine_model:
            return True
        if not _transformers or not _torch:
            self._emit_status("AST model unavailable (torch/transformers missing)")
            log.warning("torch/transformers missing — adaptive filter cannot run.")
            return False
        try:
            from transformers import AutoFeatureExtractor, ASTForAudioClassification
            self._emit_status("Loading AST model…")
            log.info("Loading AST model %s", self.config['refine_model_name'])
            self._refine_feature_extractor = AutoFeatureExtractor.from_pretrained(self.config['refine_model_name'])
            self._refine_model = ASTForAudioClassification.from_pretrained(self.config['refine_model_name'])
            self._refine_model.eval().to(self.config['device'])
            self._model_loaded = True
            self._emit_status("AST model ready")
            log.info("AST model loaded.")
            return True
        except Exception as e:
            self._emit_status(f"AST load failed: {e}")
            log.warning("AST refine load failed: %s", e)
            return False

    def _worker_loop(self):
        if not self._load_refine():
            self.is_running = False
            return

        last_analysis_time = 0.0
        while self.is_running and not self.stop_event.is_set():
            try:
                # Wake every 100ms but rate-limited by analysis_interval.
                time.sleep(0.1)
                interval = max(0.5, float(self.config.get('analysis_interval', 2.0)))
                now = time.time()
                if now - last_analysis_time < interval:
                    continue

                with self.buffer_lock:
                    if self.buffer_sr is None:
                        continue
                    arr = np.concatenate(list(self.buffer)) if self.buffer else np.array([], dtype=np.float32)
                    sr = self.buffer_sr

                window = float(self.config.get('analysis_window', 4.0))
                analysis_samples = int(sr * window)
                if arr.size < analysis_samples:
                    continue

                last_analysis_time = now
                segment = arr[-analysis_samples:]
                detections = self._run_analysis(segment, sr)
                if self.callback:
                    self.callback({'timestamp': now, 'detections': detections})
            except Exception as e:
                log.exception("Worker loop error: %s", e)
                time.sleep(0.5)

    def _run_analysis(self, audio_1d: np.ndarray, sr: int) -> Dict[str, float]:
        if not self._refine_model or not self._refine_feature_extractor:
            return {}
        try:
            target_sr = self._refine_feature_extractor.sampling_rate
            if sr != target_sr and librosa:
                audio_1d = librosa.resample(audio_1d, orig_sr=sr, target_sr=target_sr)
            inputs = self._refine_feature_extractor(audio_1d, sampling_rate=target_sr, return_tensors='pt').to(self.config['device'])
            with _torch.no_grad():
                logits = self._refine_model(**inputs).logits[0]
                probs = _torch.nn.functional.softmax(logits, dim=-1).cpu().numpy()
            topk = min(15, probs.size)
            idx = np.argsort(probs)[-topk:][::-1]
            return {self._refine_model.config.id2label[int(i)]: float(probs[int(i)]) for i in idx}
        except Exception as e:
            log.warning("AST analysis failed: %s", e)
            return {}


# --------------------------------------------------------------------------- #
#  EQProfile dataclass + default profile bank                                 #
# --------------------------------------------------------------------------- #

@dataclass
class EQProfile:
    name: str
    bands: List[Dict] = field(default_factory=list)
    bass: float = 0.0
    treble: float = 0.0


def _build_default_profiles() -> Dict[str, EQProfile]:
    return {
        "Speech":     EQProfile("Voice clarity",     [{"freq": 250, "gain": -1.0, "q": 1.0, "type": "PK"},
                                                       {"freq": 3500, "gain": 2.0, "q": 1.5, "type": "PK"}], -1.5, 1.0),
        "Movie":      EQProfile("Cinema",            [{"freq": 80,   "gain": 1.5, "q": 0.7, "type": "LS"},
                                                       {"freq": 300,  "gain": -1.0,"q": 1.2, "type": "PK"},
                                                       {"freq": 4000, "gain": 1.5, "q": 1.5, "type": "PK"}], 1.0, 0.5),
        "Music":      EQProfile("Balanced music",    [], 0.5, 0.5),
        "Electronic": EQProfile("Electronic",        [{"freq": 50,   "gain": 2.0, "q": 0.8, "type": "LS"},
                                                       {"freq": 10000,"gain": 1.5, "q": 1.0, "type": "HS"}], 1.5, 1.0),
        "Rock":       EQProfile("Rock",              [{"freq": 150,  "gain": 1.5, "q": 0.9, "type": "PK"},
                                                       {"freq": 4000, "gain": 1.0, "q": 1.4, "type": "PK"}], 1.0, 0.5),
        "Classical":  EQProfile("Classical",         [{"freq": 10000,"gain": 1.5, "q": 1.0, "type": "HS"}], 0.0, 1.0),
        "Hip-Hop":    EQProfile("Hip-Hop",           [{"freq": 60,   "gain": 2.0, "q": 0.7, "type": "LS"},
                                                       {"freq": 2500, "gain": 1.5, "q": 1.5, "type": "PK"}], 1.5, 0.5),
        "Jazz":       EQProfile("Jazz",              [{"freq": 200,  "gain": -1.0,"q": 1.2, "type": "PK"},
                                                       {"freq": 7000, "gain": 1.5, "q": 1.2, "type": "PK"}], 0.0, 1.0),
        "Singing":    EQProfile("Vocal focus",       [{"freq": 120,  "gain": -1.0,"q": 0.7, "type": "LS"},
                                                       {"freq": 2000, "gain": 2.0, "q": 1.5, "type": "PK"}], -0.5, 1.5),
        "Pop":        EQProfile("Pop",               [{"freq": 80,   "gain": 1.0, "q": 0.7, "type": "LS"},
                                                       {"freq": 12000,"gain": 1.5, "q": 0.9, "type": "HS"}], 1.0, 1.0),
        "Ambient":    EQProfile("Ambient",           [{"freq": 60,   "gain": 1.5, "q": 0.7, "type": "LS"},
                                                       {"freq": 400,  "gain": -1.0,"q": 1.5, "type": "PK"},
                                                       {"freq": 13000,"gain": 1.0, "q": 1.0, "type": "HS"}], 0.5, 0.5),
        "Acoustic":   EQProfile("Acoustic",          [{"freq": 180,  "gain": -1.5,"q": 1.4, "type": "PK"},
                                                       {"freq": 5000, "gain": 1.0, "q": 1.8, "type": "PK"}], -0.5, 0.5),
        "default":    EQProfile("Off",               [], 0.0, 0.0),
    }


_GENRE_MAP = {
    # Electronic
    "Electronic music": "Electronic", "Techno": "Electronic", "Dubstep": "Electronic",
    "House music": "Electronic", "Electronica": "Electronic", "Dance music": "Electronic",
    # Rock / Alternative
    "Rock music": "Rock", "Heavy metal": "Rock", "Punk rock": "Rock",
    "Alternative rock": "Rock", "Indie rock": "Rock",
    # Pop
    "Pop music": "Pop",
    # Classical
    "Classical music": "Classical", "Orchestra": "Classical", "Symphony": "Classical",
    # Hip-Hop / R&B
    "Hip hop music": "Hip-Hop", "Rhythm and blues": "Hip-Hop", "Funk": "Hip-Hop",
    # Jazz
    "Jazz": "Jazz", "Swing music": "Jazz", "Blues": "Jazz",
    # Acoustic / Folk
    "Folk music": "Acoustic", "Country": "Acoustic",
    "Acoustic guitar": "Acoustic", "Piano": "Acoustic",
    # Ambient
    "Ambient music": "Ambient", "Chill-out music": "Ambient",
    # Vocal
    "Singing": "Singing", "Choir": "Singing", "Opera": "Singing",
    "Chant": "Singing", "Mantra": "Singing", "Vocal music": "Singing",
    # Broad
    "Music": "Music", "Musical instrument": "Music",
    # Non-music
    "Speech": "Speech", "Narration, monologue": "Speech",
    "Male speech, man speaking": "Speech", "Female speech, woman speaking": "Speech",
    "Movie": "Movie", "Film": "Movie", "Video game music": "Movie",
}


# --------------------------------------------------------------------------- #
#  AudioEZAdaptiveIntegration                                                 #
# --------------------------------------------------------------------------- #

class AudioEZAdaptiveIntegration:
    """Bridges RTGD detections with AudioEngine EQ transitions."""

    DEFAULT_CONFIG = {
        # Detection thresholds (0..1).
        'speech_threshold': 0.6,
        'movie_threshold': 0.5,
        'music_genre_threshold': 0.4,
        'general_music_threshold': 0.2,
        # Stability + cooldown.
        'hysteresis_delay': 8.0,    # seconds the candidate must dominate before switching
        'cooldown_period': 12.0,    # min seconds between two profile switches
        # Smoothness.
        'transition_duration': 1.5,
        # User-controllable enable list (None = all).
        'enabled_profiles': None,
        # Pause adaptive when the user touches the EQ manually.
        'manual_override_pause': True,
        'manual_override_timeout': 30.0,
    }

    def __init__(self, audio_engine, rtgd_config: Optional[Dict] = None):
        self.audio_engine = audio_engine

        # Split config: anything in DEFAULT_CONFIG belongs to the integration,
        # the rest is forwarded to RTGD.
        rtgd_config = dict(rtgd_config or {})
        self.config: Dict[str, Any] = dict(self.DEFAULT_CONFIG)
        for key in list(rtgd_config.keys()):
            if key in self.DEFAULT_CONFIG:
                self.config[key] = rtgd_config.pop(key)

        self.rtgd = RTGD(config=rtgd_config)
        self.rtgd.register_callback(self._on_detection)
        self.rtgd.register_status_callback(self._on_rtgd_status)

        # Profiles + genre map can be customised at runtime.
        self.eq_profiles: Dict[str, EQProfile] = _build_default_profiles()
        self.genre_map: Dict[str, str] = dict(_GENRE_MAP)

        # Runtime state (guarded by self._state_lock).
        self._state_lock = threading.RLock()
        self.is_adaptive_enabled = False
        self.is_paused = False
        self.original_eq_settings: Optional[Dict] = None
        self.current_profile_key = "default"
        self.last_switch_time = 0.0
        self.hysteresis_candidate: Optional[str] = None
        self.potential_class_start_time: float = 0.0
        self.last_status: Dict[str, Any] = {'detection': '', 'confidence': 0.0,
                                            'profile': 'default', 'paused': False}
        self._manual_override_until = 0.0

        # Capture / transition threads.
        self.recorder = None
        self.record_thread: Optional[threading.Thread] = None
        self.transition_thread: Optional[threading.Thread] = None
        self.stop_transition_event = threading.Event()
        self._record_stop_event = threading.Event()

        # Optional UI hook (set by PythonChannel).
        self.status_listener: Optional[Callable[[Dict], None]] = None

    # ---- configuration -------------------------------------------------- #

    def set_status_listener(self, fn: Callable[[Dict], None]):
        self.status_listener = fn

    def update_config(self, partial: Dict):
        """Hot-update integration + RTGD config from a single dict."""
        if not partial:
            return
        rtgd_keys = ('analysis_window', 'analysis_interval', 'queue_max_seconds')
        rtgd_partial = {k: partial[k] for k in rtgd_keys if k in partial}
        if rtgd_partial:
            self.rtgd.update_config(rtgd_partial)

        with self._state_lock:
            for key, value in partial.items():
                if key in self.DEFAULT_CONFIG:
                    if key == 'enabled_profiles':
                        if value is None:
                            self.config[key] = None
                        else:
                            self.config[key] = list(value)
                    elif key == 'manual_override_pause':
                        self.config[key] = bool(value)
                    else:
                        try:
                            self.config[key] = float(value)
                        except (TypeError, ValueError):
                            pass
        log.info("Adaptive config updated: %s", partial)

    def set_profile(self, key: str, profile_dict: Dict):
        """Replace or add a profile from a JSON-friendly dict."""
        with self._state_lock:
            self.eq_profiles[key] = EQProfile(
                name=profile_dict.get('name', key),
                bands=list(profile_dict.get('bands', [])),
                bass=float(profile_dict.get('bass', 0.0)),
                treble=float(profile_dict.get('treble', 0.0)),
            )

    def get_profiles_serializable(self) -> Dict[str, Dict]:
        with self._state_lock:
            return {k: asdict(v) for k, v in self.eq_profiles.items()}

    def get_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self.last_status)

    def pause(self):
        with self._state_lock:
            self.is_paused = True
            self.last_status['paused'] = True
        self._emit_status()

    def resume(self):
        with self._state_lock:
            self.is_paused = False
            self.last_status['paused'] = False
            self._manual_override_until = 0.0
        self._emit_status()

    def notify_manual_eq_change(self):
        """Called by AudioEngine/PythonChannel when the user touches the EQ."""
        if not self.config.get('manual_override_pause', True):
            return
        if not self.is_adaptive_enabled:
            return
        with self._state_lock:
            self._manual_override_until = time.time() + float(self.config.get('manual_override_timeout', 30.0))
            self.is_paused = True
            self.last_status['paused'] = True
        self._emit_status()
        log.info("Adaptive paused (manual override) for %.1fs", self.config.get('manual_override_timeout', 30.0))

    # ---- enable/disable ------------------------------------------------- #

    def enable_adaptive_filter(self):
        if self.is_adaptive_enabled:
            return
        try:
            self.original_eq_settings = self.audio_engine.get_current_config()
            log.info("Original EQ saved.")
        except Exception as e:
            self.original_eq_settings = None
            log.warning("Could not save EQ: %s", e)

        self.rtgd.start()
        self.is_adaptive_enabled = True
        self._record_stop_event.clear()

        try:
            warnings.filterwarnings('ignore', category=SoundcardRuntimeWarning)
            import soundcard as sc
            log.info("Attempting loopback capture…")
            speaker = sc.default_speaker()
            mic = next(
                (m for m in sc.all_microphones(include_loopback=True) if speaker.name in m.name),
                sc.default_microphone(),
            )
            log.info("Using mic: %s", mic.name)
            self.recorder = mic.recorder(samplerate=48000, channels=1)
            self.recorder.__enter__()
            self.record_thread = threading.Thread(
                target=self._record_loop, daemon=True, name="RTGD-Capture"
            )
            self.record_thread.start()
            log.info("Adaptive filter enabled.")
            self.last_status = {'detection': 'idle', 'confidence': 0.0,
                                'profile': 'default', 'paused': False}
            self._emit_status()
        except Exception as e:
            log.error("Capture failed: %s", e, exc_info=True)
            self.rtgd.stop()
            self.is_adaptive_enabled = False
            self._safe_close_recorder()

    def disable_adaptive_filter(self):
        if not self.is_adaptive_enabled:
            return
        self.is_adaptive_enabled = False
        self._record_stop_event.set()
        self.rtgd.stop()
        if self.record_thread:
            self.record_thread.join(timeout=1.5)
        self._safe_close_recorder()
        log.info("Adaptive filter disabled.")
        if self.original_eq_settings:
            log.info("Restoring original EQ.")
            try:
                self.start_transition(self.audio_engine.get_current_config(),
                                      self.original_eq_settings, duration=1.0)
            except Exception as e:
                log.warning("Could not start restore transition: %s", e)
            self.original_eq_settings = None
        with self._state_lock:
            self.current_profile_key = "default"
            self.hysteresis_candidate = None
            self.is_paused = False
            self.last_status = {'detection': '', 'confidence': 0.0,
                                'profile': 'default', 'paused': False}
        self._emit_status()

    def _safe_close_recorder(self):
        try:
            if self.recorder is not None:
                self.recorder.__exit__(None, None, None)
        except Exception as e:
            log.warning("Recorder teardown failed: %s", e)
        finally:
            self.recorder = None

    def _record_loop(self):
        while not self._record_stop_event.is_set():
            try:
                if self.recorder is None:
                    break
                frame = self.recorder.record(numframes=4096)
                self.rtgd.enqueue_audio(frame, self.recorder.samplerate)
            except Exception as e:
                log.error("Record loop error: %s", e)
                time.sleep(1.0)

    # ---- detection -> profile decision ---------------------------------- #

    def _on_rtgd_status(self, msg: str):
        with self._state_lock:
            self.last_status['detection'] = msg
        self._emit_status()

    def _emit_status(self):
        try:
            if self.status_listener:
                self.status_listener(self.get_status())
        except Exception:
            pass

    def _on_detection(self, out: Dict):
        if not self.is_adaptive_enabled:
            return
        detections = out.get('detections') or {}
        if not detections:
            return

        # Auto-resume after manual override timeout.
        with self._state_lock:
            if self.is_paused and self._manual_override_until and time.time() >= self._manual_override_until:
                self.is_paused = False
                self._manual_override_until = 0.0
                self.last_status['paused'] = False
                log.info("Manual override expired — adaptive resumed.")

            if self.is_paused:
                return

            # Update top-1 detection regardless of profile change so the UI is live.
            top_label, top_conf = next(iter(detections.items()))
            self.last_status['detection'] = top_label
            self.last_status['confidence'] = float(top_conf)

        cfg = self.config
        speech_conf = (detections.get("Speech", 0.0)
                       + detections.get("Male speech, man speaking", 0.0)
                       + detections.get("Female speech, woman speaking", 0.0))
        movie_conf = (detections.get("Movie", 0.0)
                      + detections.get("Film", 0.0)
                      + detections.get("Video game music", 0.0))
        music_conf = (detections.get("Music", 0.0)
                      + detections.get("Musical instrument", 0.0))

        chosen = "default"
        if speech_conf >= cfg['speech_threshold']:
            chosen = "Speech"
        elif movie_conf >= cfg['movie_threshold'] and speech_conf < cfg['speech_threshold'] * 0.8:
            chosen = "Movie"
        else:
            best_conf = 0.0
            best_key = "Music"
            for label, conf in detections.items():
                cat = self.genre_map.get(label)
                if cat and cat not in ("Speech", "Movie", "Music"):
                    if conf >= cfg['music_genre_threshold'] and conf > best_conf:
                        best_conf = conf
                        best_key = cat
            if best_conf > 0:
                chosen = best_key
            elif music_conf >= cfg['general_music_threshold']:
                chosen = "Music"

        # Honour the user's enabled-profile list.
        enabled = cfg.get('enabled_profiles')
        if enabled is not None and chosen not in enabled and chosen != "default":
            chosen = "default"

        if chosen == "default":
            with self._state_lock:
                self.hysteresis_candidate = None
            self._emit_status()
            return

        now = time.time()
        with self._state_lock:
            if chosen == self.current_profile_key:
                self.hysteresis_candidate = None
                self._emit_status()
                return

            if chosen == self.hysteresis_candidate:
                stable_long_enough = (now - self.potential_class_start_time) >= float(cfg['hysteresis_delay'])
                cooldown_passed = (now - self.last_switch_time) >= float(cfg['cooldown_period'])
                if stable_long_enough and cooldown_passed:
                    target = self.eq_profiles.get(chosen)
                    if target:
                        log.info("Transition confirmed → '%s'", chosen)
                        self.current_profile_key = chosen
                        self.last_switch_time = now
                        self.hysteresis_candidate = None
                        self.last_status['profile'] = chosen
                        # Release lock before kicking off the transition thread.
                    else:
                        return
                else:
                    self._emit_status()
                    return
            else:
                log.info("New candidate '%s' — stability check…", chosen)
                self.hysteresis_candidate = chosen
                self.potential_class_start_time = now
                self._emit_status()
                return

        # Outside the lock — start the transition.
        self._emit_status()
        self.start_transition_to_profile(target)

    # ---- profile merging + transitions ---------------------------------- #

    def _merge_eq(self, base_eq: Dict, profile: EQProfile) -> Dict:
        merged = {
            'pre_gain_db': base_eq.get('pre_gain_db', 0.0),
            'bass_gain_db': base_eq.get('bass_gain_db', 0.0) + profile.bass,
            'treble_gain_db': base_eq.get('treble_gain_db', 0.0) + profile.treble,
        }
        base_filters = [
            {'freq': f, 'gain': g, 'q': q, 'type': t}
            for f, g, q, t in zip(
                base_eq.get('bands', []),
                base_eq.get('gains', []),
                base_eq.get('q_values', []),
                base_eq.get('filter_types', []),
            )
        ]
        for p_band in profile.bands:
            closest = min(base_filters,
                          key=lambda b: abs(np.log10(b['freq']) - np.log10(p_band['freq']))) if base_filters else None
            if closest and (closest['freq'] / 1.5 < p_band['freq'] < closest['freq'] * 1.5):
                closest['gain'] += p_band['gain']
            else:
                base_filters.append(dict(p_band))
        base_filters.sort(key=lambda x: x['freq'])

        merged['bands'] = [f['freq'] for f in base_filters]
        merged['gains'] = [f['gain'] for f in base_filters]
        merged['q_values'] = [f['q'] for f in base_filters]
        merged['filter_types'] = [f['type'] for f in base_filters]
        return merged

    def start_transition_to_profile(self, target_profile: EQProfile):
        if self.original_eq_settings is None:
            log.warning("Original EQ missing, cannot transition.")
            return
        merged = self._merge_eq(self.original_eq_settings, target_profile)
        self.start_transition(self.audio_engine.get_current_config(), merged,
                              duration=float(self.config.get('transition_duration', 1.5)))

    def start_transition(self, start_eq: Dict, end_eq: Dict, duration: float = 1.0):
        if self.transition_thread and self.transition_thread.is_alive():
            self.stop_transition_event.set()
            self.transition_thread.join(timeout=0.5)
        self.stop_transition_event.clear()
        self.transition_thread = threading.Thread(
            target=self._run_transition_loop,
            args=(copy.deepcopy(start_eq), copy.deepcopy(end_eq), duration, self.stop_transition_event),
            daemon=True,
            name="RTGD-Transition",
        )
        self.transition_thread.start()

    def _run_transition_loop(self, start_eq: Dict, end_eq: Dict, duration: float, stop_event: threading.Event):
        steps = max(1, int(40 * max(0.1, duration)))
        interval = duration / steps
        s_p = {k: float(start_eq.get(k, 0.0)) for k in ('pre_gain_db', 'bass_gain_db', 'treble_gain_db')}
        e_p = {k: float(end_eq.get(k, 0.0)) for k in ('pre_gain_db', 'bass_gain_db', 'treble_gain_db')}
        all_freqs = sorted(set(start_eq.get('bands', [])) | set(end_eq.get('bands', [])))

        def get_p(eq, freqs):
            if not eq.get('bands'):
                return np.zeros(len(freqs)), np.ones(len(freqs))
            g = np.interp(freqs, eq['bands'], eq.get('gains', [0.0] * len(eq['bands'])))
            q = np.interp(freqs, eq['bands'], eq.get('q_values', [1.0] * len(eq['bands'])))
            return g, q

        s_g, s_q = get_p(start_eq, all_freqs)
        e_g, e_q = get_p(end_eq, all_freqs)
        e_t = {f: t for f, t in zip(end_eq.get('bands', []), end_eq.get('filter_types', []))}
        f_t = [e_t.get(f, 'PK') for f in all_freqs]

        # Throttle APO writes: only at start, every ~120ms, and at the end.
        last_apo_write = 0.0
        APO_INTERVAL = 0.12

        for i in range(steps + 1):
            if stop_event.is_set():
                return
            p = i / steps
            try:
                for k in s_p:
                    setattr(self.audio_engine, k, float(s_p[k] + (e_p[k] - s_p[k]) * p))
                self.audio_engine.bands = list(all_freqs)
                self.audio_engine.band_count = len(all_freqs)
                self.audio_engine.gains = np.array(s_g + (e_g - s_g) * p, dtype=float)
                self.audio_engine.q_values = np.array(s_q + (e_q - s_q) * p, dtype=float)
                self.audio_engine.filter_types = list(f_t)
                self.audio_engine.send_full_ui_update()

                now = time.time()
                is_last = (i == steps)
                if getattr(self.audio_engine, 'is_playing', False):
                    if is_last or (now - last_apo_write) >= APO_INTERVAL:
                        self.audio_engine._apply_apo_config()
                        last_apo_write = now
            except Exception as e:
                log.debug("Transition step failed: %s", e)
            time.sleep(interval)
