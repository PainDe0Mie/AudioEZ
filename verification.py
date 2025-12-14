import subprocess, shutil, urllib.request, winreg, os, json, re, time, sys, csv
from PyQt6.QtWidgets import QProgressBar, QTextEdit, QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal, QThread, Qt
from PyQt6.QtGui import QFont
from pathlib import Path
from typing import List, Tuple

class VerificationThread(QThread):
    progress_update = pyqtSignal(str, int)
    verification_complete = pyqtSignal(bool, str)
    task_progress_update = pyqtSignal(int, int)
    
    def __init__(self):
        super().__init__()
        if getattr(sys, 'frozen', False):
            self.base_path = Path(sys.executable).parent
        else:
            self.base_path = Path(__file__).parent

        self.autoeq_repo = "https://github.com/jaakkopasanen/AutoEq"
        self.audioez_repo = "https://github.com/PainDe0Mie/AudioEZ"
        self.required_libs = [
            'PyQt6', 'numpy', 'scipy', 'sounddevice', 'pypresence',
            'requests', 'autoeq'
        ]
        
    def run(self):
        try:
            self.progress_update.emit("Checking required libraries...", 10)
            missing_libs = self.check_libraries()
            #missing_libs = False # Because compilated with all libs
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
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Message de statut
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
    dialog = VerificationDialog(parent)
    dialog.start_verification()
    result = dialog.exec()
    return result == QDialog.DialogCode.Accepted