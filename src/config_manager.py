# src/config_manager.py

import os
import json
import traceback
from typing import Optional, Dict, Any, Union

# --- Constants ---
CONFIG_FILE_NAME = ".pythautom_config.json"
DEFAULT_CONFIG = {
    "version": 1,
    "llm_settings": {
        "gemini": {
            "api_key": None,
            "last_model_used": None # Optionnel: sauvegarder le dernier modèle utilisé
        },
        "lmstudio": {
            "last_ip_used": None,
            "last_port_used": None
        }
        # Potentiellement d'autres backends ici
    },
    "ui_settings": {
        # Ex: "show_logs_on_startup": False
    }
}

# --- Module State ---
# Stocke la configuration chargée en mémoire
_current_config: Dict[str, Any] = {}

# --- Helper Functions ---

def _get_config_path() -> str:
    """Gets the absolute path to the configuration file."""
    try:
        # Trouve la racine de l'application (où se trouve main.py)
        # Assume config_manager.py est dans src/
        app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        # Fallback si __file__ n'est pas défini (rare)
        app_root_dir = os.path.abspath(".")
        if os.path.basename(app_root_dir) == 'src':
            app_root_dir = os.path.dirname(app_root_dir)

    # Vérifie si on est bien à la racine attendue (là où 'src' ou 'main.py' devrait être)
    expected_marker = os.path.join(app_root_dir, 'src')
    if not os.path.isdir(expected_marker) and not os.path.exists(os.path.join(app_root_dir, 'main.py')):
         print(f"Warning: Config path guessing based on '{app_root_dir}', structure might be unexpected.")

    return os.path.join(app_root_dir, CONFIG_FILE_NAME)

def _merge_defaults(loaded_config: Dict[str, Any]) -> Dict[str, Any]:
    """Merges loaded config with defaults to handle missing keys gracefully."""
    # Copie profonde pour éviter de modifier DEFAULT_CONFIG
    merged_config = json.loads(json.dumps(DEFAULT_CONFIG))

    def _recursive_update(target: Dict, source: Dict):
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                _recursive_update(target[key], value)
            elif key in target: # Only update if key exists in default structure
                 target[key] = value

    _recursive_update(merged_config, loaded_config)
    # Check version compatibility (simple check for now)
    if merged_config.get("version") != DEFAULT_CONFIG.get("version"):
        print(f"Warning: Configuration version mismatch (loaded: {merged_config.get('version')}, expected: {DEFAULT_CONFIG.get('version')}). Using loaded structure.")
        # For more complex cases, migration logic would be needed here.
        # For now, we just keep the loaded structure if version is different.
        merged_config = loaded_config # Revert to loaded if versions differ drastically

    return merged_config


# --- Public API ---

def load_app_config():
    """Loads the application configuration from the JSON file.
       Populates the internal _current_config state.
    """
    global _current_config
    config_path = _get_config_path()
    print(f"[Config] Attempting to load config from: {config_path}")

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # Merge with defaults to ensure all keys exist
                _current_config = _merge_defaults(loaded_data)
                print("[Config] Configuration loaded successfully.")
        except json.JSONDecodeError:
            print(f"ERROR: Failed to decode JSON from '{config_path}'. Using default config.")
            traceback.print_exc()
            _current_config = json.loads(json.dumps(DEFAULT_CONFIG)) # Use deep copy of default
        except Exception as e:
            print(f"ERROR: Failed to load config file '{config_path}': {e}. Using default config.")
            traceback.print_exc()
            _current_config = json.loads(json.dumps(DEFAULT_CONFIG))
    else:
        print("[Config] Configuration file not found. Using default config.")
        _current_config = json.loads(json.dumps(DEFAULT_CONFIG))

    # Ensure essential structure exists even after loading/defaulting
    _current_config.setdefault("llm_settings", {}).setdefault("gemini", {})
    _current_config["llm_settings"]["gemini"].setdefault("api_key", None)


def save_app_config():
    """Saves the current application configuration to the JSON file."""
    global _current_config
    config_path = _get_config_path()
    print(f"[Config] Saving configuration to: {config_path}")
    try:
        # Ensure the directory exists (should normally be project root)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(_current_config, f, indent=4)
        print("[Config] Configuration saved successfully.")
        return True
    except Exception as e:
        print(f"ERROR: Failed to save config file '{config_path}': {e}")
        traceback.print_exc()
        return False

# --- Getters ---

def get_api_key() -> Optional[str]:
    """Gets the saved Gemini API key."""
    # Assure que load_app_config a été appelé au moins une fois
    if not _current_config:
        load_app_config()
    # Utilise .get() pour éviter les KeyErrors si la structure est corrompue
    return _current_config.get("llm_settings", {}).get("gemini", {}).get("api_key")

def get_last_used_gemini_model() -> Optional[str]:
    """Gets the last saved Gemini model name."""
    if not _current_config: load_app_config()
    return _current_config.get("llm_settings", {}).get("gemini", {}).get("last_model_used")

def get_last_used_lmstudio_ip() -> Optional[str]:
    """Gets the last saved LM Studio IP."""
    if not _current_config: load_app_config()
    return _current_config.get("llm_settings", {}).get("lmstudio", {}).get("last_ip_used")

def get_last_used_lmstudio_port() -> Optional[int]:
    """Gets the last saved LM Studio port."""
    if not _current_config: load_app_config()
    port = _current_config.get("llm_settings", {}).get("lmstudio", {}).get("last_port_used")
    # Convertit en int si c'est une chaîne valide, sinon None
    if isinstance(port, str) and port.isdigit():
        return int(port)
    elif isinstance(port, int):
        return port
    else:
        return None

# --- Setters ---

def set_api_key(api_key: Optional[str]):
    """Sets the Gemini API key and saves the configuration."""
    global _current_config
    # Assure que la structure existe
    if "llm_settings" not in _current_config: _current_config["llm_settings"] = {}
    if "gemini" not in _current_config["llm_settings"]: _current_config["llm_settings"]["gemini"] = {}

    # Met à jour la clé (même si elle est None)
    _current_config["llm_settings"]["gemini"]["api_key"] = api_key
    print(f"[Config] API Key updated in memory.")
    save_app_config() # Sauvegarde immédiatement

def set_last_used_gemini_model(model_name: Optional[str]):
    """Sets the last used Gemini model name and saves the configuration."""
    global _current_config
    if "llm_settings" not in _current_config: _current_config["llm_settings"] = {}
    if "gemini" not in _current_config["llm_settings"]: _current_config["llm_settings"]["gemini"] = {}
    _current_config["llm_settings"]["gemini"]["last_model_used"] = model_name
    save_app_config()

def set_last_used_lmstudio_details(ip: Optional[str], port: Optional[Union[int, str]]):
    """Sets the last used LM Studio details and saves the configuration."""
    global _current_config
    if "llm_settings" not in _current_config: _current_config["llm_settings"] = {}
    if "lmstudio" not in _current_config["llm_settings"]: _current_config["llm_settings"]["lmstudio"] = {}

    # Assure que le port est stocké comme un int si possible
    port_int = None
    if isinstance(port, str) and port.isdigit(): port_int = int(port)
    elif isinstance(port, int): port_int = port

    _current_config["llm_settings"]["lmstudio"]["last_ip_used"] = ip
    _current_config["llm_settings"]["lmstudio"]["last_port_used"] = port_int
    save_app_config()

# --- Initial Load ---
# Charge la configuration lorsque le module est importé pour la première fois
# Note: Cela signifie que main.py n'a plus besoin de l'appeler explicitement,
# mais c'est bien de le garder là pour la clarté du flux de démarrage.
# load_app_config()
# -> Commenté car main.py l'appelle déjà explicitement. On peut choisir l'un ou l'autre.
# -> Laisser l'appel dans main.py est plus clair pour l'ordre d'exécution.