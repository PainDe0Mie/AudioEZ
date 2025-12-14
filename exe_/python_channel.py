import json, os, sys, time, winreg
from pypresence import Presence
from PySide6.QtCore import Signal, QThread, QObject, Slot

import config

def get_autoeq_models_for_settings():
    models = set()
    measurements_root = "measurements"
    
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
                    model_name = os.path.splitext(file)[0]
                    models.add(model_name)
    
    return sorted(models)

class AutoEQFetcher(QObject):
    modelsFetched = Signal(list)

    def __init__(self, audio_engine):
        super().__init__()
        self.audio_engine = audio_engine

    @Slot()
    def run(self):
        models = self.audio_engine.fetch_autoeq_index(force_refresh=True)
        self.modelsFetched.emit(models)

class PythonChannel(QObject):
    statusUpdate = Signal(str)
    configStatusUpdate = Signal(str)
    preampGainChanged = Signal(float)
    frequencyResponseUpdate = Signal(list, list, list, list, list)
    playbackStateChanged = Signal(bool)
    configListUpdate = Signal(list, str)
    bassGainChanged = Signal(float)
    trebleGainChanged = Signal(float)
    qFactorChanged = Signal(float)
    modelsUpdated = Signal(list)
    autoeqModelsUpdated = Signal(list)
    targetCurveUpdate = Signal(list, list)
    EarphonesCurve = Signal(list, list)
    headphoneDetected = Signal(str)
    get_ET = Signal(str, str)
    settingsUpdated = Signal(str)
    
    def __init__(self, audio_engine, adaptive_integration):
        super().__init__()

        self.audio_engine = audio_engine
        self.adaptive_integration = adaptive_integration if adaptive_integration is not None else None
        self.config_manager = audio_engine.config_manager
        self.audio_engine.set_channel(self)
        self._models_cache = []
        print("PythonChannel: Object registered for QWebChannel.")

        self.earphone_name = ""
        self.target_name = ""

        self._target_curve_freq = []
        self._target_curve_amp = []
        self._earphones_curve_freq = []
        self._earphones_curve_amp = []

        self.targetCurveUpdate.connect(self._update_target_curve)
        self.EarphonesCurve.connect(self._update_earphones_curve)

        self.settings = {}
        self.APP_NAME = "AudioEZ"
        self.REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
        self.load_settings()

        try:
            if self.settings.get("discord_rpc", True):
                config.connect()
                config.RPC.update(
                    state="Starting..",
                    large_image="logo",
                    start=time.time()
                )
        except:
            print("Discord is not installed or not running.")

    @Slot(str)
    def setDefaultConfiguration(self, config_name: str):
        print(f"PythonChannel: Setting '{config_name}' as default startup configuration.")

        settings_path = os.path.join(config.APP_CONFIGS_DIR, "settings.json")
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception as e:
                print(f"Erreur lecture settings: {e}")

        settings['default_configuration'] = config_name
        
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            self.settings = settings 
            self.statusUpdate.emit(f"'{config_name}' est maintenant la configuration par défaut.")
        except Exception as e:
            print(f"Erreur sauvegarde settings: {e}")
            self.statusUpdate.emit(f"Erreur: Impossible de définir '{config_name}' comme défaut.")

    @Slot(bool)
    def toggleAdaptiveFilter(self, enabled):
        """Active ou désactive le filtre adaptatif depuis l'interface."""
        if enabled:
            self.adaptive_integration.enable_adaptive_filter()
            self.statusUpdate.emit("Adaptive Filter: Active")
        else:
            self.adaptive_integration.disable_adaptive_filter()
            self.statusUpdate.emit("Adaptive Filter: Inactive")

    def _update_target_curve(self, freq_list, amp_list):
        self._target_curve_freq = freq_list
        self._target_curve_amp = amp_list

    def _update_earphones_curve(self, freq_list, amp_list):
        self._earphones_curve_freq = freq_list
        self._earphones_curve_amp = amp_list

    def load_settings(self):
        """Charge les paramètres depuis settings.json ou crée un fichier par défaut."""
        default_settings = {
            "auto_launch": False,
            "detect_earphone": True,
            "persistent_state": True,
            "discord_rpc": False,
            "launch_with_windows": False,
            "default_headphone": "None",
            "default_target": "AutoEq in-ear",
            "default_configuration": "Default",
            "adaptive_filter": False
        }
        
        try:
            with open(config.settings_file, 'r') as f:
                self.settings = json.load(f)

            for key, value in default_settings.items():
                if key not in self.settings:
                    self.settings[key] = value
            print("Paramètres chargés avec succès.")
        except (FileNotFoundError, json.JSONDecodeError):
            print("Fichier de paramètres non trouvé ou invalide. Création d'un fichier par défaut.")
            self.settings = default_settings
            self.save_settings()
        
        self.apply_settings_on_startup()

    def apply_settings_on_startup(self):
        """Applique les paramètres au démarrage de l'application"""
        # Configuration Discord RPC
        if self.settings.get("discord_rpc", True):
            try:
                client_id = '1402724529851072583'
                self.RPC = Presence(client_id)
                self.RPC.connect()
                self.RPC.update(
                    state="Starting AudioEZ...",
                    large_image="logo",
                    start=time.time()
                )
            except Exception as e:
                print(f"Erreur Discord RPC: {e}")
        
        # Configuration autostart
        if sys.platform == "win32":
            self.update_autostart(self.settings.get("launch_with_windows", False))

    def update_autostart(self, enabled):
        """Active ou désactive le démarrage automatique avec Windows"""
        if sys.platform != "win32":
            return
            
        try:
            key = winreg.HKEY_CURRENT_USER
            reg_key = winreg.OpenKey(key, self.REG_PATH, 0, winreg.KEY_SET_VALUE)
            
            if enabled:
                # Chemin complet de l'exécutable
                exe_path = os.path.abspath(sys.executable)
                winreg.SetValueEx(reg_key, self.APP_NAME, 0, winreg.REG_SZ, exe_path)
                print(f"Autostart activé: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(reg_key, self.APP_NAME)
                    print("Autostart désactivé")
                except FileNotFoundError:
                    pass 
                    
            winreg.CloseKey(reg_key)
            
        except Exception as e:
            print(f"Erreur configuration autostart: {e}")

    def save_settings(self):
        os.makedirs(os.path.dirname(config.settings_file), exist_ok=True)
        with open(config.settings_file, 'w') as f:
            json.dump(self.settings, f, indent=4)
        
        if self.settings:
            self.settingsUpdated.emit(json.dumps(self.settings))
        else:
            print("Avertissement: Tentative d'émettre des paramètres vides")

    @Slot(str)
    def saveSettings(self, json_settings):
        try:
            new_settings = json.loads(json_settings)
            
            print(f"Saving settings: {new_settings}")
            
            self.update_autostart(new_settings.get("launch_with_windows", False))
            self.settings.update(new_settings)
            self.save_settings()
            
        except Exception as e:
            print(f"Erreur lors de la sauvegarde : {e}")

    @Slot(result=str)
    def getSettings(self):
        """Slot appelé par JavaScript pour obtenir les paramètres."""
        return json.dumps(self.settings)

    @Slot(result=str)
    def getAutoEQModelsForSettings(self):
        """Retourne la liste des modèles AutoEQ pour les paramètres"""
        models = get_autoeq_models_for_settings()
        return json.dumps(models)

    @Slot(result=list)
    def getConfigNamesForSettings(self):
        """Retourne la liste des noms de configurations pour les paramètres"""
        return self.audio_engine.config_manager.get_config_names()

    @Slot(str, str)
    def update_presence_discord(self, state, details):
        
        if self.settings.get("discord_rpc", True):
            try:
                config.RPC.update(
                    state=state,
                    details=details,
                    large_image="logo",
                    large_text="AudioEZ",      
                    start=time.time()
                )
            except:
                print("Discord is not installed or not running.")

    @Slot(str)
    def receiveConsoleLog(self, message):
        print(f"[JS LOG] {message}")

    @Slot()
    def requestAutoEQModels(self):
        print("PythonChannel: Demande de récupération modèles AutoEQ.")

        cache_path = os.path.join(self.audio_engine.AUTOEQ_CACHE_DIR, "autoeq_cache", "index.json")

        cache_data = None
        cached_models = []

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    cached_models = cache_data.get('data', [])
            except Exception as e:
                self.audio_engine.log_message(f"Erreur chargement cache AutoEQ: {e}")

        if cached_models:
            print("PythonChannel: Envoi du cache local sans fetch.")
            self._models_cache = cached_models
            self.modelsUpdated.emit(cached_models)
            return

        self.fetcher_thread = QThread()
        self.fetcher = AutoEQFetcher(self.audio_engine)
        self.fetcher.moveToThread(self.fetcher_thread)
        self.fetcher.modelsFetched.connect(self.onModelsFetched)
        self.fetcher_thread.started.connect(self.fetcher.run)
        self.fetcher_thread.start()

    @Slot(list)
    def onModelsFetched(self, models):
        print(f"PythonChannel: {len(models)} modèles reçus.")
        self._models_cache = models
        self.modelsUpdated.emit(models)
        self.fetcher_thread.quit()
        self.fetcher_thread.wait()

    @Slot(str, str, int)
    def applyAutoEQProfile(self, headphone, target, band_size):
        print(f"Application de l'AutoEQ : {headphone} avec cible {target} sur {band_size} bandes.")
        if self.audio_engine:
            self.audio_engine.apply_autoeq_profile(headphone, target, band_size)

    @Slot(str)
    def fetchCurve(self, object):
        print(f"Recuperation de la courbe : {object}")
        if self.audio_engine:
            self.audio_engine.fetch_object_curve(object)

    @Slot(float)
    def setPreampGain(self, gain_db):
        print(f"PythonChannel: Received 'setPreampGain' call with value {gain_db}.")
        self.audio_engine.set_pre_gain(gain_db)

    @Slot(float)
    def setBassGain(self, gain_db):
        print(f"PythonChannel: Received 'setBassGain' call with value {gain_db}.")
        self.audio_engine.set_bass_gain(gain_db)

    @Slot(float)
    def setTrebleGain(self, gain_db):
        print(f"PythonChannel: Received 'setTrebleGain' call with value {gain_db}.")
        self.audio_engine.set_treble_gain(gain_db)

    @Slot(int, float, int)
    def setBandGainAndFrequency(self, index, gain_db, frequency):
        print(f"PythonChannel: Received 'setBandGainAndFrequency' call for index {index} with gain={gain_db} dB and frequency={frequency} Hz.")
        self.audio_engine.set_gain_and_frequency(index, gain_db, frequency)

    @Slot()
    def startPlayback(self):
        print("PythonChannel: Received 'startPlayback' call.")
        self.audio_engine.start_playback()

    @Slot()
    def stopPlayback(self):
        print("PythonChannel: Received 'stopPlayback' call.")
        self.audio_engine.stop_playback()

    @Slot(str)
    def loadConfig(self, config_name):
        print(f"PythonChannel: Received 'loadConfig' call for config '{config_name}'.")
        self.audio_engine.load_config(config_name)

    @Slot(str)
    def saveConfig(self, config_name):
        print(f"PythonChannel: Received 'saveConfig' call for config '{config_name}'.")
        self.audio_engine.save_config(config_name)

    @Slot(str)
    def deleteConfig(self, config_name):
        print(f"PythonChannel: Received 'deleteConfig' call for config '{config_name}'.")
        
        if not config_name or config_name == "Default":
            print("PythonChannel: Cannot delete 'Default' configuration.")
            return

        self.config_manager.delete_config(config_name)

        config_list = self.config_manager.get_config_names()
        self.configListUpdate.emit(config_list, "")

        self.audio_engine.load_config("Default")
        self.audio_engine.calculate_frequency_response()
        self.audio_engine.send_full_ui_update()

    @Slot(str) 
    def exportConfig(self, export_data_json):
        print("PythonChannel: Received 'exportConfig' call.")
        try:
            export_data = json.loads(export_data_json)
        except json.JSONDecodeError:
            print("Error decoding JSON in exportConfig")
            return
        
        self.audio_engine.export_config(export_data)
    
    @Slot()
    def exportAllConfigs(self):
        print("PythonChannel: Received 'exportAllConfigs' call.")
        self.audio_engine.export_all_configs()

    @Slot()
    def importConfig(self):
        print("PythonChannel: Received 'importConfig' call.")
        self.audio_engine.import_config_file()

    @Slot()
    def resetAllGains(self):
        print("PythonChannel: Received 'resetAllGains' call.")
        self.audio_engine.reset_gains()
    
    @Slot()
    def openFileDialog(self):
        print("PythonChannel: Received 'openFileDialog' call.")
        self.audio_engine.load_config_file()

    @Slot()
    def openKoFi(self):
        print("PythonChannel: Open Ko-Fi page.")
        import webbrowser
        webbrowser.open("https://ko-fi.com/painde0mie")

    @Slot(float)
    def set_q_factor(self, q):
        """Applique le même Q à tous les filtres et met à jour la courbe."""
        print(f"AudioEngine: Setting Q-factor of all bands to {q:.2f}.")
        self.q_values[:] = q
        if self.is_playing:
            self._apply_apo_config()
        self.calculate_frequency_response()

    @Slot(int, str, float)
    def setEqualizerPointParameter(self, index, key, value):
        self.audio_engine.set_equalizer_point_parameter(index, key, value)