import json, re, os, sys, csv, time, difflib, winreg, subprocess, shutil, urllib.request, urllib.error
import numpy as np
import sounddevice as sd 
from collections import defaultdict
from pypresence import Presence
from PyQt5.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal, QCoreApplication, QThread, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QMessageBox, QDialog, QPushButton, QLabel, QHBoxLayout, QProgressBar, QTextEdit
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtGui import QIcon, QFont
from subprocess import Popen
from pathlib import Path
from typing import List, Tuple

class VerificationThread(QThread):
    """Thread pour effectuer les vérifications sans bloquer l'interface"""
    progress_update = pyqtSignal(str, int)
    verification_complete = pyqtSignal(bool, str)
    task_progress_update = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        self.base_path = Path(__file__).parent
        self.autoeq_repo = "https://github.com/jaakkopasanen/AutoEq"
        self.audioez_repo = "https://github.com/PainDe0Mie/AudioEZ"
        self.required_libs = [
            'PyQt5', 'numpy', 'scipy', 'sounddevice', 'pypresence',
            'requests', 'librosa', 'autoeq'
        ]
        
    def run(self):
        try:
            self.progress_update.emit("Checking required libraries...", 10)
            missing_libs = self.check_libraries()
            if missing_libs:
                self.progress_update.emit(f"Installing missing libraries: {', '.join(missing_libs)}", 15)
                if not self.install_libraries(missing_libs):
                    self.verification_complete.emit(False, "Failed to install required libraries")
                    return
            
            self.progress_update.emit("Checking Equalizer APO...", 20)
            if not self.check_equalizer_apo():
                self.progress_update.emit("Installing Equalizer APO...", 25)
                if not self.install_equalizer_apo():
                    self.verification_complete.emit(False, "Failed to install Equalizer APO. Please install manually from https://sourceforge.net/projects/equalizerapo/")
                    return
            else:
                update_available, latest_version = self.check_equalizer_apo_updates()
                if update_available:
                    self.progress_update.emit(f"Updating Equalizer APO to {latest_version}...", 25)
                    self.install_equalizer_apo()

            self.progress_update.emit("Checking AutoEQ directories...", 30)
            if not self.check_autoeq_directories():
                self.progress_update.emit("Downloading AutoEQ data...", 40)
                if not self.download_autoeq_data():
                    self.verification_complete.emit(False, "Failed to download AutoEQ data")
                    return
            
            self.progress_update.emit("Checking for AutoEQ updates...", 60)
            if self.check_autoeq_updates():
                self.progress_update.emit("Updating AutoEQ data...", 65)
                self.update_autoeq_data()
            
            self.progress_update.emit("Checking AudioEZ version...", 85)
            update_available, latest_version = self.check_audioez_version()
            
            self.progress_update.emit("Building AutoEQ index...", 90)
            self.build_autoeq_index()

            self.progress_update.emit("Verification complete!", 100)
            
            message = "All checks passed successfully!"
            if update_available:
                message += f"\n\nNew version available: {latest_version}\nPlease visit {self.audioez_repo} to update."
            
            self.verification_complete.emit(True, message)
            
        except Exception as e:
            self.verification_complete.emit(False, f"Verification error: {str(e)}")

    def check_equalizer_apo(self) -> bool:
        try:
            key_paths = [
                r"SOFTWARE\EqualizerAPO",
                r"SOFTWARE\WOW6432Node\EqualizerAPO"
            ]
            
            for key_path in key_paths:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ)
                    install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                    winreg.CloseKey(key)
                    
                    if Path(install_path).exists() and (Path(install_path) / "Editor.exe").exists():
                        return True
                except (FileNotFoundError, OSError):
                    continue
            
            default_paths = [
                Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / "EqualizerAPO",
                Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')) / "EqualizerAPO"
            ]
            
            for path in default_paths:
                if path.exists() and (path / "Editor.exe").exists():
                    return True
            
            return False
            
        except Exception as e:
            print(f"Error checking Equalizer APO: {e}")
            return False
    
    def check_equalizer_apo_updates(self) -> Tuple[bool, str]:
        try:
            installed_version = self.get_installed_eqapo_version()
            if not installed_version:
                return False, "Unknown"
            
            latest_version = self.get_latest_eqapo_version()
            if not latest_version:
                return False, "Unknown"
            
            return (latest_version != installed_version), latest_version
            
        except Exception as e:
            print(f"Error checking Equalizer APO updates: {e}")
            return False, "Unknown"
    
    def get_installed_eqapo_version(self) -> str:
        try:
            key_paths = [
                r"SOFTWARE\EqualizerAPO",
                r"SOFTWARE\WOW6432Node\EqualizerAPO"
            ]
            
            for key_path in key_paths:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ)
                    version, _ = winreg.QueryValueEx(key, "Version")
                    winreg.CloseKey(key)
                    return version
                except (FileNotFoundError, OSError):
                    continue
            
            return None
        except Exception as e:
            print(f"Error getting installed version: {e}")
            return None
    
    def get_latest_eqapo_version(self) -> str:
        """Récupère la dernière version d'Equalizer APO depuis SourceForge"""
        try:
            api_url = "https://sourceforge.net/projects/equalizerapo/best_release.json"
            
            with urllib.request.urlopen(api_url, timeout=10) as response:
                data = json.loads(response.read())
                filename = data['release']['filename']
                version_match = re.search(r'EqualizerAPO[_-](\d+[._]\d+(?:[._]\d+)?)', filename)
                if version_match:
                    return version_match.group(1).replace('_', '.')
            
            return None
        except Exception as e:
            print(f"Error getting latest version: {e}")
            return None
    

    def get_latest_eqapo_version(self) -> str:
        api_url = "https://sourceforge.net/projects/equalizerapo/best_release.json"
        with urllib.request.urlopen(api_url, timeout=10) as response:
            data = json.loads(response.read())
        filename = data['release']['filename'] 
        version_match = re.search(r'EqualizerAPO-x64-(\d+\.\d+\.\d+)', filename)
        if version_match:
            return version_match.group(1)
        return None

    def install_equalizer_apo(self) -> bool:
        """Télécharge et installe Equalizer APO"""
        try:
            self.progress_update.emit("Downloading Equalizer APO...", 25)
            self.task_progress_update.emit(0, 100)

            version = self.get_latest_eqapo_version()
            download_url = f"https://netix.dl.sourceforge.net/project/equalizerapo/{version}/EqualizerAPO-x64-{version}.exe?viasf=1"

            print(download_url)
            
            temp_dir = Path(os.environ['TEMP']) / "AudioEZ_Setup"
            temp_dir.mkdir(exist_ok=True)

            installer_path = Path(os.environ['ProgramData']) / "AudioEZ" / f"EqualizerAPO-x64-{version}.exe"
            installer_path.parent.mkdir(parents=True, exist_ok=True)
            
            req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(req, timeout=60) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 8192
                
                with open(installer_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            self.task_progress_update.emit(percent, 100)
                            mb_dl = downloaded / (1024*1024)
                            mb_tot = total_size / (1024*1024)
                            self.progress_update.emit(f"Downloading: {mb_dl:.1f}MB / {mb_tot:.1f}MB", 25)
            
            self.progress_update.emit("Installing Equalizer APO...", 28)
            self.task_progress_update.emit(0, 100)
            
            process = subprocess.Popen(
                [str(installer_path), "/S"],
                shell=False
            )

            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                process.kill()
                return False

            self.progress_update.emit(
                "Installation terminée, vérification...",
                30
            )

            for _ in range(10):
                if self.check_equalizer_apo():
                    return True
                time.sleep(2)

            return False
                
        except Exception as e:
            print(f"Error installing Equalizer APO: {e}")
            self.task_progress_update.emit(0, 100)
            return False

    def check_libraries(self) -> List[str]:
        missing = []
        for lib in self.required_libs:
            try:
                __import__(lib.replace('-', '_'))
            except ImportError:
                missing.append(lib)
        return missing
    
    def install_libraries(self, libraries: List[str]) -> bool:
        try:
            for lib in libraries:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
            return True
        except subprocess.CalledProcessError:
            return False
    
    def check_autoeq_directories(self) -> bool:
        required_dirs = ['measurements', 'targets', 'results']
        for dir_name in required_dirs:
            dir_path = self.base_path / dir_name
            if not dir_path.exists() or not any(dir_path.iterdir()):
                return False
        return True
    
    def download_autoeq_data(self) -> bool:
        return self.download_autoeq_direct()
    
    def download_autoeq_direct(self) -> bool:
            try:
                import zipfile
                import io
                
                zip_url = f"{self.autoeq_repo}/archive/refs/heads/master.zip"
                
                self.progress_update.emit("Downloading AutoEQ...", 40)
                self.task_progress_update.emit(0, 100)
                
                req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    zip_data = bytearray()
                    chunk_size = 8192
                    downloaded = 0
                    
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        zip_data.extend(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            self.task_progress_update.emit(percent, 100)
                            
                            mb_dl = downloaded / (1024*1024)
                            mb_tot = total_size / (1024*1024)
                            self.progress_update.emit(f"Downloading: {mb_dl:.1f}MB / {mb_tot:.1f}MB", 40)

                self.progress_update.emit("Analyzing archive...", 60)
                self.task_progress_update.emit(0, 100)
                
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
                    prefix = 'AutoEq-master/'
                    target_dirs = ['measurements/', 'targets/', 'results/']
                    
                    all_files = zip_ref.namelist()
                    files_to_extract = []
                    
                    for f in all_files:
                        for td in target_dirs:
                            if f.startswith(prefix + td) and not f.endswith('/'):
                                files_to_extract.append(f)
                                break
                    
                    total_files = len(files_to_extract)
                    self.progress_update.emit(f"Extracting {total_files} files...", 70)
                    
                    for d in ['measurements', 'targets', 'results']:
                        dst = self.base_path / d
                        if dst.exists(): shutil.rmtree(dst)
                        dst.mkdir(exist_ok=True)
                    
                    for i, member in enumerate(files_to_extract):
                        relative_path = member[len(prefix):]
                        target_path = self.base_path / relative_path
                        
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        
                        if i % 10 == 0:
                            percent = int(((i + 1) / total_files) * 100)
                            self.task_progress_update.emit(percent, 100)
                            self.progress_update.emit(f"Extracting: {i+1}/{total_files}", 70)


                api_url = "https://api.github.com/repos/jaakkopasanen/AutoEq/commits/master"
                
                with urllib.request.urlopen(api_url) as response:
                    data = json.loads(response.read())
                    latest_commit = data['sha']
                
                version_file = self.base_path / ".autoeq_version"
                
                with open(version_file, 'w') as f:
                    f.write(latest_commit)
                
                self.task_progress_update.emit(100, 100)
                self.progress_update.emit("Download complete!", 80)
                return True
                
            except Exception as e:
                print(f"DL Error: {e}")
                self.task_progress_update.emit(0, 100)
                return False
    
    def check_autoeq_updates(self) -> bool:
        """Vérifie s'il y a des mises à jour pour AutoEQ"""
        try:
            api_url = "https://api.github.com/repos/jaakkopasanen/AutoEq/commits/master"
            
            with urllib.request.urlopen(api_url) as response:
                data = json.loads(response.read())
                latest_commit = data['sha']
            
            version_file = self.base_path / ".autoeq_version"
            if version_file.exists():
                with open(version_file, 'r') as f:
                    local_commit = f.read().strip()
                
                if local_commit == latest_commit:
                    return False
            
            with open(version_file, 'w') as f:
                f.write(latest_commit)
            
            return True
        except Exception as e:
            print(f"Error checking AutoEQ updates: {e}")
            return False
    
    def update_autoeq_data(self):
        self.download_autoeq_data()
    
    def check_audioez_version(self) -> Tuple[bool, str]:
        try:
            local = "1.0"
            if (self.base_path / "version.txt").exists():
                with open(self.base_path / "version.txt") as f: local = f.read().strip()
            
            url = "https://api.github.com/repos/PainDe0Mie/AudioEZ/releases/latest"
            with urllib.request.urlopen(url, timeout=5) as r:
                remote = json.loads(r.read())['tag_name'].lstrip('v')
            return (remote != local), remote
        except:
            return False, "Unknown"

    def build_autoeq_index(self):
            """Construction de l'index avec progression RÉELLE (basée sur les dossiers auteurs) et filtrage CSV."""
            
            cache_dir = self.base_path / "configs" / "autoeq_profiles" / "autoeq_cache"
            cache_path = cache_dir / "index.json"
            measurements_root = self.base_path / "measurements" 
            
            if cache_path.exists():
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                        cached_models = cache_data.get('data', [])
                        if cached_models:
                            print(f"Index: {len(cached_models)} modèles chargés depuis le cache.")
                            self.progress_update.emit(f"Indexed {len(cached_models)} models (cached)", 95)
                            self.task_progress_update.emit(100, 100)
                            return
                except Exception as e:
                    print(f"Erreur lecture cache AutoEQ : {e}. Reconstruction nécessaire.")

            if not measurements_root.exists():
                print(f"Répertoire {measurements_root} introuvable.")
                return

            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.task_progress_update.emit(0, 100)
                
                author_folders = [d for d in measurements_root.iterdir() if d.is_dir()]
                total_authors = len(author_folders)
                
                models_to_filter = {}
                self.progress_update.emit(f"Scanning {total_authors} databases...", 92)
                
                for i, author_folder in enumerate(author_folders):
                    percent_scan = int(((i + 1) / total_authors) * 50)
                    self.task_progress_update.emit(percent_scan, 100)
                    
                    index_path = author_folder / "name_index.tsv"
                    if not index_path.is_file():
                        continue

                    try:
                        with open(index_path, newline='', encoding='utf-8') as tsvfile:
                            reader = csv.DictReader(tsvfile, delimiter='\t')
                            for row in reader:
                                model_name = (row.get('model') or row.get('Model') or 
                                            row.get('name') or row.get('Name'))
                                if model_name:
                                    models_to_filter[model_name.strip()] = author_folder
                    except Exception as e:
                        print(f"Erreur lecture {index_path} : {e}")
                        
                
                valid_models = []
                invalid_models = []
                total_models = len(models_to_filter)
                
                self.progress_update.emit(f"Filtering {total_models} models...", 94)
                
                for i, (model_name, author_folder) in enumerate(models_to_filter.items()):
                    
                    found_csv = False
                    data_path = author_folder / "data"
                    
                    if data_path.exists():
                        csv_name_base = model_name.strip()
                        
                        expected_csv_path = data_path / f"{csv_name_base}.csv"
                        if expected_csv_path.is_file():
                            found_csv = True
                        else:
                            for file in data_path.rglob('*.csv'):
                                if file.stem.lower() == csv_name_base.lower():
                                    found_csv = True
                                    break
                    
                    if found_csv:
                        valid_models.append(model_name)
                    else:
                        invalid_models.append(model_name)

                    if total_models > 0:
                        percent_filter = 50 + int(((i + 1) / total_models) * 50)
                        if (i + 1) % 50 == 0 or (i + 1) == total_models:
                            self.task_progress_update.emit(percent_filter, 100)
                            self.progress_update.emit(f"Filtering: {i+1}/{total_models} models...", 94)

                self.autoeq_index = sorted(valid_models)

                print(f"Index: {len(valid_models)} modèles valides chargés. {len(invalid_models)} ignorés.")

                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump({'data': self.autoeq_index}, f, indent=2, ensure_ascii=False)
                
                self.task_progress_update.emit(100, 100)
                self.progress_update.emit(f"Indexed {len(valid_models)} models", 95)
                
            except Exception as e:
                print(f"Error building AutoEQ index: {e}")
                import traceback
                traceback.print_exc()
                self.task_progress_update.emit(0, 100)

class VerificationDialog(QDialog):
    """Dialogue de vérification au démarrage"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AudioEZ - Verification")
        self.setFixedSize(500, 350)
        self.setModal(True)
        
        self.setup_ui()
        self.verification_thread = VerificationThread()
        self.verification_thread.progress_update.connect(self.update_progress)
        self.verification_thread.verification_complete.connect(self.on_verification_complete)
        self.verification_thread.task_progress_update.connect(self.update_task_progress)  # NOUVEAU
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Titre
        title = QLabel("Checking files...")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Message de statut
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        # Barre de progression principale
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Barre de progression pour les tâches
        self.task_progress_bar = QProgressBar()
        self.task_progress_bar.setRange(0, 100)
        self.task_progress_bar.setValue(0)
        self.task_progress_bar.setFormat("Task: %p%")
        self.task_progress_bar.setVisible(False)
        layout.addWidget(self.task_progress_bar)
        
        # Zone de texte pour les détails
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        layout.addWidget(self.details_text)
        
        # Bouton de fermeture
        self.close_button = QPushButton("Cancel")
        #self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.exit)
        layout.addWidget(self.close_button)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
            }
            QLabel {
                color: #e2e8f0;
                padding: 10px;
            }
            QProgressBar {
                border: 2px solid #3b82f6;
                border-radius: 5px;
                text-align: center;
                color: white;
                background-color: #2d3748;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
            }
            QTextEdit {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 5px;
                font-family: 'Consolas', monospace;
                font-size: 10px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:disabled {
                background-color: #4a5568;
                color: #718096;
            }
        """)
    
    def start_verification(self):
        """Démarre le processus de vérification"""
        self.verification_thread.start()
    
    def update_progress(self, message: str, progress: int):
        """Met à jour l'interface avec la progression"""
        self.status_label.setText(message)
        self.progress_bar.setValue(progress)
        self.details_text.append(f"[{progress}%] {message}")
    
    def update_task_progress(self, current: int, total: int):
        """Met à jour la barre de progression des tâches"""
        if current > 0 and total > 0:
            self.task_progress_bar.setVisible(True)
            self.task_progress_bar.setValue(current)
            self.task_progress_bar.setMaximum(total)
        else:
            self.task_progress_bar.setVisible(False)
            self.task_progress_bar.setValue(0)
    
    def on_verification_complete(self, success: bool, message: str):
        """Appelé quand la vérification est terminée"""
        if success:
            self.status_label.setText("✓ Verification complete!")
            self.details_text.append(f"\n✓ SUCCESS: {message}")
            #self.close_button.setEnabled(True)
            time.sleep(2)
            self.accept()
        else:
            self.status_label.setText("✗ Verification failed")
            self.details_text.append(f"\n✗ ERROR: {message}")
            self.close_button.setText("Close")
            #self.close_button.setEnabled(True)
            self.close_button.clicked.disconnect()
            self.close_button.clicked.connect(self.reject)

    def exit(self):
        sys.exit(0)

def run_verification(parent=None) -> bool:
    """
    Exécute la vérification et retourne True si tout est OK
    À appeler au démarrage de l'application
    """
    dialog = VerificationDialog(parent)
    dialog.start_verification()
    result = dialog.exec_()
    return result == QDialog.Accepted

# Setup Discord RPC
client_id = '1402724529851072583'
RPC = Presence(client_id)

# Constants
EAPO_INSTALL_PATH = r"C:\Program Files\EqualizerAPO"
EAPO_CONFIG_PATH = os.path.join(EAPO_INSTALL_PATH, "config", "config.txt")
APP_CONFIGS_DIR = "./configs"
os.makedirs(APP_CONFIGS_DIR, exist_ok=True)
settings_file = os.path.join(APP_CONFIGS_DIR, 'settings.json')

# Set high DPI scaling
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"

# Create default settings if not exists
if not os.path.exists(settings_file):
    with open(settings_file, 'w') as f:
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

def save_to_aez_file(
    filepath: str,
    eq_parametric: dict,
    earphone_name: str,
    earphone_curve: list,
    target_name: str,
    target_curve: list
):
    """Sauvegarde les données d'égalisation dans un fichier .aez"""
    data = {
        "equalizer": {
            "parametric": eq_parametric
        },
        "headphone": {
            "name": earphone_name,
            "curve": earphone_curve
        },
        "target": {
            "name": target_name,
            "curve": target_curve
        }
    }

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        print(f"Erreur lors de l'écriture du fichier : {e}")

def load_from_aez_file(filepath: str) -> dict:
    """Lit et importe les données d'égalisation d'un fichier .aez"""
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
    """Trouve le meilleur match entre les appareils disponibles et connus"""
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

def get_autoeq_models_for_settings():
    """Récupère la liste des modèles AutoEQ pour les paramètres"""
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

def list_output_devices():
    """Liste les périphériques de sortie audio disponibles"""
    devices = sd.query_devices()
    return [dev['name'].lower() for dev in devices if dev['max_output_channels'] > 0]

class AdaptiveIntegrationDummy:
    def enable_adaptive_filter(self):
        print("Adaptive filter is not loaded. Cannot enable.")

    def disable_adaptive_filter(self):
        print("Adaptive filter is not loaded. Cannot disable.")

class AutoEQFetcher(QObject):
    """Thread pour récupérer les modèles AutoEQ"""
    modelsFetched = pyqtSignal(list)

    def __init__(self, audio_engine):
        super().__init__()
        self.audio_engine = audio_engine

    @pyqtSlot()
    def run(self):
        models = self.audio_engine.fetch_autoeq_index(force_refresh=True)
        self.modelsFetched.emit(models)

class PythonChannel(QObject):
    """Canal de communication entre Python et JavaScript"""
    statusUpdate = pyqtSignal(str)
    configStatusUpdate = pyqtSignal(str)
    preampGainChanged = pyqtSignal(float)
    frequencyResponseUpdate = pyqtSignal(list, list, list, list, list)
    playbackStateChanged = pyqtSignal(bool)
    configListUpdate = pyqtSignal(list, str)
    bassGainChanged = pyqtSignal(float)
    trebleGainChanged = pyqtSignal(float)
    qFactorChanged = pyqtSignal(float)
    modelsUpdated = pyqtSignal(list)
    autoeqModelsUpdated = pyqtSignal(list)
    targetCurveUpdate = pyqtSignal(list, list)
    EarphonesCurve = pyqtSignal(list, list)
    headphoneDetected = pyqtSignal(str)
    get_ET = pyqtSignal(str, str)
    settingsUpdated = pyqtSignal(str)
    
    def __init__(self, audio_engine, adaptive_integration):
        super().__init__()
        self.audio_engine = audio_engine
        self.adaptive_integration = adaptive_integration if adaptive_integration is not None else AdaptiveIntegrationDummy()
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
                RPC.connect()
                RPC.update(
                    state="Starting..",
                    large_image="logo",
                    start=time.time()
                )
        except:
            print("Discord is not installed or not running.")

    @pyqtSlot(str)
    def setDefaultConfiguration(self, config_name: str):
        """Définit la configuration spécifiée comme configuration par défaut au démarrage."""
        print(f"PythonChannel: Setting '{config_name}' as default startup configuration.")
        
        settings_path = os.path.join(APP_CONFIGS_DIR, "settings.json")
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

    @pyqtSlot(bool)
    def toggleAdaptiveFilter(self, enabled):
        """Active ou désactive le filtre adaptatif depuis l'interface."""
        if isinstance(self.adaptive_integration, AdaptiveIntegrationDummy):
            print("Adaptive Filter module not loaded. Cannot toggle.")
            return

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
            with open(settings_file, 'r') as f:
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
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        with open(settings_file, 'w') as f:
            json.dump(self.settings, f, indent=4)
        
        if self.settings:
            self.settingsUpdated.emit(json.dumps(self.settings))
        else:
            print("Avertissement: Tentative d'émettre des paramètres vides")

    @pyqtSlot(str)
    def saveSettings(self, json_settings):
        try:
            new_settings = json.loads(json_settings)
            
            print(f"Saving settings: {new_settings}")
            
            self.update_autostart(new_settings.get("launch_with_windows", False))
            self.settings.update(new_settings)
            self.save_settings()
            
        except Exception as e:
            print(f"Erreur lors de la sauvegarde : {e}")

    @pyqtSlot(result=str)
    def getSettings(self):
        """Slot appelé par JavaScript pour obtenir les paramètres."""
        return json.dumps(self.settings)

    @pyqtSlot(result=str)
    def getAutoEQModelsForSettings(self):
        """Retourne la liste des modèles AutoEQ pour les paramètres"""
        models = get_autoeq_models_for_settings()
        return json.dumps(models)

    @pyqtSlot(result=list)
    def getConfigNamesForSettings(self):
        """Retourne la liste des noms de configurations pour les paramètres"""
        return self.audio_engine.config_manager.get_config_names()

    @pyqtSlot(str, str)
    def update_presence_discord(self, state, details):
        if self.settings.get("discord_rpc", True):
            try:
                RPC.update(
                    state=state,
                    details=details,
                    large_image="logo",
                    large_text="AudioEZ",      
                    start=time.time()
                )
            except:
                print("Discord is not installed or not running.")

    @pyqtSlot(str)
    def receiveConsoleLog(self, message):
        print(f"[JS LOG] {message}")

    @pyqtSlot()
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

    @pyqtSlot(list)
    def onModelsFetched(self, models):
        print(f"PythonChannel: {len(models)} modèles reçus.")
        self._models_cache = models
        self.modelsUpdated.emit(models)
        self.fetcher_thread.quit()
        self.fetcher_thread.wait()

    @pyqtSlot(str, str, int)
    def applyAutoEQProfile(self, headphone, target, band_size):
        print(f"Application de l'AutoEQ : {headphone} avec cible {target} sur {band_size} bandes.")
        if self.audio_engine:
            self.audio_engine.apply_autoeq_profile(headphone, target, band_size)

    @pyqtSlot(str)
    def fetchCurve(self, object):
        print(f"Recuperation de la courbe : {object}")
        if self.audio_engine:
            self.audio_engine.fetch_object_curve(object)

    @pyqtSlot(float)
    def setPreampGain(self, gain_db):
        print(f"PythonChannel: Received 'setPreampGain' call with value {gain_db}.")
        self.audio_engine.set_pre_gain(gain_db)

    @pyqtSlot(float)
    def setBassGain(self, gain_db):
        print(f"PythonChannel: Received 'setBassGain' call with value {gain_db}.")
        self.audio_engine.set_bass_gain(gain_db)

    @pyqtSlot(float)
    def setTrebleGain(self, gain_db):
        print(f"PythonChannel: Received 'setTrebleGain' call with value {gain_db}.")
        self.audio_engine.set_treble_gain(gain_db)

    @pyqtSlot(int, float, int)
    def setBandGainAndFrequency(self, index, gain_db, frequency):
        print(f"PythonChannel: Received 'setBandGainAndFrequency' call for index {index} with gain={gain_db} dB and frequency={frequency} Hz.")
        self.audio_engine.set_gain_and_frequency(index, gain_db, frequency)

    @pyqtSlot()
    def startPlayback(self):
        print("PythonChannel: Received 'startPlayback' call.")
        self.audio_engine.start_playback()

    @pyqtSlot()
    def stopPlayback(self):
        print("PythonChannel: Received 'stopPlayback' call.")
        self.audio_engine.stop_playback()

    @pyqtSlot(str)
    def loadConfig(self, config_name):
        print(f"PythonChannel: Received 'loadConfig' call for config '{config_name}'.")
        self.audio_engine.load_config(config_name)

    @pyqtSlot(str)
    def saveConfig(self, config_name):
        print(f"PythonChannel: Received 'saveConfig' call for config '{config_name}'.")
        self.audio_engine.save_config(config_name)

    @pyqtSlot(str)
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

    @pyqtSlot(str) 
    def exportConfig(self, export_data_json):
        print("PythonChannel: Received 'exportConfig' call.")
        try:
            export_data = json.loads(export_data_json)
        except json.JSONDecodeError:
            print("Error decoding JSON in exportConfig")
            return
        
        self.audio_engine.export_config(export_data)
    
    @pyqtSlot()
    def exportAllConfigs(self):
        print("PythonChannel: Received 'exportAllConfigs' call.")
        self.audio_engine.export_all_configs()

    @pyqtSlot()
    def importConfig(self):
        print("PythonChannel: Received 'importConfig' call.")
        self.audio_engine.import_config_file()

    @pyqtSlot()
    def resetAllGains(self):
        print("PythonChannel: Received 'resetAllGains' call.")
        self.audio_engine.reset_gains()
    
    @pyqtSlot()
    def openFileDialog(self):
        print("PythonChannel: Received 'openFileDialog' call.")
        self.audio_engine.load_config_file()

    @pyqtSlot()
    def openKoFi(self):
        print("PythonChannel: Open Ko-Fi page.")
        import webbrowser
        webbrowser.open("https://ko-fi.com/painde0mie")

    @pyqtSlot(float)
    def set_q_factor(self, q):
        """Applique le même Q à tous les filtres et met à jour la courbe."""
        print(f"AudioEngine: Setting Q-factor of all bands to {q:.2f}.")
        self.q_values[:] = q
        if self.is_playing:
            self._apply_apo_config()
        self.calculate_frequency_response()

    @pyqtSlot(int, str, float)
    def setEqualizerPointParameter(self, index, key, value):
        self.audio_engine.set_equalizer_point_parameter(index, key, value)

class AudioEngine(QObject):
    """Moteur audio principal gérant l'égalisation et les configurations"""
    def __init__(self):
        super().__init__()
        self.py_channel = None
        self.is_playing = False
        
        # Paramètres d'égalisation par défaut
        self.bands = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        self.band_count = len(self.bands)  
        self.gains = np.zeros(len(self.bands))
        self.q_values = np.full(len(self.bands), 1.41)
        self.filter_types = ['PK'] * len(self.bands)
        
        self.pre_gain_db = 0.0
        self.bass_gain_db = 0.0
        self.treble_gain_db = 0.0

        # Gestion des configurations
        self.config_manager = ConfigManager(self)
        self.config_manager.load_configs()

        # Configuration AutoEQ
        self.AUTOEQ_BASE_URL = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
        self.AUTOEQ_CACHE_DIR = os.path.join(APP_CONFIGS_DIR, "autoeq_profiles")
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

        save_to_aez_file(
            filepath=f"{APP_CONFIGS_DIR}/temp_.aez",
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
        """Vérifie la présence de la configuration Equalizer APO"""
        if not os.path.exists(EAPO_CONFIG_PATH):
            msg = f"ERROR: Equalizer APO configuration file not found at the default location: {EAPO_CONFIG_PATH}. "
            print(msg, file=sys.stderr)
            if self.py_channel:
                self.py_channel.statusUpdate.emit(msg)
            return False
        return True

    def _update_and_emit_playback_state(self):
        """Met à jour l'état de lecture et émet le signal correspondant"""
        if self.py_channel:
            self.py_channel.playbackStateChanged.emit(self.is_playing)
            print(f"AudioEngine: Playback state updated to {self.is_playing}.")

    def _apply_apo_config(self):
        """Applique la configuration à Equalizer APO"""
        if not self.check_apo_config():
            return

        print("AudioEngine: Updating Equalizer APO configuration file...")

        try:
            config_lines = [f"Preamp: {self.pre_gain_db:.1f} dB"]

            # Filtres EQ utilisateur
            for i in range(len(self.bands)):
                filter_type = self.filter_types[i]
                fc = self.bands[i]
                gain = self.gains[i]
                q = self.q_values[i]

                # Pour les filtres shelf, ne pas mettre le paramètre Q si c'est 0 ou non applicable
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

            with open(EAPO_CONFIG_PATH, "w", encoding="utf-8") as f:
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

            save_to_aez_file(
                filepath=f"{APP_CONFIGS_DIR}/temp_.aez",
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
        """Démarre l'application de l'égaliseur"""
        if self.is_playing:
            print("AudioEngine: Playback is already active.")
            return
        
        if not self.check_apo_config():
            return

        print("AudioEngine: Starting equalizer via Equalizer APO.")
        self.is_playing = True
        self._apply_apo_config()
        
        if self.py_channel:
            self.py_channel.statusUpdate.emit("Equalizer is active.")
        self._update_and_emit_playback_state()
            
    def stop_playback(self):
        """Arrête l'application de l'égaliseur"""
        if not self.is_playing:
            print("AudioEngine: Equalizer is not active.")
            return
        
        if not self.check_apo_config():
            return
        
        print("AudioEngine: Stopping equalizer.")
        self.is_playing = False
        
        temp_gains = self.gains.copy()
        temp_preamp = self.pre_gain_db
        temp_bass_gain = self.bass_gain_db
        temp_treble_gain = self.treble_gain_db

        self.pre_gain_db = 0.0
        self.bass_gain_db = 0.0
        self.treble_gain_db = 0.0
        self._apply_apo_config()

        self.gains = temp_gains
        self.pre_gain_db = temp_preamp
        self.bass_gain_db = temp_bass_gain
        self.treble_gain_db = temp_treble_gain
        
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
        """Réinitialise tous les gains à zéro"""
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
        """Envoie une mise à jour complète de l'interface utilisateur"""
        print("AudioEngine: Sending a complete UI update.")
        if self.py_channel:
            self.py_channel.preampGainChanged.emit(self.pre_gain_db)
            self.py_channel.bassGainChanged.emit(self.bass_gain_db)
            self.py_channel.trebleGainChanged.emit(self.treble_gain_db)
            self.py_channel.configListUpdate.emit(self.config_manager.get_config_names(), self.config_manager.active_config)
        self.calculate_frequency_response()

    def get_current_config(self):
        """Récupère la configuration actuelle sous forme de dictionnaire"""
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
        """Charge une configuration spécifique"""
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
        """Sauvegarde la configuration actuelle"""
        config_data = self.get_current_config()
        self.config_manager.save_config(config_name, config_data)
        self.py_channel.statusUpdate.emit(f"Configuration '{config_name}' saved.")

    def export_config(self, export_data):
        """
        Gère la boîte de dialogue d'enregistrement pour l'exportation d'une seule configuration.
        Appelle ConfigManager.export_single_config.
        """
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
        """Exporte toutes les configurations"""
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
        """Importe une configuration à partir d'un fichier"""
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
        """Définit un paramètre spécifique pour un point de l'égaliseur"""
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

class ConfigManager(QObject):
    """Gère le chargement, la sauvegarde et l'importation des configurations"""
    def __init__(self, audio_engine):
        super().__init__()
        self.audio_engine = audio_engine
        self.configs = {}
        self.active_config = "Default"
        self.config_file = os.path.join(APP_CONFIGS_DIR, "presets.json")

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
    """Charge l'état d'égalisation à partir du fichier temporaire"""
    data = load_from_aez_file(f"{APP_CONFIGS_DIR}/temp_.aez")

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
    """Fenêtre principale de l'application"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AudioEZ - V1")
        self.setGeometry(100, 100, 1150, 900) 
        
        # Configuration de la vue web
        self.webview = QWebEngineView()
        self.webview.setContextMenuPolicy(Qt.NoContextMenu)
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, 'index.html')
        
        if not os.path.exists(html_path):
            QMessageBox.critical(self, "Error", f"The HTML file was not found at the location: {html_path}")
            sys.exit(1)

        self.webview.load(QUrl.fromLocalFile(html_path))
        
        page = self.webview.page()
        
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)

        self.audio_engine = AudioEngine()
        
        temp_settings = {}
        try:
            with open(settings_file, 'r') as f:
                temp_settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        rtgd_config = {
            'refine_window': temp_settings.get('adaptive_analysis_duration', 5.0),
            'hysteresis_delay': temp_settings.get('adaptive_hysteresis_delay', 10.0),
            'cooldown_period': temp_settings.get('adaptive_cooldown_period', 30.0)
        }
        
        self.adaptive_integration = None
        if temp_settings.get("adaptive_filter", False):
            try:
                from RTGD import AudioEZAdaptiveIntegration
                self.adaptive_integration = AudioEZAdaptiveIntegration(self.audio_engine, rtgd_config=rtgd_config)
                print("Adaptive Filter module loaded successfully.")
            except ImportError:
                print("Warning: Adaptive Filter is enabled in settings but RTGD module could not be imported.")
                print("Please ensure RTGD.py is in the correct directory and its dependencies are met.")
        
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

        # Vérification de l'installation d'Equalizer APO
        self.check_apo_installation()

        # Chargement de l'état persistant
        self.load_persistent_state()

        # Connexion des signaux
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
            
            # Appliquer AutoEQ si activé
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
            result = dialog.exec_()
            if result == QDialog.Accepted:
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
        
        # Sauvegarde de l'état persistant
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

            save_to_aez_file(
                filepath=f"{APP_CONFIGS_DIR}/temp_.aez",
                eq_parametric=eq_parametric_data,
                earphone_name=self.py_channel.earphone_name,
                earphone_curve=[self.py_channel._earphones_curve_freq, self.py_channel._earphones_curve_amp],
                target_name=self.py_channel.target_name,
                target_curve=[self.py_channel._target_curve_freq, self.py_channel._target_curve_amp]
            )
            print("État persistant sauvegardé.")
        
        event.accept()

if __name__ == "__main__":    
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('icon.ico'))

    verif = run_verification()
    if verif:
        window = AudioEZWindow()
        window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(1)