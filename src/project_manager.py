# src/project_manager.py
import os
import json
import shutil # <-- Assurez-vous que cet import est présent
import traceback # Pour delete_project
from . import utils # Use relative import within the package

PROJECTS_DIR = "projet" # Keep this relative for definition simplicity
PROJECT_CONFIG_FILE = "project_meta.json"
DEFAULT_MAIN_SCRIPT = "main.py"

# --- Fonction get_project_path (version avec chemin absolu) ---
def get_project_path(project_name):
    """Gets the FULL ABSOLUTE path to a project directory."""
    try:
        app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        app_root_dir = os.path.abspath(".")
    abs_projects_dir = os.path.join(app_root_dir, PROJECTS_DIR)
    project_path = os.path.join(abs_projects_dir, project_name)
    return os.path.abspath(project_path)

# --- Fonctions existantes ---
def ensure_projects_dir():
    """Creates the main projects directory if it doesn't exist using absolute path."""
    app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_projects_dir = os.path.join(app_root_dir, PROJECTS_DIR)
    if not os.path.exists(abs_projects_dir):
        print(f"Creating projects directory: {abs_projects_dir}")
        os.makedirs(abs_projects_dir)

def list_projects():
    """Lists existing projects by checking subdirectories in PROJECTS_DIR."""
    # Utiliser le chemin absolu pour lister est plus sûr
    try:
        app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_projects_dir = os.path.join(app_root_dir, PROJECTS_DIR)
        ensure_projects_dir() # S'assurer qu'il existe
        projects = []
        if os.path.exists(abs_projects_dir): # Vérifier avant de lister
            for item in os.listdir(abs_projects_dir):
                item_path = os.path.join(abs_projects_dir, item)
                if os.path.isdir(item_path):
                    # Vérification simple : contient main.py ou un .venv ?
                    # (get_project_venv_path a besoin du chemin de base)
                    venv_path_rel = os.path.join(item, ".venv") # Chemin relatif pour utils.get...
                    # Note: utils.get_project_venv_path attend le chemin *base* du projet
                    # La vérification ici pourrait être simplifiée ou améliorée
                    if os.path.exists(os.path.join(item_path, DEFAULT_MAIN_SCRIPT)):
                         # or os.path.exists(utils.get_project_venv_path(item_path)): # get_project_venv_path attend le chemin base
                         projects.append(item)
                    elif os.path.exists(os.path.join(item_path, ".venv")): # Check plus direct
                          projects.append(item)

        return sorted(projects)
    except Exception as e:
        print(f"Error listing projects: {e}")
        traceback.print_exc()
        return [] # Retourner liste vide en cas d'erreur

def create_project(project_name):
    """Creates a new project directory and basic structure."""
    project_path = get_project_path(project_name) # Chemin absolu
    if os.path.exists(project_path):
        print(f"Project '{project_name}' already exists at {project_path}.")
        return False
    try:
        print(f"Creating project '{project_name}' at {project_path}...")
        os.makedirs(project_path)
        main_script_path = os.path.join(project_path, DEFAULT_MAIN_SCRIPT)
        with open(main_script_path, 'w', encoding='utf-8') as f:
            f.write(f"# Project: {project_name}\nprint('Hello from project {project_name}!')\n")
        print(f"Attempting to create venv for {project_name}...")
        if not utils.ensure_project_venv(project_path): # Passe le chemin absolu
             print(f"Warning: Failed to create initial venv for {project_name}")
             # return False # Décommenter pour échouer si venv échoue
        save_project_metadata(project_name, {"name": project_name, "dependencies": []})
        print(f"Project '{project_name}' created successfully.")
        return True
    except Exception as e:
        print(f"Error creating project '{project_name}': {e}"); traceback.print_exc()
        # Tentative de nettoyage partiel (optionnel et prudent)
        # if os.path.exists(project_path):
        #     try: shutil.rmtree(project_path); print("Cleaned up partial directory.")
        #     except Exception as cleanup_e: print(f"Error during cleanup: {cleanup_e}")
        return False

def load_project_metadata(project_name):
    """Loads metadata from the project's config file."""
    project_path = get_project_path(project_name)
    config_path = os.path.join(project_path, PROJECT_CONFIG_FILE)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: print(f"Error loading metadata for {project_name}: {e}")
    return {"name": project_name, "dependencies": []}

def save_project_metadata(project_name, metadata):
    """Saves metadata to the project's config file."""
    project_path = get_project_path(project_name)
    config_path = os.path.join(project_path, PROJECT_CONFIG_FILE)
    try:
        os.makedirs(project_path, exist_ok=True) # Assurer que le dossier existe
        with open(config_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
    except Exception as e: print(f"Error saving metadata for {project_name}: {e}")

def get_project_script_content(project_name, script_name=DEFAULT_MAIN_SCRIPT):
    """Reads the content of a script file within the project."""
    script_path = os.path.join(get_project_path(project_name), script_name)
    if os.path.exists(script_path):
        try:
            with open(script_path, 'r', encoding='utf-8') as f: return f.read()
        except Exception as e: print(f"Error reading script {script_path}: {e}"); return f"# Error reading file: {e}"
    return "# Script not found" # Retourner si le fichier n'existe pas

def save_project_script_content(project_name, content, script_name=DEFAULT_MAIN_SCRIPT):
    """Writes content to a script file within the project."""
    project_path = get_project_path(project_name)
    script_path = os.path.join(project_path, script_name)
    try:
        os.makedirs(project_path, exist_ok=True) # Assurer que le dossier existe
        with open(script_path, 'w', encoding='utf-8') as f: f.write(content)
        print(f"Script '{script_name}' saved for project '{project_name}'.")
        return True
    except Exception as e: print(f"Error writing script {script_path}: {e}"); return False

# --- NOUVELLE FONCTION DE SUPPRESSION ---
def delete_project(project_name: str) -> bool:
    """Deletes the entire project directory permanently."""
    try:
        project_path = get_project_path(project_name) # Chemin absolu
        print(f"Attempting to delete project at: {project_path}")
        if not os.path.isdir(project_path): print(f"Error: Directory not found: {project_path}"); return False

        # Sécurité : Vérifier qu'on est dans le dossier projet attendu
        app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_projects_dir = os.path.abspath(os.path.join(app_root_dir, PROJECTS_DIR))
        # Vérifie que project_path commence bien par abs_projects_dir + séparateur
        if not project_path.startswith(os.path.join(abs_projects_dir, '')): # os.path.join assure le bon séparateur
             print(f"CRITICAL ERROR: Path '{project_path}' is outside projects dir '{abs_projects_dir}'. Aborting delete.")
             return False

        shutil.rmtree(project_path) # Suppression récursive
        print(f"Project '{project_name}' deleted successfully from {project_path}.")
        return True

    except Exception as e:
        print(f"!!!!!!!! ERROR deleting project '{project_name}' !!!!!!!!")
        print(traceback.format_exc())
        return False
# --- FIN NOUVELLE FONCTION ---