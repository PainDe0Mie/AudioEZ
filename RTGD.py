# RTGD_with_AudioEZIntegration.py


import threading, time, queue, logging, sys, warnings
import numpy as np
from collections import deque
from typing import Callable, Dict, Optional, List
from dataclasses import dataclass
from soundcard import SoundcardRuntimeWarning

try:
    import librosa
except ImportError:
    librosa = None

_torch, _transformers, _tf, _tfhub = None, None, None, None
try: import torch as _torch; import transformers as _transformers
except ImportError: pass
try: import tensorflow as _tf; import tensorflow_hub as _tfhub
except ImportError: pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

class RTGD:
    def __init__(self, config: Optional[Dict] = None):
        self.config = {
            'refine_model_name': 'MIT/ast-finetuned-audioset-10-10-0.4593',
            'analysis_window': 4.0,
            'queue_max_seconds': 8.0,
            'device': 'cuda' if (_torch and _torch.cuda.is_available()) else 'cpu'
        }
        if config: self.config.update(config)
        self.buffer = deque()
        self.buffer_sr = None
        self.buffer_lock = threading.Lock()
        self.worker_thread = None
        self.is_running = False
        self.stop_event = threading.Event()
        self.callback: Optional[Callable[[Dict], None]] = None
        self._refine_model = None
        self._refine_feature_extractor = None

    def start(self):
        if self.is_running: return
        self.is_running = True
        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logging.info("RTGD started (AST-Primary Mode)")

    def stop(self):
        if not self.is_running: return
        self.is_running = False
        self.stop_event.set()
        if self.worker_thread: self.worker_thread.join(timeout=1.0)
        logging.info("RTGD stopped")

    def register_callback(self, fn: Callable[[Dict], None]):
        self.callback = fn

    def enqueue_audio(self, frame: np.ndarray, sr: int):
        if frame is None or frame.size == 0: return
        frame_mono = np.mean(frame, axis=1) if frame.ndim > 1 else frame.astype(np.float32)
        with self.buffer_lock:
            if self.buffer_sr is None: self.buffer_sr = int(sr)
            if sr != self.buffer_sr and librosa:
                try: frame_mono = librosa.resample(frame_mono, orig_sr=sr, target_sr=self.buffer_sr)
                except Exception: pass
            self.buffer.append(frame_mono)
            max_samples = int(self.buffer_sr * self.config['queue_max_seconds'])
            total = sum(len(x) for x in self.buffer)
            while total > max_samples and self.buffer: total -= len(self.buffer.popleft())

    def _load_refine(self):
        if self._refine_model or not _transformers or not _torch: return
        try:
            from transformers import AutoFeatureExtractor, ASTForAudioClassification
            logging.info(f"Loading AST model {self.config['refine_model_name']}...")
            self._refine_feature_extractor = AutoFeatureExtractor.from_pretrained(self.config['refine_model_name'])
            self._refine_model = ASTForAudioClassification.from_pretrained(self.config['refine_model_name'])
            self._refine_model.eval().to(self.config['device'])
            logging.info('AST model loaded.')
        except Exception as e:
            logging.warning(f'AST refine load failed: {e}')

    def _worker_loop(self):
        self._load_refine()
        last_analysis_time = 0.0
        while self.is_running and not self.stop_event.is_set():
            try:
                time.sleep(0.1)
                analysis_interval = self.config['analysis_window'] / 2
                with self.buffer_lock:
                    if self.buffer_sr is None: continue
                    arr = np.concatenate(list(self.buffer)) if self.buffer else np.array([], dtype=np.float32)
                now = time.time()
                if now - last_analysis_time < analysis_interval: continue
                analysis_samples = int(self.buffer_sr * self.config['analysis_window'])
                if arr.size < analysis_samples: continue
                last_analysis_time = now
                analysis_segment = arr[-analysis_samples:]
                detections = self._run_analysis(analysis_segment, self.buffer_sr)
                out = {'timestamp': now, 'detections': detections}
                if self.callback: self.callback(out)
            except Exception as e:
                logging.exception(f'Worker loop error: {e}')
                time.sleep(0.5)

    def _run_analysis(self, audio_1d: np.ndarray, sr: int) -> Dict[str, float]:
        if not self._refine_model or not self._refine_feature_extractor: return {}
        try:
            TARGET_SR = self._refine_feature_extractor.sampling_rate
            if sr != TARGET_SR and librosa:
                audio_1d = librosa.resample(audio_1d, orig_sr=sr, target_sr=TARGET_SR)
            inputs = self._refine_feature_extractor(audio_1d, sampling_rate=TARGET_SR, return_tensors='pt').to(self.config['device'])
            with _torch.no_grad():
                logits = self._refine_model(**inputs).logits[0]
                probs = _torch.nn.functional.softmax(logits, dim=-1).cpu().numpy()
            topk = min(15, probs.size)
            idx = np.argsort(probs)[-topk:][::-1]
            return {self._refine_model.config.id2label[int(i)]: float(probs[int(i)]) for i in idx}
        except Exception as e:
            logging.warning(f'AST analysis failed: {e}')
            return {}

@dataclass
class EQProfile:
    name: str; bands: List[Dict]; bass: float = 0.0; treble: float = 0.0

class AudioEZAdaptiveIntegration:
    def __init__(self, audio_engine, rtgd_config: Optional[Dict] = None):
        self.audio_engine = audio_engine
        self.rtgd = RTGD(config=rtgd_config)
        self.rtgd.register_callback(self._on_detection)
        rtgd_config = rtgd_config or {}
        self.hysteresis_delay = rtgd_config.get('hysteresis_delay', 10.0) # Increased for stability
        self.cooldown_period = rtgd_config.get('cooldown_period', 12.0)
        self.is_adaptive_enabled = False
        self.original_eq_settings = None
        self.recorder, self.record_thread, self.transition_thread = None, None, None
        self.stop_transition_event = threading.Event()
        self.current_profile_key = "default"
        self.last_switch_time = 0.0
        self.hysteresis_candidate = None
        self.potential_class_start_time = None
        self._initialize_profiles_and_maps()

    def _initialize_profiles_and_maps(self):
        """Massive expansion of profiles and genre mappings for versatility."""
        self.eq_profiles = {
            "Speech": EQProfile(name="Clarté Vocale", bands=[{"freq": 250, "gain": -1.0, "q": 1.0, "type": "PK"}, {"freq": 3500, "gain": 2.0, "q": 1.5, "type": "PK"}], bass=-1.5, treble=1.0),
            "Movie": EQProfile(name="Cinéma", bands=[{"freq": 80, "gain": 1.5, "q": 0.7, "type": "LS"}, {"freq": 300, "gain": -1.0, "q": 1.2, "type": "PK"}, {"freq": 4000, "gain": 1.5, "q": 1.5, "type": "PK"}], bass=1.0, treble=0.5),
            "Music": EQProfile(name="Musique Équilibrée", bands=[], bass=0.5, treble=0.5),
            "Electronic": EQProfile(name="Électronique", bands=[{"freq": 50, "gain": 2.0, "q": 0.8, "type": "LS"}, {"freq": 10000, "gain": 1.5, "q": 1.0, "type": "HS"}], bass=1.5, treble=1.0),
            "Rock": EQProfile(name="Rock", bands=[{"freq": 150, "gain": 1.5, "q": 0.9, "type": "PK"}, {"freq": 4000, "gain": 1.0, "q": 1.4, "type": "PK"}], bass=1.0, treble=0.5),
            "Classical": EQProfile(name="Classique", bands=[{"freq": 10000, "gain": 1.5, "q": 1.0, "type": "HS"}], bass=0.0, treble=1.0),
            "Hip-Hop": EQProfile(name="Hip-Hop", bands=[{"freq": 60, "gain": 2.0, "q": 0.7, "type": "LS"}, {"freq": 2500, "gain": 1.5, "q": 1.5, "type": "PK"}], bass=1.5, treble=0.5),
            "Jazz": EQProfile(name="Jazz", bands=[{"freq": 200, "gain": -1.0, "q": 1.2, "type": "PK"}, {"freq": 7000, "gain": 1.5, "q": 1.2, "type": "PK"}], bass=0.0, treble=1.0),
            "Singing": EQProfile(name="Focus Vocal", bands=[{"freq": 120, "gain": -1.0, "q": 0.7, "type": "LS"}, {"freq": 2000, "gain": 2.0, "q": 1.5, "type": "PK"}], bass=-0.5, treble=1.5),
            "Pop": EQProfile(name="Pop", bands=[{"freq": 80, "gain": 1.0, "q": 0.7, "type": "LS"}, {"freq": 12000, "gain": 1.5, "q": 0.9, "type": "HS"}], bass=1.0, treble=1.0),
            "Ambient": EQProfile(name="Ambiant", bands=[{"freq": 60, "gain": 1.5, "q": 0.7, "type": "LS"}, {"freq": 400, "gain": -1.0, "q": 1.5, "type": "PK"}, {"freq": 13000, "gain": 1.0, "q": 1.0, "type": "HS"}], bass=0.5, treble=0.5),
            "Acoustic": EQProfile(name="Acoustique", bands=[{"freq": 180, "gain": -1.5, "q": 1.4, "type": "PK"}, {"freq": 5000, "gain": 1.0, "q": 1.8, "type": "PK"}], bass=-0.5, treble=0.5),
            "default": EQProfile(name="Désactivé", bands=[], bass=0.0, treble=0.0)
        }
        self.genre_map = {
            # Electronic
            "Electronic music": "Electronic", "Techno": "Electronic", "Dubstep": "Electronic", "House music": "Electronic", "Electronica": "Electronic", "Dance music": "Electronic",
            # Rock / Alternative
            "Rock music": "Rock", "Heavy metal": "Rock", "Punk rock": "Rock", "Alternative rock": "Rock", "Indie rock": "Rock",
            # Pop
            "Pop music": "Pop",
            # Classical
            "Classical music": "Classical", "Orchestra": "Classical", "Symphony": "Classical",
            # Hip-Hop / R&B
            "Hip hop music": "Hip-Hop", "Rhythm and blues": "Hip-Hop", "Funk": "Hip-Hop",
            # Jazz
            "Jazz": "Jazz", "Swing music": "Jazz", "Blues": "Jazz",
            # Acoustic / Folk
            "Folk music": "Acoustic", "Country": "Acoustic", "Acoustic guitar": "Acoustic", "Piano": "Acoustic",
            # Ambient / Chill
            "Ambient music": "Ambient", "Chill-out music": "Ambient",
            # Vocal
            "Singing": "Singing", "Choir": "Singing", "Opera": "Singing", "Chant": "Singing", "Mantra": "Singing", "Vocal music": "Singing",
            # Broad Categories
            "Music": "Music", "Musical instrument": "Music",
            # Non-Music
            "Speech": "Speech", "Narration, monologue": "Speech", "Male speech, man speaking": "Speech", "Female speech, woman speaking": "Speech",
            "Movie": "Movie", "Film": "Movie", "Video game music": "Movie"
        }

    def _on_detection(self, out: Dict):
        if not self.is_adaptive_enabled: return
        detections = out.get('detections')
        if not detections: return

        top_5 = {k: f'{v:.2f}' for k, v in list(detections.items())[:5]}
        logging.info(f"Analysis results: {top_5}")

        SPEECH_THRESHOLD = 0.6
        MOVIE_THRESHOLD = 0.5
        MUSIC_GENRE_THRESHOLD = 0.4
        GENERAL_MUSIC_THRESHOLD = 0.2

        chosen_profile_key = "default"
        
        speech_conf = detections.get("Speech", 0.0) + detections.get("Male speech, man speaking", 0.0) + detections.get("Female speech, woman speaking", 0.0)
        movie_conf = detections.get("Movie", 0.0) + detections.get("Film", 0.0) + detections.get("Video game music", 0.0)
        music_conf = detections.get("Music", 0.0) + detections.get("Musical instrument", 0.0)

        if speech_conf >= SPEECH_THRESHOLD:
            chosen_profile_key = "Speech"
        elif movie_conf >= MOVIE_THRESHOLD and speech_conf < SPEECH_THRESHOLD * 0.8:
            chosen_profile_key = "Movie"
        else:
            best_music_genre_conf = 0.0
            best_music_genre_key = "Music"

            for label, conf in detections.items():
                profile_category = self.genre_map.get(label)
                if profile_category and profile_category not in ["Speech", "Movie", "Music"]:
                    if conf >= MUSIC_GENRE_THRESHOLD and conf > best_music_genre_conf:
                        best_music_genre_conf = conf
                        best_music_genre_key = profile_category
            
            if best_music_genre_conf > 0:
                chosen_profile_key = best_music_genre_key
            elif music_conf >= GENERAL_MUSIC_THRESHOLD:
                chosen_profile_key = "Music" # Fallback to general music if no specific genre is strong enough

        if chosen_profile_key == "default":
            logging.info(f"Undecided. No strong classification. Current profile: {self.current_profile_key}. No change.")
            self.hysteresis_candidate = None; return

        now = time.time()
        if chosen_profile_key == self.current_profile_key:
            self.hysteresis_candidate = None; return

        if chosen_profile_key == self.hysteresis_candidate:
            if (now - self.potential_class_start_time >= self.hysteresis_delay) and \
               (now - self.last_switch_time >= self.cooldown_period):
                logging.info(f"✅ Transition confirmed to profile: '{chosen_profile_key}'")
                target_profile = self.eq_profiles.get(chosen_profile_key)
                if target_profile: self.start_transition_to_profile(target_profile)
                self.current_profile_key, self.last_switch_time, self.hysteresis_candidate = chosen_profile_key, now, None
        else:
            logging.info(f"🤔 New potential profile: '{chosen_profile_key}'. Starting stability check...")
            self.hysteresis_candidate, self.potential_class_start_time = chosen_profile_key, now

    def _merge_eq(self, base_eq: Dict, profile: EQProfile) -> Dict:
        """BUGFIXED: Correctly unpacks the merged filter dictionary."""
        merged = { 'pre_gain_db': base_eq.get('pre_gain_db', 0.0), 'bass_gain_db': base_eq.get('bass_gain_db', 0.0) + profile.bass, 'treble_gain_db': base_eq.get('treble_gain_db', 0.0) + profile.treble }
        base_filters = [
            {'freq': f, 'gain': g, 'q': q, 'type': t} for f, g, q, t in zip(
                base_eq.get('bands', []), base_eq.get('gains', []),
                base_eq.get('q_values', []), base_eq.get('filter_types', [])
            )
        ]
        for p_band in profile.bands:
            closest = min(base_filters, key=lambda b: abs(np.log10(b['freq']) - np.log10(p_band['freq']))) if base_filters else None
            if closest and (closest['freq'] / 1.5 < p_band['freq'] < closest['freq'] * 1.5):
                closest['gain'] += p_band['gain']
            else:
                base_filters.append(p_band)
        base_filters.sort(key=lambda x: x['freq'])
        
        merged['bands'] = [f['freq'] for f in base_filters]
        merged['gains'] = [f['gain'] for f in base_filters]
        merged['q_values'] = [f['q'] for f in base_filters]
        merged['filter_types'] = [f['type'] for f in base_filters]
        return merged

    def enable_adaptive_filter(self):
        if self.is_adaptive_enabled: return
        try: self.original_eq_settings = self.audio_engine.get_current_config(); logging.info("Original EQ saved.")
        except Exception as e: self.original_eq_settings = None; logging.warning(f"Could not save EQ: {e}")
        self.rtgd.start()
        self.is_adaptive_enabled = True
        try:
            warnings.filterwarnings('ignore', category=SoundcardRuntimeWarning)
            import soundcard as sc
            logging.info("Attempting loopback capture...")
            speaker = sc.default_speaker()
            mic = next((m for m in sc.all_microphones(include_loopback=True) if speaker.name in m.name), sc.default_microphone())
            logging.info(f"Using mic: {mic.name}")
            def record_loop(recorder, rtgd):
                while self.is_adaptive_enabled:
                    try: rtgd.enqueue_audio(recorder.record(numframes=4096), recorder.samplerate)
                    except Exception as e: logging.error(f"Record loop error: {e}"); time.sleep(1)
            self.recorder = mic.recorder(samplerate=48000, channels=1)
            self.recorder.__enter__()
            self.record_thread = threading.Thread(target=record_loop, args=(self.recorder, self.rtgd), daemon=True)
            self.record_thread.start()
            logging.info("Adaptive filter enabled.")
        except Exception as e:
            logging.error(f"Capture failed: {e}", exc_info=True)
            self.rtgd.stop(); self.is_adaptive_enabled = False

    def disable_adaptive_filter(self):
        if not self.is_adaptive_enabled: return
        self.is_adaptive_enabled = False
        self.rtgd.stop()
        if self.record_thread: self.record_thread.join(timeout=1.0)
        if self.recorder: self.recorder.__exit__(None, None, None)
        logging.info("Adaptive filter disabled.")
        if self.original_eq_settings:
            logging.info("Restoring original EQ.")
            self.start_transition(self.audio_engine.get_current_config(), self.original_eq_settings, duration=1.0)
            self.original_eq_settings = None
        self.current_profile_key = "default"

    def start_transition_to_profile(self, target_profile: EQProfile):
        if self.original_eq_settings is None: logging.warning("Original EQ missing, cannot transition."); return
        self.start_transition(self.audio_engine.get_current_config(), self._merge_eq(self.original_eq_settings, target_profile), 2.0)

    def start_transition(self, start_eq: Dict, end_eq: Dict, duration: float = 1.0):
        if self.transition_thread and self.transition_thread.is_alive():
            self.stop_transition_event.set(); self.transition_thread.join()
        self.stop_transition_event.clear()
        self.transition_thread = threading.Thread(target=self._run_transition_loop, args=(start_eq, end_eq, duration, self.stop_transition_event), daemon=True)
        self.transition_thread.start()

    def _run_transition_loop(self, start_eq: Dict, end_eq: Dict, duration: float, stop_event: threading.Event):
        steps = int(50 * duration)
        if steps == 0: return
        interval = duration / steps
        s_p, e_p = {k: start_eq.get(k, 0.0) for k in ['pre_gain_db','bass_gain_db','treble_gain_db']}, {k: end_eq.get(k, 0.0) for k in ['pre_gain_db','bass_gain_db','treble_gain_db']}
        all_freqs = sorted(list(set(start_eq.get('bands', [])) | set(end_eq.get('bands', []))))
        def get_p(eq, f):
            g = np.interp(f, eq.get('bands', []), eq.get('gains', [])) if eq.get('bands') else np.zeros_like(f, dtype=float)
            q = np.interp(f, eq.get('bands', []), eq.get('q_values',[])) if eq.get('bands') else np.ones_like(f, dtype=float)
            return g, q
        s_g, s_q = get_p(start_eq, all_freqs); e_g, e_q = get_p(end_eq, all_freqs)
        e_t = {f: t for f, t in zip(end_eq.get('bands', []), end_eq.get('filter_types', []))}
        f_t = [e_t.get(f, 'PK') for f in all_freqs]
        for i in range(steps + 1):
            if stop_event.is_set(): return
            p = i / steps
            try:
                for k in s_p: setattr(self.audio_engine, k, float(s_p[k] + (e_p[k] - s_p[k]) * p))
                self.audio_engine.bands, self.audio_engine.band_count = list(all_freqs), len(all_freqs)
                self.audio_engine.gains = np.array(s_g + (e_g - s_g) * p, dtype=float)
                self.audio_engine.q_values = np.array(s_q + (e_q - s_q) * p, dtype=float)
                self.audio_engine.filter_types = list(f_t)
                self.audio_engine.send_full_ui_update()
                if getattr(self.audio_engine, 'is_playing', False): self.audio_engine._apply_apo_config()
            except Exception: pass
            time.sleep(interval)