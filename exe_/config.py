RPC = None

client_id = '1402724529851072583'
EAPO_INSTALL_PATH = r"C:\Program Files\EqualizerAPO"
EAPO_CONFIG_PATH = None
APP_CONFIGS_DIR = "./configs"
settings_file = None

def initialize_paths():
    global EAPO_CONFIG_PATH, settings_file
    import os
    EAPO_CONFIG_PATH = os.path.join(EAPO_INSTALL_PATH, "config", "config.txt")
    settings_file = os.path.join(APP_CONFIGS_DIR, 'settings.json')