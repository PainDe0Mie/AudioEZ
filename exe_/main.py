from multiprocessing import freeze_support
freeze_support() # For exe build (with pyinstaller)

import json, re, os, sys, difflib

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def get_executable_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

import numpy as np
from collections import defaultdict
from pypresence import Presence
from PySide6.QtCore import QUrl, QCoreApplication, Qt, QTimer, QLockFile, QDir
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QMessageBox, QDialog, QPushButton, QLabel, QHBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QIcon
from subprocess import Popen

import sounddevice as sd
import config

def check_single_instance():
    """Empêche le lancement multiple de l'application"""
    lock_file = QLockFile(QDir.temp().filePath('audioez.lock'))
    
    if not lock_file.tryLock(100):
        QMessageBox.warning(
            None,
            "AudioEZ",
            "AudioEZ est déjà en cours d'exécution."
        )
        return False
    return True

# Constants
EAPO_INSTALL_PATH = r"C:\Program Files\EqualizerAPO"
EAPO_CONFIG_PATH = os.path.join(EAPO_INSTALL_PATH, "config", "config.txt")

exe_dir = get_executable_dir()
os.chdir(exe_dir)
config.APP_CONFIGS_DIR = os.path.join(exe_dir, "configs")
config.initialize_paths()

def load_from_aez_file(filepath: str) -> dict:
    if not os.path.exists(filepath):
        print(f"Erreur : Le fichier '{filepath}' n'existe pas.")
        return {}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"Chargement réussi depuis {filepath}")
            return data
    except json.JSONDecodeError as e:
        print(f"Erreur de décodage JSON dans le fichier '{filepath}': {e}")
        return {}
    except IOError as e:
        print(f"Erreur lors de la lecture du fichier '{filepath}': {e}")
        return {}

def tokenize(name):
    return set(re.findall(r'\w+', name.lower()))

def split_model_name(name):
    pattern = r"^(.*?)(?:[\s\-_]?([0-9]+|gen\s*\d+|mk\s*\d+|s|pro|ii|iii|iv))?$"
    m = re.match(pattern, name.lower())
    if m:
        base = m.group(1).strip()
        suffix = m.group(2) or ""
        return base, suffix
    return name, ""

def suffix_similarity(s1, s2):
    return 1.0 if s1 == s2 else 0.0

def build_index(known_devices):
    """Crée un index pour limiter les comparaisons de noms"""
    index = defaultdict(list)
    known_data = []
    for known in known_devices:
        base, suffix = split_model_name(known)
        tokens = tokenize(base)
        known_data.append((base, suffix, known, tokens))
        for token in tokens:
            index[token].append((base, suffix, known))
    return index, known_data

def find_matching_device(available_devices, known_devices, threshold=0.75, min_common_tokens=2):
    index, known_data = build_index(known_devices)
    best_score = 0
    best_known = None
    best_dev = None

    for dev in available_devices:
        dev_base, dev_suffix = split_model_name(dev)
        dev_tokens = tokenize(dev_base)

        candidates = set()
        for token in dev_tokens:
            candidates.update(index.get(token, []))

        filtered_candidates = []
        for base, suffix, full_name in candidates:
            common_tokens = dev_tokens.intersection(tokenize(base))
            if len(common_tokens) >= min_common_tokens:
                filtered_candidates.append((base, suffix, full_name))

        for base, suffix, full_name in filtered_candidates:
            base_ratio = difflib.SequenceMatcher(None, dev_base, base).ratio()
            if base_ratio >= threshold:
                suffix_score = suffix_similarity(dev_suffix, suffix)
                score = base_ratio + suffix_score
                if score > best_score:
                    best_score = score
                    best_known = full_name
                    best_dev = dev

    return best_known, best_dev

def get_all_autoeq_models(measurements_root="measurements"):
    """Récupère tous les modèles AutoEQ disponibles"""
    models = set()
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
                    model_name = os.path.splitext(file)[0].lower()
                    models.add(model_name)
    return models

def list_output_devices():
    devices = sd.query_devices()
    return [dev['name'].lower() for dev in devices if dev['max_output_channels'] > 0]

class InstallAPODialog(QDialog):
    """Boîte de dialogue pour l'installation d'Equalizer APO"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Equalizer APO Installation Required")
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout(self)
        
        label = QLabel("Equalizer APO is not installed. It is an essential component for this program to function.\n\nDo you want to start the installation now?")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        buttons_layout = QHBoxLayout()
        install_button = QPushButton("Install Equalizer APO")
        cancel_button = QPushButton("Cancel")
        
        buttons_layout.addWidget(install_button)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
        install_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
                color: white;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 10px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 10px;
                font-size: 12px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton#cancel_button {
                background-color: #4a5568;
            }
            QPushButton#cancel_button:hover {
                background-color: #2d3748;
            }
        """)

def load_aez_state():
    data = load_from_aez_file(f"{config.APP_CONFIGS_DIR}/temp_.aez")

    if not data:
        print("Aucun fichier de secours valide trouvé ou le chargement a échoué.")
        return

    filters = data.get('equalizer', {}).get('parametric', {}).get('filters', [])

    if filters:
        bands = [f['freq'] for f in filters]
        gains = [f['gain'] for f in filters]
        q_values = [f['q'] for f in filters]
        filter_types = [f['type'] for f in filters]
    else:
        bands = []
        gains = []
        q_values = []
        filter_types = []

    parametric_eq = data.get('equalizer', {}).get('parametric', {})
    preamp = parametric_eq.get('preamp')
    bass_boost = parametric_eq.get('bass_boost')
    treble_boost = parametric_eq.get('treble_boost')

    earphone_data = data.get('headphone', {})
    earphone_name = earphone_data.get('name')
    earphone_curve = earphone_data.get('curve', [])
    
    target_data = data.get('target', {})
    target_name = target_data.get('name')
    target_curve = target_data.get('curve', [])
    
    return {
        'bands': bands,
        'gains': gains,
        'q_values': q_values,
        'filter_types': filter_types,
        'pre_gain_db': preamp,
        'bass_gain_db': bass_boost,
        'treble_gain_db': treble_boost,
        'earphone_name': earphone_name,
        'earphone_curve': earphone_curve,
        'target_name': target_name,
        'target_curve': target_curve
    }

class AudioEZWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        from audio_engine import AudioEngine
        from python_channel import PythonChannel

        self.setWindowTitle("AudioEZ - V1")
        self.setGeometry(100, 100, 1150, 900) 
        
        self.webview = QWebEngineView()
        self.webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        
        #current_dir = os.path.dirname(os.path.abspath(__file__))
        #html_path = os.path.join(current_dir, 'index.html')

        # Python version

        html_path = get_resource_path('index.html') # For exe build
        
        if not os.path.exists(html_path):
            QMessageBox.critical(self, "Error", f"The HTML file was not found at the location: {html_path}")
            sys.exit(1)

        self.webview.load(QUrl.fromLocalFile(html_path))
        
        page = self.webview.page()
        
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.audio_engine = AudioEngine()
        
        temp_settings = {}
        try:
            with open(config.settings_file, 'r') as f:
                temp_settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        rtgd_config = {
            'refine_window': temp_settings.get('adaptive_analysis_duration', 5.0),
            'hysteresis_delay': temp_settings.get('adaptive_hysteresis_delay', 10.0),
            'cooldown_period': temp_settings.get('adaptive_cooldown_period', 30.0)
        }
        
        self.adaptive_integration = None
        #if temp_settings.get("adaptive_filter", False):
        #    try:
        #        from RTGD import AudioEZAdaptiveIntegration
        #        self.adaptive_integration = AudioEZAdaptiveIntegration(self.audio_engine, rtgd_config=rtgd_config)
        #        print("Adaptive Filter module loaded successfully.")
        #    except ImportError:
        #        print("Warning: Adaptive Filter is enabled in settings but RTGD module could not be imported.")
        #        print("Please ensure RTGD.py is in the correct directory and its dependencies are met.")
        
        # REMOVED ON EXE BUILD

        self.py_channel = PythonChannel(self.audio_engine, self.adaptive_integration)
        

        self.channel = QWebChannel()
        self.channel.registerObject("py_channel", self.py_channel)
        page.setWebChannel(self.channel)
        
        # Configuration de l'interface
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.webview)
        self.setCentralWidget(central_widget)

        self.check_apo_installation()

        self.load_persistent_state()

        self.webview.loadFinished.connect(self.on_load_finished)

    def load_persistent_state(self):
        """Charge l'état persistant de l'application si activé"""
        if self.py_channel.settings.get("persistent_state", True):
            state = load_aez_state()
            if state:
                self.audio_engine.bands = state.get('bands', self.audio_engine.bands)
                self.audio_engine.gains = np.array(state.get('gains', self.audio_engine.gains))
                self.audio_engine.q_values = np.array(state.get('q_values', self.audio_engine.q_values))
                self.audio_engine.filter_types = state.get('filter_types', self.audio_engine.filter_types)
                self.audio_engine.pre_gain_db = state.get('pre_gain_db', 0.0)
                self.audio_engine.bass_gain_db = state.get('bass_gain_db', 0.0)
                self.audio_engine.treble_gain_db = state.get('treble_gain_db', 0.0)
                
                self.py_channel.earphone_name = state.get('earphone_name', '')
                self.py_channel.target_name = state.get('target_name', '')
                
                earphone_curve = state.get('earphone_curve', [])
                if earphone_curve and isinstance(earphone_curve, list) and len(earphone_curve) > 0:
                    if isinstance(earphone_curve[0], list) and len(earphone_curve[0]) > 0:
                        self.py_channel._earphones_curve_freq = [p[0] for p in earphone_curve]
                        self.py_channel._earphones_curve_amp = [p[1] for p in earphone_curve]
                    elif len(earphone_curve) == 2 and isinstance(earphone_curve[0], list):
                        self.py_channel._earphones_curve_freq = earphone_curve[0]
                        self.py_channel._earphones_curve_amp = earphone_curve[1]
                
                target_curve = state.get('target_curve', [])
                if target_curve and isinstance(target_curve, list) and len(target_curve) > 0:
                    if isinstance(target_curve[0], list) and len(target_curve[0]) > 0:
                        self.py_channel._target_curve_freq = [p[0] for p in target_curve]
                        self.py_channel._target_curve_amp = [p[1] for p in target_curve]
                    elif len(target_curve) == 2 and isinstance(target_curve[0], list):
                        self.py_channel._target_curve_freq = target_curve[0]
                        self.py_channel._target_curve_amp = target_curve[1]
                
                print("État persistant chargé avec succès.")
        
        default_config = self.py_channel.settings.get("default_configuration", "Default")
        if default_config and default_config != "Default":
            self.audio_engine.load_config(default_config)
            print(f"Configuration par défaut chargée: {default_config}")

        default_target = self.py_channel.settings.get("default_target", "")
        if default_target:
            print(f"Chargement de la cible par défaut: {default_target}")
            self.audio_engine.fetch_object_curve(default_target)
        
        default_headphone = self.py_channel.settings.get("default_headphone", "")
        if default_headphone:
            print(f"Chargement de l'écouteur par défaut: {default_headphone}")
            self.audio_engine.fetch_object_curve(default_headphone)

    def on_load_finished(self, ok):
        """Gère le chargement complet de l'interface web"""
        if ok:
            print("Web page finished loading successfully.")
            
            settings_json = json.dumps(self.py_channel.settings)
            self.webview.page().runJavaScript(f"window.updateSettingsFromPython({settings_json})")
                
            self.detect_headphones()
            self.load_default_headphone()
            
            self.py_channel.get_ET.emit(self.py_channel.earphone_name, self.py_channel.target_name)
            self.audio_engine.send_full_ui_update()
            
            if self.py_channel.settings.get("auto_launch", False):
                if not self.audio_engine.is_playing:
                    QTimer.singleShot(1000, self.audio_engine.start_playback)
                    print("Auto-launching equalizer...")
            
            if self.py_channel.settings.get("adaptive_filter", False):
                print("Adaptive Filter was enabled on last session, re-enabling.")
                self.py_channel.toggleAdaptiveFilter(True)
                self.webview.page().runJavaScript("document.getElementById('adaptive-filter-state').checked = true;")
        else:
            print("Web page failed to load.")

    def detect_headphones(self):
        """Détecte et applique automatiquement le profil d'écouteur si activé"""
        if not self.py_channel.settings.get("detect_earphone", False):
            return

        known_devices = get_all_autoeq_models()
        devices = list_output_devices()

        known, found = find_matching_device(
            devices,
            known_devices,
            threshold=0.75,
            min_common_tokens=2
        )

        if known:
            print(f"✅ Appareil reconnu : {found} (match avec {known})")
            self.audio_engine.fetch_object_curve(known)
            self.py_channel.headphoneDetected.emit(known)
            
            if self.py_channel.settings.get("autoeq", False):
                target = self.py_channel.settings.get("default_target", "AutoEq in-ear")
                self.audio_engine.apply_autoeq_profile(known, target, 10)
        else:
            print(f"❌ Aucun appareil reconnu.")
            self.py_channel.headphoneDetected.emit(None)

    def load_default_headphone(self):
        """Charge le modèle d'écouteur par défaut si défini"""
        default_headphone = self.py_channel.settings.get("default_headphone", "")
        if default_headphone:
            self.audio_engine.fetch_object_curve(default_headphone)
            self.py_channel.earphone_name = default_headphone
            print(f"Écouteur par défaut chargé: {default_headphone}")

    def check_apo_installation(self):
        """Vérifie l'installation d'Equalizer APO et propose l'installation si nécessaire"""
        if not os.path.exists(EAPO_INSTALL_PATH):
            dialog = InstallAPODialog(self)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                installer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EqualizerAPO64-1.3.exe")
                if os.path.exists(installer_path):
                    Popen([installer_path])
                    QMessageBox.information(self, "Installation", "The Equalizer APO installer has been launched. Please follow it to complete the installation, then restart AudioEZ.")
                    QCoreApplication.instance().quit()
                else:
                    QMessageBox.critical(self, "Error", "The Equalizer APO installer was not found. Please place it in the same folder as your application.")
                    QCoreApplication.instance().quit()
            else:
                QMessageBox.critical(self, "Error", "Equalizer APO is required for this program to function. The application will now close.")
                QCoreApplication.instance().quit()

    def closeEvent(self, event):
        """Gère la fermeture de l'application"""
        print("Closing the application...")
        self.audio_engine.stop_playback()
        
        if self.py_channel.settings.get("persistent_state", True):
            eq_parametric_data = {
                "preamp": self.audio_engine.pre_gain_db,
                "bass_boost": self.audio_engine.bass_gain_db,
                "treble_boost": self.audio_engine.treble_gain_db,
                "filters": [
                    {"type": t, "gain": g, "q": q, "freq": b}
                    for b, g, q, t in zip(self.audio_engine.bands, self.audio_engine.gains, self.audio_engine.q_values, self.audio_engine.filter_types)
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
            print("État persistant sauvegardé.")
        
        event.accept()

def initialize_config():
    os.makedirs(config.APP_CONFIGS_DIR, exist_ok=True)
    
    if not os.path.exists(config.settings_file):
        with open(config.settings_file, 'w') as f:
            json.dump({
                "auto_launch": False,
                "detect_earphone": True,
                "persistent_state": True,
                "discord_rpc": False,
                "launch_with_windows": False,
                "default_headphone": "None",
                "default_target": "AutoEq in-ear",
                "default_configuration": "Default",
                "adaptive_filter": False
            }, f)
    
    return config.settings_file

def initialize_discord_rpc():
    """Initialise Discord RPC si nécessaire"""
    try:
        RPC = Presence(config.client_id)
        return RPC
    except:
        print("Discord non disponible")
        return None

def main():
    
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR"] = "1"
    
    initialize_config()
    config.RPC = initialize_discord_rpc()

    app = QApplication(sys.argv)

    if not check_single_instance():
        sys.exit(1)

    app.setWindowIcon(QIcon('icon.ico'))

    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    except Exception:
        pass
    
    from verification import run_verification

    verif = run_verification()
    if verif:
        window = AudioEZWindow()
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    multiprocessing.set_start_method('spawn', force=True)

    main()