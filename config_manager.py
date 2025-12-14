import json, re, os, sys
import numpy as np
from PyQt6.QtCore import QObject

import config

class ConfigManager(QObject):
    def __init__(self, audio_engine):
        super().__init__()

        self.audio_engine = audio_engine
        self.configs = {}
        self.active_config = "Default"
        self.config_file = os.path.join(config.APP_CONFIGS_DIR, "presets.json")

    def get_config_names(self):
        return ["Default"] + [name for name in sorted(self.configs.keys()) 
                if not name.startswith("temp_")]

    def set_active_config(self, name):
        if not name == "temp_":
            self.active_config = name
            if self.audio_engine.py_channel:
                self.audio_engine.py_channel.configListUpdate.emit(self.get_config_names(), self.active_config)

    def load_configs(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.configs = json.load(f)
            except json.JSONDecodeError:
                print("Error: The presets.json file is corrupted or empty. It will be reinitialized.", file=sys.stderr)
                self.configs = {}
            except Exception as e:
                print(f"Error loading configurations: {e}", file=sys.stderr)
        self.set_active_config("Default")

    def save_configs(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.configs, f, indent=4)
                                                                               # 2048 like the game ;)
    def load_config_by_name(self, name):
        return self.configs.get(name)

    def delete_config(self, name):
        if name in self.configs:
            del self.configs[name]
            self.save_configs()
            print(f"Configuration '{name}' supprimée de presets.json.")
        else:
            print(f"La configuration '{name}' n'existe pas.")

    def save_config(self, name, data):
        self.configs[name] = data
        self.save_configs()
        self.set_active_config(name)
    
    def export_single_config(self, file_path, data):
        """
        Exporte une seule configuration dans le format spécifié par l'extension du fichier.
        Formats pris en charge: .aez (AudioEZ JSON), .txt (EqualizerAPO/Peace), .json (Wavelet)
        """
        
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        preamp_db = data.get('pre_gain_db', 0.0)
        
        filters = []

        bass_gain_db = data.get('bass_gain_db', 0.0)
        if bass_gain_db != 0.0:
            filters.append({
                'type': 'PK', 'fc': 100.0, 'gain': bass_gain_db, 'q': 0.71
            })
            
        treble_gain_db = data.get('treble_gain_db', 0.0)
        if treble_gain_db != 0.0:
            filters.append({
                'type': 'PK', 'fc': 8000.0, 'gain': treble_gain_db, 'q': 0.71
            })

        filter_types = data.get('filter_types', ['PK'] * len(data.get('bands', [])))
        for i in range(len(data.get('bands', []))):
            filters.append({
                'type': filter_types[i],
                'fc': data['bands'][i],
                'gain': data['gains'][i],
                'q': data['q_values'][i]
            })


        if ext == '.aez':
            with open(file_path, 'w') as f:
                 json.dump(data, f, indent=4)
        
        elif ext == '.txt':
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"Preamp: {preamp_db:.1f} dB\n")
                
                for i, f_data in enumerate(filters):
                    f.write(f"Filter {i+1}: ON {f_data['type']} Fc {f_data['fc']:.1f} Hz Gain {f_data['gain']:.1f} dB Q {f_data['q']:.2f}\n")
        
        elif ext == '.peace':
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("[Frequencies]\n")
                for i, f_data in enumerate(filters):
                    f.write(f"Frequency{i+1}={f_data['fc']:.0f}\n")
                
                f.write("[Gains]\n")
                for i, f_data in enumerate(filters):
                    f.write(f"Gain{i+1}={f_data['gain']:.1f}\n")
                    
                f.write("[Qualities]\n")
                for i, f_data in enumerate(filters):
                    f.write(f"Quality{i+1}={f_data['q']:.2f}\n")
                
                f.write("[General]\n")
                f.write(f"PreAmp={preamp_db:.1f}\n")
                
                f.write("Device=\n") 
                f.write("Device GUID=\n")
                f.write("[Speakers]\n")
                f.write("SpeakerId0=0\n")
                f.write("SpeakerTargets0=all\n")
                f.write("SpeakerName0=Tout\n")

        elif ext == '.json' or ext == '.wavelet':
            
            wavelet_filters = []
            for f_data in filters:

                
                wavelet_type = f_data['type'].lower()
                
                if wavelet_type == 'pk': wavelet_type = 'peaking'
                elif wavelet_type == 'lsq': wavelet_type = 'lowshelf'
                elif wavelet_type == 'hsq': wavelet_type = 'highshelf'
                
                wavelet_filters.append({
                    "type": wavelet_type,
                    "frequency": f_data['fc'],
                    "gain": f_data['gain'],
                    "q": f_data['q']
                })

            wavelet_data = {
                "preamp": preamp_db,
                "filters": wavelet_filters
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(wavelet_data, f, indent=4)
        
        else:
            raise ValueError(f"Unsupported export file format: {ext}")

    def export_all_configs(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.configs, f, indent=4)

    def import_config(self, file_path):
        try:
            filename = os.path.basename(file_path)
            name, ext = os.path.splitext(filename)
            imported_data = None

            if ext.lower() in ['.aez', '.aezl']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_data = json.load(f)

                if isinstance(imported_data, dict):
                    self.configs[name] = imported_data
                    self.audio_engine.py_channel.statusUpdate.emit(f"Configuration '{name}' imported successfully.")

                    # Màj des filtres et gains
                    self.audio_engine.pre_gain_db = imported_data.get('pre_gain_db', 0.0)
                    self.audio_engine.bass_gain_db = imported_data.get('bass_gain_db', 0.0)
                    self.audio_engine.treble_gain_db = imported_data.get('treble_gain_db', 0.0)
                    self.audio_engine.bands = imported_data.get('bands', self.audio_engine.bands)
                    self.audio_engine.gains = np.array(imported_data.get('gains', np.zeros(len(self.audio_engine.bands)).tolist()))
                    self.audio_engine.q_values = np.array(imported_data.get('q_values', np.full(len(self.audio_engine.bands), 1.41).tolist()))
                    self.audio_engine.filter_types = imported_data.get('filter_types', ['PK'] * len(bands)) # Explicitly update the filter types
                    self.set_active_config(name)

                elif isinstance(imported_data, dict):
                    self.configs.update(imported_data)
                    self.audio_engine.py_channel.statusUpdate.emit("All configurations imported successfully.")

            elif ext.lower() == '.peace':
                try:
                    with open(file_path, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(file_path, 'r', encoding='latin1') as f:
                        content = f.read()

                preamp_match = re.search(r"PreAmp=(-?\d+\.?\d*)", content)
                preamp = float(preamp_match.group(1)) if preamp_match else 0.0

                bass_gain_match = re.search(r"Bass Gain=(-?\d+\.?\d*)", content)
                bass_gain = float(bass_gain_match.group(1)) if bass_gain_match else 0.0

                treble_gain_match = re.search(r"Treble Gain=(-?\d+\.?\d*)", content)
                treble_gain = float(treble_gain_match.group(1)) if treble_gain_match else 0.0

                frequencies = re.findall(r"Frequency\d+=(\d+\.?\d*)", content)
                gains = re.findall(r"Gain\d+=(-?\d+\.?\d*)", content)
                q_values = re.findall(r"Quality\d+=(\d+\.?\d*)", content)

                length = min(len(frequencies), len(gains), len(q_values))
                if length == 0:
                    raise ValueError("No valid Peace filter configuration found.")

                new_bands = [float(f) for f in frequencies[:length]]
                new_gains = [float(g) for g in gains[:length]]
                new_q_values = [float(q) for q in q_values[:length]]

                imported_data = {
                    'pre_gain_db': preamp,
                    'bass_gain_db': bass_gain,
                    'treble_gain_db': treble_gain,
                    'bands': new_bands,
                    'gains': new_gains,
                    'q_values': new_q_values,
                    'filter_types': ['PK'] * len(new_bands)
                }

                self.configs[name] = imported_data
                self.audio_engine.py_channel.statusUpdate.emit(f"Peace configuration '{name}' imported successfully.")

            elif ext.lower() == '.txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Extraire Preamp
                preamp_match = re.search(r"Preamp:\s*([-+]?\d+\.?\d*)\s*dB", content, re.IGNORECASE)
                preamp = float(preamp_match.group(1)) if preamp_match else 0.0

                # Regular expression in main.py
                filter_pattern = re.compile(
                    r"Filter\s*\d+\s*:\s*ON\s+(\w+)\s+Fc\s+([\d\.]+)\s*Hz\s+Gain\s+([-+]?\d+\.?\d*)\s*dB\s+Q\s+([\d\.]+)",
                    re.IGNORECASE
                )

                bands = []
                gains = []
                q_values = []
                filter_types = []


                for match in filter_pattern.finditer(content):
                    f_type = match.group(1).upper()
                    freq = float(match.group(2))
                    gain = float(match.group(3))
                    q = float(match.group(4))
                    print(f"Type: {f_type}, Freq: {freq}, Gain: {gain}, Q: {q}")
                    bands.append(freq)
                    gains.append(gain)
                    q_values.append(q)
                    filter_types.append(f_type)

                if not bands:
                    raise ValueError("Aucun filtre valide trouvé dans le fichier .txt")

                imported_data = {
                    'pre_gain_db': preamp,
                    'bands': bands,
                    'gains': gains,
                    'q_values': q_values,
                    'filter_types': filter_types
                }

                self.configs[name] = imported_data
                self.audio_engine.py_channel.statusUpdate.emit(f"Configuration '{name}' importée avec succès.")

            else:
                raise ValueError("Unsupported file format.")

            self.save_configs()
            if imported_data:
                self.audio_engine.pre_gain_db = imported_data.get('pre_gain_db', 0.0)
                self.audio_engine.bass_gain_db = imported_data.get('bass_gain_db', 0.0)
                self.audio_engine.treble_gain_db = imported_data.get('treble_gain_db', 0.0)
                self.audio_engine.gains = np.array(imported_data.get('gains', np.zeros(len(self.audio_engine.bands)).tolist()))
                self.audio_engine.bands = imported_data.get('bands', self.audio_engine.bands)
                self.audio_engine.q_values = np.array(imported_data.get('q_values', np.full(len(self.audio_engine.bands), 1.41).tolist()))
                self.audio_engine.filter_types = imported_data.get('filter_types', ['PK'] * len(bands)) # Explicitly update the filter types
                self.set_active_config(name)

        except Exception as e:
            self.audio_engine.py_channel.statusUpdate.emit(f"Error importing file: {e}")
            print(f"Import error: {e}", file=sys.stderr)