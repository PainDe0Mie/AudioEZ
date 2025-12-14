import json, os, sys, csv
import numpy as np
from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QFileDialog

import config

class AudioEngine(QObject):
    def __init__(self):
        super().__init__()

        from config_manager import ConfigManager

        self.py_channel = None
        self.is_playing = False
        
        self.bands = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        self.band_count = len(self.bands)  
        self.gains = np.zeros(len(self.bands))
        self.q_values = np.full(len(self.bands), 1.41)
        self.filter_types = ['PK'] * len(self.bands)
        
        self.pre_gain_db = 0.0
        self.bass_gain_db = 0.0
        self.treble_gain_db = 0.0

        self.config_manager = ConfigManager(self)
        self.config_manager.load_configs()

        self.AUTOEQ_CACHE_DIR = os.path.join(config.APP_CONFIGS_DIR, "autoeq_profiles")
        os.makedirs(self.AUTOEQ_CACHE_DIR, exist_ok=True)

        self.autoeq_cache_timestamp = None
        self.autoeq_models = []
        os.makedirs(self.AUTOEQ_CACHE_DIR, exist_ok=True)

        print("AudioEngine: Initialized.")

    def load_config(self, config_name):
        """Charge la configuration spécifiée ou la configuration par défaut"""
        config_data = self.config_manager.get_config_data(config_name)
        
        is_default_or_missing = config_name.lower() == "default" or not config_data
        
        if is_default_or_missing:
            num_bands = len(self.bands) if hasattr(self, 'bands') and self.bands else 10
            
            self.pre_gain_db = 0.0
            self.bass_gain_db = 0.0
            self.treble_gain_db = 0.0
            self.gains = np.zeros(num_bands).tolist()
            self.q_values = np.full(num_bands, 1.41).tolist()
            self.filter_types = ['PK'] * num_bands
            self.config_manager.set_active_config("Default")
            self.send_full_ui_update()
            if self.is_playing: self._apply_apo_config()
            self.py_channel.statusUpdate.emit("Configuration 'Default' (flat) loaded.")
            return

        self.pre_gain_db = config_data.get('pre_gain_db', 0.0)
        self.bass_gain_db = config_data.get('bass_boost', 0.0)
        self.treble_gain_db = config_data.get('treble_boost', 0.0)
        self.gains = np.array(config_data.get('gains', np.zeros(len(self.bands)).tolist()))
        self.bands = config_data.get('bands', self.bands)
        self.q_values = np.array(config_data.get('q_values', np.full(len(self.bands), 1.41).tolist()))
        self.filter_types = config_data.get('filter_types', ['PK'] * len(self.bands))
        self.config_manager.set_active_config(config_name)
        self.send_full_ui_update()
        if self.is_playing: self._apply_apo_config()
        self.py_channel.statusUpdate.emit(f"Configuration '{config_name}' loaded.")

    def log_message(self, message):
        print(f"AudioEngine: {message}")

    def filter_valid_autoeq_models(self, models, measurements_root="measurements"): 
        """Filtre les modèles AutoEQ valides"""
        valid_models = []
        invalid_models = []

        available_csv_models = set()
        for author_folder in os.listdir(measurements_root):
            data_path = os.path.join(measurements_root, author_folder, "data")
            if not os.path.exists(data_path):
                continue

            for category_folder in os.listdir(data_path):
                cat_path = os.path.join(data_path, category_folder)
                if not os.path.isdir(cat_path):
                    continue

                for file in os.listdir(cat_path):
                    if file.lower().endswith(".csv"):
                        base = os.path.splitext(file)[0].lower()
                        available_csv_models.add(base)

        for model_name in models:
            base_name = os.path.basename(model_name).lower()
            if base_name in available_csv_models:
                valid_models.append(model_name)
            else:
                invalid_models.append(model_name)

        return sorted(valid_models), sorted(invalid_models)

    def fetch_autoeq_index(self, force_refresh=False):
        """Récupère les modèles AutoEQ avec cache local"""
        measurements_root = "measurements"
        cache_dir = os.path.join(self.AUTOEQ_CACHE_DIR, "autoeq_cache")
        cache_path = os.path.join(cache_dir, "index.json")

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        if not force_refresh and os.path.isfile(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    cached_models = cache_data.get('data', [])
                    if cached_models:
                        self.autoeq_index = cached_models
                        self.log_message(f"{len(cached_models)} modèles AutoEQ chargés depuis le cache.")
                        if self.py_channel:
                            self.py_channel.autoeqModelsUpdated.emit(cached_models)
                        return cached_models
            except Exception as e:
                self.log_message(f"Erreur lecture cache AutoEQ : {e}")

        models = set()

        if not os.path.exists(measurements_root):
            self.log_message(f"Répertoire {measurements_root} introuvable.")
            return []

        for folder in os.listdir(measurements_root):
            index_path = os.path.join(measurements_root, folder, "name_index.tsv")
            if not os.path.isfile(index_path):
                continue

            try:
                with open(index_path, newline='', encoding='utf-8') as tsvfile:
                    reader = csv.DictReader(tsvfile, delimiter='\t')
                    for row in reader:
                        model_name = row.get('model') or row.get('Model') or row.get('name') or row.get('Name')
                        if model_name:
                            models.add(model_name.strip())
            except Exception as e:
                self.log_message(f"Erreur lecture {index_path} : {e}")

        valid_models, invalid_models = self.filter_valid_autoeq_models(models, measurements_root)

        self.autoeq_index = sorted(valid_models)

        self.log_message(f"{len(valid_models)} modèles valides chargés. {len(invalid_models)} ignorés.")
        if invalid_models:
            self.log_message(f"Modèles ignorés (sans fichier .csv) : {invalid_models}")

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({'data': self.autoeq_index}, f, indent=2, ensure_ascii=False)
            self.log_message(f"Cache AutoEQ sauvegardé dans : {cache_path}")
        except Exception as e:
            self.log_message(f"Erreur sauvegarde cache AutoEQ : {e}")

        if self.py_channel:
            self.py_channel.autoeqModelsUpdated.emit(self.autoeq_index)

        return self.autoeq_index
        
    def fetch_object_curve(self, object_name):
        """Récupère la courbe de réponse pour un objet donné"""
        from autoeq.frequency_response import FrequencyResponse
        import os
        import numpy as np

        if not object_name:
            self.log_message("[FetchCurve] Aucun nom d'objet fourni.")
            return

        print(f"[FetchCurve] Chargement de : {object_name}")

        measurements_root = "measurements"
        targets_root = "targets"
        
        try:
            if '/' in object_name or '\\' in object_name:
                parts = object_name.replace('\\', '/').split('/')
                if len(parts) < 2:
                    raise ValueError(f"Format de target inattendu : {object_name}")

                target_csv_path = os.path.join(measurements_root, parts[0], "data", *parts[1:-1], parts[-1] + ".csv")
                if not os.path.exists(target_csv_path):
                    raise FileNotFoundError(f"Fichier cible introuvable dans measurements: {target_csv_path}")

                target_fr = FrequencyResponse.read_csv(target_csv_path)
                target_fr.interpolate()
                target_fr.center()

                self.log_message(f"[FetchCurve] Cible chargée (measurements) : {object_name}")
                if self.py_channel and hasattr(self.py_channel, 'targetCurveUpdate'):
                    self.py_channel.target_name = object_name
                    self.py_channel.targetCurveUpdate.emit(target_fr.frequency.tolist(), target_fr.raw.tolist())

            else:
                target_csv_path = os.path.join(targets_root, f"{object_name}.csv")
                if os.path.exists(target_csv_path):
                    target_fr = FrequencyResponse.read_csv(target_csv_path)
                    target_fr.interpolate()
                    target_fr.center()

                    self.log_message(f"[FetchCurve] Cible chargée (targets) : {object_name}")
                    if self.py_channel and hasattr(self.py_channel, 'targetCurveUpdate'):
                        self.py_channel.target_name = object_name
                        self.py_channel.targetCurveUpdate.emit(target_fr.frequency.tolist(), target_fr.raw.tolist())
                else:
                    model_base_name = os.path.basename(object_name).lower()
                    measurement_files = []

                    for author_folder in os.listdir(measurements_root):
                        data_path = os.path.join(measurements_root, author_folder, "data")
                        if not os.path.exists(data_path):
                            continue
                        for category_folder in os.listdir(data_path):
                            cat_path = os.path.join(data_path, category_folder)
                            if not os.path.isdir(cat_path):
                                continue
                            for file in os.listdir(cat_path):
                                if file.lower().endswith(".csv") and os.path.splitext(file)[0].lower() == model_base_name:
                                    measurement_files.append(os.path.join(cat_path, file))

                    if not measurement_files:
                        self.log_message(f"[FetchCurve] Aucun fichier de mesure trouvé pour {object_name}")
                        if self.py_channel:
                            self.py_channel.statusUpdate.emit(f"Measurement file missing for {object_name}.")
                        return

                    responses = []
                    for csv_file in measurement_files:
                        fr = FrequencyResponse.read_csv(csv_file)
                        fr.interpolate()
                        fr.center()
                        if fr.raw.size > 0:
                            responses.append(fr)

                    if not responses:
                        raise ValueError("Aucune réponse fréquentielle valide trouvée pour la moyenne.")

                    min_len = min(len(fr.frequency) for fr in responses)
                    frequency = responses[0].frequency[:min_len]
                    avg_raw = np.mean([fr.raw[:min_len] for fr in responses], axis=0)

                    avg_fr = FrequencyResponse(name=f"{object_name} (average)", frequency=frequency, raw=avg_raw)
                    avg_fr.interpolate()
                    avg_fr.center()

                    self.log_message(f"[FetchCurve] Écouteur chargé : {object_name}")
                    if self.py_channel and hasattr(self.py_channel, 'EarphonesCurve'):
                        self.py_channel.earphone_name = object_name
                        self.py_channel.EarphonesCurve.emit(avg_fr.frequency.tolist(), avg_fr.raw.tolist())

        except Exception as e:
            import traceback
            self.log_message(f"[FetchCurve] Erreur lors du chargement de {object_name} : {e}\n{traceback.format_exc()}")
            if self.py_channel:
                self.py_channel.statusUpdate.emit(f"Error loading curve for {object_name}.")

        eq_parametric_data = {
            "preamp": self.pre_gain_db,
            "bass_boost": self.bass_gain_db,
            "treble_boost": self.treble_gain_db,
            "filters": [
                {"type": t, "gain": g, "q": q, "freq": b}
                for b, g, q, t in zip(self.bands, self.gains, self.q_values, self.filter_types)
            ]
        }

        from config_save import save_to_aez_file

        save_to_aez_file(
            filepath=f"{config.APP_CONFIGS_DIR}/temp_.aez",
            eq_parametric=eq_parametric_data,
            earphone_name=self.py_channel.earphone_name,
            earphone_curve=[self.py_channel._earphones_curve_freq, self.py_channel._earphones_curve_amp],
            target_name=self.py_channel.target_name,
            target_curve=[self.py_channel._target_curve_freq, self.py_channel._target_curve_amp]
        )

        self.calculate_frequency_response()

    def apply_autoeq_profile(self, model_name, target=None, band_size=10):
        """Applique un profil AutoEQ à l'égaliseur"""
        from autoeq.frequency_response import FrequencyResponse
        from autoeq.peq import PEQ
        from autoeq.constants import PEQ_CONFIGS, DEFAULT_FS, DEFAULT_MAX_GAIN, DEFAULT_MAX_SLOPE, \
            DEFAULT_TREBLE_F_LOWER, DEFAULT_TREBLE_F_UPPER, DEFAULT_TREBLE_GAIN_K
        
        self.py_channel.statusUpdate.emit("AutoEQ, please wait...")

        self.log_message(f"Application AutoEQ locale: {model_name} → cible: {target or 'par défaut'}")

        model_base_name = os.path.basename(model_name)
        measurements_root = "measurements"
        measurement_files = []
        for author_folder in os.listdir(measurements_root):
            data_path = os.path.join(measurements_root, author_folder, "data")
            if not os.path.exists(data_path): continue
            for category_folder in os.listdir(data_path):
                cat_path = os.path.join(data_path, category_folder)
                if not os.path.isdir(cat_path): continue
                for file in os.listdir(cat_path):
                    if file.lower().endswith(".csv") and os.path.splitext(file)[0].lower() == model_base_name.lower():
                        measurement_files.append(os.path.join(cat_path, file))
        
        if not measurement_files:
            self.log_message(f"Aucun fichier de mesure trouvé pour {model_name}")
            self.py_channel.statusUpdate.emit(f"Measurement file missing for {model_name}.")
            return

        self.py_channel.earphone_name = model_name
        self.py_channel.target_name = target

        try:
            responses = []
            for csv_file in measurement_files:
                fr = FrequencyResponse.read_csv(csv_file)
                fr.interpolate()
                fr.center()
                if fr.raw.size > 0:
                    responses.append(fr)

            if not responses:
                raise ValueError("Aucune réponse fréquentielle valide trouvée pour la moyenne.")

            min_len = min(len(fr.frequency) for fr in responses)
            frequency = responses[0].frequency[:min_len]
            avg_raw = np.mean([fr.raw[:min_len] for fr in responses], axis=0)
            
            avg_fr = FrequencyResponse(name=f"{model_name} (average)", frequency=frequency, raw=avg_raw)
            avg_fr.interpolate()
            avg_fr.center()

            if self.py_channel and hasattr(self.py_channel, 'EarphonesCurve'):
                self.py_channel.EarphonesCurve.emit(avg_fr.frequency.tolist(), avg_fr.raw.tolist())

            if not target:
                return None
            if '/' in target or '\\' in target:
                parts = target.replace('\\', '/').split('/')
                if len(parts) < 2:
                    raise ValueError(f"Format de target inattendu : {target}")
                target_csv_path = os.path.join("measurements", parts[0], "data", *parts[1:-1], parts[-1] + ".csv")
            else:
                target_csv_path = os.path.join("targets", f"{target}.csv")

            print(f"Chemin de fichier cible vérifié : {target_csv_path}")
            print(f"Le fichier existe-t-il ? {os.path.exists(target_csv_path)}")

            if not target_csv_path or not os.path.exists(target_csv_path):
                raise ValueError(f"Fichier de cible introuvable ou invalide : {target_csv_path}")

            target_fr = FrequencyResponse.read_csv(target_csv_path)
            target_fr.interpolate()
            target_fr.center()
            
            avg_fr.compensate(target_fr, min_mean_error=True)
            avg_fr.smoothen()
            avg_fr.equalize(
                max_gain=DEFAULT_MAX_GAIN,
                max_slope=DEFAULT_MAX_SLOPE,
                treble_f_lower=DEFAULT_TREBLE_F_LOWER,
                treble_f_upper=DEFAULT_TREBLE_F_UPPER,
                treble_gain_k=DEFAULT_TREBLE_GAIN_K
            )

            peq_config = PEQ_CONFIGS['8_PEAKING_WITH_SHELVES']
            
            peq = PEQ.from_dict(
                config=peq_config,
                f=avg_fr.frequency,
                fs=DEFAULT_FS,
                target=avg_fr.equalization
            )
            
            peq.optimize()
            
            if peq.filters and len(peq.filters) == band_size:
                preamp = -peq.max_gain if peq.max_gain > 0 else 0.0
            
                self.pre_gain_db = preamp
                self.bands = [filt.fc for filt in peq.filters]
                self.band_count = len(self.bands) 
                self.gains = [filt.gain for filt in peq.filters]
                self.q_values = [filt.q for filt in peq.filters]
                filter_name_map = {
                    'LowShelf': 'LS',
                    'HighShelf': 'HS',
                    'Peaking': 'PK',
                    'LowPass': 'LP',
                    'HighPass': 'HP',
                    'BandPass': 'BP',
                    'Notch': 'NO',
                    'AllPass': 'AP'
                }
                self.filter_types = [filter_name_map.get(type(filt).__name__, type(filt).__name__) for filt in peq.filters]
                                    
                self.log_message(f"Optimisation réussie avec {len(peq.filters)} filtres.")
            else:
                self.log_message(f"Erreur d'optimisation PEQ : l'optimisation a produit {len(peq.filters)} filtres au lieu de 10.")
                self.bands = []
                self.band_count = 0
                self.gains = []
                self.q_values = []
                self.filter_types = []
            
            if self.py_channel and hasattr(self.py_channel, 'targetCurveUpdate'):
                self.py_channel.targetCurveUpdate.emit(target_fr.frequency.tolist(), target_fr.raw.tolist())

        except Exception as e:
            import traceback
            self.log_message(f"Erreur retarget AutoEQ local: {e}\n{traceback.format_exc()}")
            if self.py_channel:
                self.py_channel.statusUpdate.emit(f"Error recalcul AutoEQ for {model_name}.")
            return

        self.send_full_ui_update()
        if self.is_playing:
            self._apply_apo_config()
        self.py_channel.statusUpdate.emit(f"'{model_base_name}' retarget → {target}")

    def set_channel(self, channel):
        self.py_channel = channel
        print("AudioEngine: Python channel updated.")
    
    def check_apo_config(self):
        
        if not os.path.exists(config.EAPO_CONFIG_PATH):
            msg = f"ERROR: Equalizer APO configuration file not found at the default location: {config.EAPO_CONFIG_PATH}. "
            print(msg, file=sys.stderr)
            if self.py_channel:
                self.py_channel.statusUpdate.emit(msg)
            return False
        return True

    def _update_and_emit_playback_state(self):
        if self.py_channel:
            self.py_channel.playbackStateChanged.emit(self.is_playing)
            print(f"AudioEngine: Playback state updated to {self.is_playing}.")

    def write_disabled_config(self):
        """Écrit une configuration désactivée dans config.txt"""
        config_path = self.get_config_path()
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write("# AudioEZ - Equalizer Disabled\n")
                f.write("Preamp: 0 dB\n")
                for i in range(1, 11):
                    f.write(f"Filter {i}: OFF None\n")
            
            print("Configuration EQ APO désactivée avec succès")
            return True
        except Exception as e:
            print(f"Erreur écriture config désactivée: {e}")
            return False
    
    def backup_config(self):
        config_path = self.get_config_path()
        backup_path = config_path.with_suffix('.txt.bak')
        
        try:
            if config_path.exists():
                import shutil
                shutil.copy2(config_path, backup_path)
                return True
        except Exception as e:
            print(f"Error save config: {e}")
            return False
    
    def restore_config(self):
        config_path = self.get_config_path()
        backup_path = config_path.with_suffix('.txt.bak')
        
        try:
            if backup_path.exists():
                import shutil
                shutil.copy2(backup_path, config_path)
                return True
        except Exception as e:
            print(f"Error restauration config: {e}")
            return False

    def _apply_apo_config(self):
        if not self.check_apo_config():
            return

        print("AudioEngine: Updating Equalizer APO configuration file...")

        try:
            config_lines = [f"Preamp: {self.pre_gain_db:.1f} dB"]

            for i in range(len(self.bands)):
                filter_type = self.filter_types[i]
                fc = self.bands[i]
                gain = self.gains[i]
                q = self.q_values[i]

                if filter_type.upper() in ['LS', 'HS', 'LSQ', 'HSQ']:
                    config_lines.append(
                        f"Filter {i+1}: ON {filter_type} Fc {fc} Hz Gain {gain:.1f} dB Q {q:.2f}"
                    )
                else:
                    config_lines.append(
                        f"Filter {i+1}: ON {filter_type} Fc {fc} Hz Gain {gain:.1f} dB Q {q:.2f}"
                    )

            filter_index = len(self.bands) + 1

            if hasattr(self, "bass_gain_db") and self.bass_gain_db != 0:
                bass_q = getattr(self, "bass_q", 0.71)
                config_lines.append(
                    f"Filter {filter_index}: ON LS Fc 100 Hz Gain {self.bass_gain_db:.1f} dB Q {bass_q:.2f}"
                )
                filter_index += 1

            if hasattr(self, "treble_gain_db") and self.treble_gain_db != 0:
                treble_q = getattr(self, "treble_q", 0.71)
                config_lines.append(
                    f"Filter {filter_index}: ON HS Fc 8000 Hz Gain {self.treble_gain_db:.1f} dB Q {treble_q:.2f}"
                )

            with open(config.EAPO_CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(config_lines))

            print("AudioEngine: Equalizer APO configuration file updated.")

        except IOError as e:
            error_msg = (
                "Permission error: Cannot write to Equalizer APO config file. \nPlease run the application as administrator."
                if e.errno == 13 else f"Error updating Equalizer APO configuration: {e}"
            )
            if self.py_channel:
                self.py_channel.statusUpdate.emit(error_msg)
            print(error_msg, file=sys.stderr)

        except Exception as e:
            error_msg = f"Error updating Equalizer APO configuration: {e}"
            if self.py_channel:
                self.py_channel.statusUpdate.emit(error_msg)
            print(error_msg, file=sys.stderr)

    def calculate_frequency_response(self):
        """Calcule et met à jour la réponse fréquentielle"""
        freqs = np.logspace(np.log10(20), np.log10(20000), 512)

        valid_triplets = [
            (b, g, q, t)
            for b, g, q, t in zip(self.bands, self.gains, self.q_values, self.filter_types)
            if b is not None and g is not None and q is not None and t is not None
        ]

        if valid_triplets and self.py_channel:
            bands, gains, q_values, filter_types = zip(*valid_triplets)

            eq_parametric_data = {
                "preamp": self.pre_gain_db,
                "bass_boost": self.bass_gain_db,
                "treble_boost": self.treble_gain_db,
                "filters": [
                    {"type": t, "gain": g, "q": q, "freq": b}
                    for b, g, q, t in zip(bands, gains, q_values, filter_types)
                ]
            }

            from config_save import save_to_aez_file

            save_to_aez_file(
                filepath=f"{config.APP_CONFIGS_DIR}/temp_.aez",
                eq_parametric=eq_parametric_data,
                earphone_name=self.py_channel.earphone_name,
                earphone_curve=[self.py_channel._earphones_curve_freq, self.py_channel._earphones_curve_amp],
                target_name=self.py_channel.target_name,
                target_curve=[self.py_channel._target_curve_freq, self.py_channel._target_curve_amp]
            )

            self.py_channel.frequencyResponseUpdate.emit(
                list(map(float, freqs)),
                list(map(float, bands)),
                list(map(float, gains)),
                list(map(float, q_values)),
                list(filter_types)
            )
        else:
            print("⚠️ Aucun triplet (band, gain, q, type) complet valide trouvé.")

    def start_playback(self):
        if self.is_playing:
            return
        
        if not self.check_apo_config():
            return
        
        self.is_playing = True
        self._apply_apo_config()
        
        if self.py_channel:
            self.py_channel.statusUpdate.emit("Equalizer is active.")
        self._update_and_emit_playback_state()

    def stop_playback(self):
        if not self.is_playing:
            print("AudioEngine: Equalizer is not active.")
            return
        
        if not self.check_apo_config():
            return
        
        self.is_playing = False
        
        try:
            import config
            
            with open(config.EAPO_CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write("Preamp: 0 dB\n")
                for i in range(1, 11):
                    f.write(f"Filter {i}: OFF None\n")

        except Exception as e:
            error_msg = f"Error disabling Equalizer APO: {e}"
            if self.py_channel:
                self.py_channel.statusUpdate.emit(error_msg)
            print(error_msg, file=sys.stderr)
        
        if self.py_channel:
            self.py_channel.statusUpdate.emit("AudioEZ disabled.")
        self._update_and_emit_playback_state()

    def set_gain_and_frequency(self, band_index, gain_db, frequency):
        """Définit le gain et la fréquence pour une bande spécifique"""
        if 0 <= band_index < len(self.gains):
            self.gains[band_index] = gain_db
            self.bands[band_index] = frequency
            print(f"AudioEngine: Setting band {band_index} to Gain={gain_db} dB, Freq={frequency} Hz.")
            if self.is_playing:
                self._apply_apo_config()
            self.calculate_frequency_response()
        else:
            print(f"AudioEngine: Invalid band index: {band_index}")

    def set_pre_gain(self, pre_gain_db):
        print(f"AudioEngine: Setting pre-amp to {pre_gain_db} dB.")
        self.pre_gain_db = pre_gain_db
        if self.is_playing:
            self._apply_apo_config()
        self.calculate_frequency_response()
    
    def set_bass_gain(self, gain_db):
        print(f"AudioEngine: Setting bass gain to {gain_db} dB.")
        self.bass_gain_db = gain_db
        if self.is_playing:
            self._apply_apo_config()
        self.calculate_frequency_response()
    
    def set_treble_gain(self, gain_db):
        print(f"AudioEngine: Setting treble gain to {gain_db} dB.")
        self.treble_gain_db = gain_db
        if self.is_playing:
            self._apply_apo_config()
        self.calculate_frequency_response()

    def reset_gains(self):
        print("AudioEngine: Resetting all gains.")
        self.bands = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        self.band_count = len(self.bands)  
        self.gains = np.zeros(len(self.bands))
        self.q_values = np.full(len(self.bands), 1.41)
        self.filter_types = ['PK'] * len(self.bands)
        self.pre_gain_db = 0.0
        self.bass_gain_db = 0.0
        self.treble_gain_db = 0.0
        if self.is_playing:
            self._apply_apo_config()
        self.send_full_ui_update()
        
    def send_full_ui_update(self):
        print("AudioEngine: Sending a complete UI update.")
        if self.py_channel:
            self.py_channel.preampGainChanged.emit(self.pre_gain_db)
            self.py_channel.bassGainChanged.emit(self.bass_gain_db)
            self.py_channel.trebleGainChanged.emit(self.treble_gain_db)
            self.py_channel.configListUpdate.emit(self.config_manager.get_config_names(), self.config_manager.active_config)
        self.calculate_frequency_response()

    def get_current_config(self):
        gains_list = self.gains.tolist() if hasattr(self.gains, 'tolist') else self.gains
        q_values_list = self.q_values.tolist() if hasattr(self.q_values, 'tolist') else self.q_values

        config = {
            'pre_gain_db': self.pre_gain_db,
            'bass_gain_db': self.bass_gain_db,
            'treble_gain_db': self.treble_gain_db,
            'bands': self.bands,
            'gains': gains_list,
            'q_values': q_values_list,
            'filter_types': self.filter_types
        }

        if hasattr(self.py_channel, '_target_curve_freq') and hasattr(self.py_channel, '_target_curve_amp'):
            config['target_curve'] = {
                'frequency': self.py_channel._target_curve_freq,
                'amplitude': self.py_channel._target_curve_amp
            }

        if hasattr(self.py_channel, '_earphones_curve_freq') and hasattr(self.py_channel, '_earphones_curve_amp'):
            config['original_curve'] = {
                'frequency': self.py_channel._earphones_curve_freq,
                'amplitude': self.py_channel._earphones_curve_amp
            }

        return config

    def load_config(self, config_name):
        if config_name == "Default":
            self.reset_gains()
            self.config_manager.set_active_config("Default")
            return

        config_data = self.config_manager.load_config_by_name(config_name)
        if config_data:
            self.pre_gain_db = config_data.get('pre_gain_db', 0.0)
            self.bass_gain_db = config_data.get('bass_gain_db', 0.0)
            self.treble_gain_db = config_data.get('treble_gain_db', 0.0)
            self.gains = np.array(config_data.get('gains', np.zeros(len(self.bands)).tolist()))
            self.bands = config_data.get('bands', self.bands)
            self.q_values = np.array(config_data.get('q_values', np.full(len(self.bands), 1.41).tolist()))
            self.filter_types = config_data.get('filter_types', ['PK'] * len(self.bands)) 

            self.config_manager.set_active_config(config_name)
            self.send_full_ui_update()
            if self.is_playing:
                self._apply_apo_config()
            self.py_channel.statusUpdate.emit(f"Configuration loaded.")
        else:
            self.py_channel.statusUpdate.emit(f"Error: Configuration not found.")

    def save_config(self, config_name):
        config_data = self.get_current_config()
        self.config_manager.save_config(config_name, config_data)
        self.py_channel.statusUpdate.emit(f"Configuration '{config_name}' saved.")

    def export_config(self, export_data):
        try:
            
            suggested_file_name = export_data.get('suggestedFileName', 'config.aez')
            export_type = export_data.get('exportType', 'audioez')
            
            print(f"AudioEngine: Exportation de la configuration avec les données: {export_data}")

            if export_type == 'audioez':
                extension = '.aez'
                name_filter = f"AudioEZ Config File (*{extension});;Equalizer APO Config (*.txt);;Peace Config (*.peace);;Wavelet Config (*.json *.wavelet);;All Files (*)"
            
            elif export_type == 'equalizerapo':
                extension = '.txt'
                name_filter = f"Equalizer APO Config (*{extension});;Peace Config (*.peace);;AudioEZ Config File (*.aez);;Wavelet Config (*.json *.wavelet);;All Files (*)"
            
            elif export_type == 'peace': 
                extension = '.peace'
                name_filter = f"Peace Config (*{extension});;Equalizer APO Config (*.txt);;AudioEZ Config File (*.aez);;Wavelet Config (*.json *.wavelet);;All Files (*)"
            
            elif export_type == 'wavelet':
                extension = '.json'
                name_filter = f"Wavelet/JSON Config (*{extension} *.wavelet);;Equalizer APO/Peace Config (*.txt *.peace);;AudioEZ Config File (*.aez);;All Files (*)"
            
            elif export_type == 'wavelet2':
                extension = '.wavelet'
                name_filter = f"Wavelet/JSON Config (*{extension} *.json);;Equalizer APO/Peace Config (*.txt *.peace);;AudioEZ Config File (*.aez);;All Files (*)"
            
            else:
                extension = '.aez'
                name_filter = f"EQ Files (*.aez *.txt *.peace *.json *.wavelet);;All Files (*)"

            base_name = os.path.splitext(suggested_file_name)[0]
            suggested_file_name = base_name + extension

            file_dialog = QFileDialog()
            file_dialog.setAcceptMode(QFileDialog.AcceptSave)
            file_dialog.setWindowTitle("Sauvegarder la configuration de l'égaliseur")
            
            file_name, _ = file_dialog.getSaveFileName(
                None,
                "Enregistrer la configuration",
                suggested_file_name,
                name_filter
            )

            if not file_name:
                print("AudioEngine: Exportation annulée par l'utilisateur.")
                self.py_channel.statusUpdate.emit("Exportation annulée.")
                return

            active_config_data = {
                "pre_gain_db": self.pre_gain_db, 
                "bass_gain_db": self.bass_gain_db,
                "treble_gain_db": self.treble_gain_db,
                "bands": [b for b in self.bands],
                "gains": [g for g in self.gains],
                "q_values": [q for q in self.q_values],
                "filter_types": [t for t in self.filter_types]
            }
            
            self.config_manager.export_single_config(file_name, active_config_data)

            print(f"AudioEngine: Configuration exportée avec succès vers {file_name}.")
            self.py_channel.statusUpdate.emit(f"Configuration exportée vers {os.path.basename(file_name)}.")
            
        except Exception as e:
            print(f"AudioEngine: Erreur lors de l'exportation: {e}", file=sys.stderr)
            self.py_channel.statusUpdate.emit(f"L'exportation a échoué: {e}")
        
    def export_all_configs(self):
        file_path, _ = QFileDialog.getSaveFileName(
            None, 
            "Export all configurations", 
            "AudioEZ_configs.aezl",
            "AudioEZ Configuration Files (*.aezl)"
        )
        if file_path:
            self.config_manager.export_all_configs(file_path)
            self.py_channel.statusUpdate.emit(f"All configurations exported to {os.path.basename(file_path)}.")

    def import_config_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Import a configuration",
            "",
            "AudioEZ Configuration Files (*.aez);;Peace Configuration File (*.peace);;Equalizer APO text file (*.txt);;All Files (*)"
        )
        if file_path:
            self.config_manager.import_config(file_path)
            self.send_full_ui_update()
            if self.is_playing:
                self._apply_apo_config()

    def set_equalizer_point_parameter(self, index, key, value):
        TYPE_MAP = {0:"PK",1:"LP",2:"HP",3:"BP",4:"LS",5:"HS",6:"NO",7:"AP",8:"LSD",9:"HSD",10:"BWLP",11:"BWHP",12:"LRLP",13:"LRHP",14:"LSQ",15:"HSQ",16:"LSC",17:"HSC"}

        if not (0 <= index < len(self.bands)):
            print(f"[EQ] Index hors limites: {index}")
            return

        if key == "freq":
            self.bands[index] = value
        elif key == "gain":
            self.gains[index] = value
        elif key == "q":
            self.q_values[index] = value
        elif key == "type":
            filter_type = TYPE_MAP.get(int(value), "PK")
            self.filter_types[index] = filter_type
        else:
            print(f"⚠️ Paramètre EQ inconnu : {key}")

        if self.is_playing:
            self._apply_apo_config()

        self.calculate_frequency_response()