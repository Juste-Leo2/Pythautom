# src/project_manager.py
# Needs re import added in main.py or here
import os
import json
import shutil
import traceback
import re # Added for sanitization
import datetime # Added for timestamp in metadata
from . import utils # Use relative import within the package

PROJECTS_DIR = "projets" # Keep consistent spelling
PROJECT_CONFIG_FILE = "project_meta.json"
DEFAULT_MAIN_SCRIPT = "main.py"

def get_absolute_projects_dir():
    """Gets the absolute path to the main projects directory."""
    try:
        # Assumes project_manager.py is in src/
        app_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        app_root_dir = os.path.abspath(".")
        if os.path.basename(app_root_dir) == 'src':
            app_root_dir = os.path.dirname(app_root_dir)

    abs_projects_dir = os.path.join(app_root_dir, PROJECTS_DIR)
    src_dir_check = os.path.join(app_root_dir, 'src')
    # Use relative path from CWD only as a last resort if absolute doesn't exist but relative does
    if not os.path.exists(abs_projects_dir) and os.path.exists(PROJECTS_DIR) and not os.path.isdir(src_dir_check):
         print(f"Warning: Absolute path '{abs_projects_dir}' not found, falling back to relative '{PROJECTS_DIR}'")
         return os.path.abspath(PROJECTS_DIR)

    return os.path.abspath(abs_projects_dir)

def get_project_path(project_name):
    """Gets the FULL ABSOLUTE path to a specific project directory."""
    # Use os.path.basename to prevent user providing path elements
    base_name = os.path.basename(project_name)
    # Sanitize allowing alphanumeric, underscore, hyphen, period
    safe_project_name = re.sub(r'[^\w.\-]+', '_', base_name)
    safe_project_name = safe_project_name.strip('_') # Remove leading/trailing underscores

    if safe_project_name != project_name:
         print(f"Warning: Project name sanitized from '{project_name}' to '{safe_project_name}' for path usage.")

    if not safe_project_name or safe_project_name in ['.', '..']:
        raise ValueError(f"Invalid project name for path after sanitization: '{project_name}' -> '{safe_project_name}'")

    abs_projects_dir = get_absolute_projects_dir()
    project_path = os.path.join(abs_projects_dir, safe_project_name)
    return os.path.abspath(project_path) # Normalize

def ensure_projects_dir():
    """Creates the main projects directory if it doesn't exist using absolute path."""
    abs_projects_dir = get_absolute_projects_dir()
    if not os.path.exists(abs_projects_dir):
        try:
            print(f"Creating projects directory: {abs_projects_dir}")
            os.makedirs(abs_projects_dir)
        except OSError as e:
            print(f"ERROR: Could not create projects directory '{abs_projects_dir}': {e}")
            raise # Re-raise

def list_projects():
    """Lists existing projects by checking subdirectories in PROJECTS_DIR."""
    projects = []
    abs_projects_dir = get_absolute_projects_dir()
    try:
        ensure_projects_dir() # Make sure base directory exists
        if not os.path.isdir(abs_projects_dir):
             print(f"Error: Projects directory '{abs_projects_dir}' is not accessible.")
             return []

        for item in os.listdir(abs_projects_dir):
            item_path = os.path.join(abs_projects_dir, item)
            # Check: is it a directory AND contains default script OR metadata file?
            if os.path.isdir(item_path) and \
               (os.path.exists(os.path.join(item_path, DEFAULT_MAIN_SCRIPT)) or \
                os.path.exists(os.path.join(item_path, PROJECT_CONFIG_FILE))):
                 projects.append(item)

        return sorted(projects)
    except Exception as e:
        print(f"Error listing projects in '{abs_projects_dir}': {e}")
        traceback.print_exc()
        return []

def create_project(project_name):
    """Creates a new project directory and basic structure."""
    base_name = os.path.basename(project_name)
    safe_project_name = re.sub(r'[^\w-]+', '_', base_name) # No periods allowed in dir name usually
    safe_project_name = safe_project_name.strip('_')
    if not safe_project_name or safe_project_name in ['.', '..']:
         print(f"Error: Invalid project name after sanitization: '{project_name}' -> '{safe_project_name}'")
         return False
    if safe_project_name != project_name:
         print(f"Note: Project name sanitized to '{safe_project_name}' for directory.")

    project_path = get_project_path(safe_project_name) # Uses the already sanitized name
    if os.path.exists(project_path):
        print(f"Project '{safe_project_name}' already exists at {project_path}.")
        return False
    try:
        print(f"Creating project '{safe_project_name}' at {project_path}...")
        os.makedirs(project_path)
        main_script_path = os.path.join(project_path, DEFAULT_MAIN_SCRIPT)
        with open(main_script_path, 'w', encoding='utf-8') as f:
            f.write(f"# Project: {safe_project_name}\n\nprint('Hello from project {safe_project_name}!')\n")

        print(f"Attempting to create venv for {safe_project_name}...")
        venv_created = utils.ensure_project_venv(project_path, progress_callback=lambda msg: print(f"[venv setup] {msg}"))
        if not venv_created:
             print(f"Warning: Failed to create initial venv for {safe_project_name}")
             # return False # Decide if fatal

        initial_metadata = {
            "name": safe_project_name,
            "dependencies": [],
            "created_at": datetime.datetime.now().isoformat() # Use ISO format
        }
        save_project_metadata(safe_project_name, initial_metadata)

        print(f"Project '{safe_project_name}' created successfully.")
        return True
    except Exception as e:
        print(f"Error creating project '{safe_project_name}': {e}")
        traceback.print_exc()
        if os.path.exists(project_path):
             try: shutil.rmtree(project_path); print(f"Cleaned up partially created: {project_path}")
             except Exception as cleanup_e: print(f"Error during cleanup: {cleanup_e}")
        return False

def load_project_metadata(project_name):
    """Loads metadata from the project's config file."""
    try:
        project_path = get_project_path(project_name) # Handles sanitization/path finding
        config_path = os.path.join(project_path, PROJECT_CONFIG_FILE)
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
             # Return default structure if file missing, using the sanitized name
             return {"name": os.path.basename(project_path), "dependencies": []}
    except ValueError as e:
        print(f"Error loading metadata (invalid name?): {e}")
        return {"name": "Invalid Project", "dependencies": []}
    except Exception as e:
        print(f"Error loading metadata for '{project_name}': {e}")
        traceback.print_exc()
        return {"name": project_name, "dependencies": [], "error": str(e)}

def save_project_metadata(project_name, metadata):
    """Saves metadata to the project's config file."""
    try:
        project_path = get_project_path(project_name) # Handles sanitization/path finding
        config_path = os.path.join(project_path, PROJECT_CONFIG_FILE)
        os.makedirs(project_path, exist_ok=True)
        # Add last modified timestamp
        metadata['last_modified'] = datetime.datetime.now().isoformat()
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        # print(f"Metadata saved for '{project_name}'.") # Reduce console noise
        return True
    except ValueError as e:
         print(f"Error saving metadata (invalid name?): {e}")
         return False
    except Exception as e:
        print(f"Error saving metadata for '{project_name}': {e}")
        traceback.print_exc()
        return False

def get_project_script_content(project_name, script_name=DEFAULT_MAIN_SCRIPT):
    """Reads the content of a script file within the project."""
    try:
        project_path = get_project_path(project_name)
        script_path = os.path.join(project_path, script_name)
        if os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # print(f"Script '{script_name}' not found in project '{project_name}'.")
            return f"# Script '{script_name}' not found."
    except ValueError as e:
        print(f"Error getting script content (invalid name?): {e}")
        return f"# Error: {e}"
    except Exception as e:
        print(f"Error reading script '{script_name}' for '{project_name}': {e}")
        # traceback.print_exc() # Reduce console noise
        return f"# Error reading file: {e}"

def save_project_script_content(project_name, content, script_name=DEFAULT_MAIN_SCRIPT):
    """Writes content to a script file within the project."""
    try:
        project_path = get_project_path(project_name)
        script_path = os.path.join(project_path, script_name)
        os.makedirs(project_path, exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(content)
        # print(f"Script '{script_name}' saved for project '{project_name}'.") # Reduce noise
        # Update metadata last modified time on code save
        metadata = load_project_metadata(project_name)
        save_project_metadata(project_name, metadata) # save_project_metadata adds timestamp
        return True
    except ValueError as e:
        print(f"Error saving script content (invalid name?): {e}")
        return False
    except Exception as e:
        print(f"Error writing script '{script_name}' for '{project_name}': {e}")
        traceback.print_exc()
        return False

def delete_project(project_name: str) -> bool:
    """Deletes the entire project directory permanently."""
    try:
        project_path = get_project_path(project_name) # Handles path finding and basic validation
        print(f"Attempting to delete project at resolved path: {project_path}")

        if not os.path.isdir(project_path):
            print(f"Error: Directory not found or is not a directory: {project_path}")
            return False

        abs_projects_dir = get_absolute_projects_dir()
        # Check if project_path is inside abs_projects_dir and not the dir itself
        proj_real = os.path.realpath(project_path)
        proj_dir_real = os.path.realpath(abs_projects_dir)
        if not proj_real.startswith(proj_dir_real + os.sep):
             print(f"CRITICAL ERROR: Path '{proj_real}' is outside projects dir '{proj_dir_real}'. Aborting delete.")
             return False
        if os.path.samefile(proj_real, proj_dir_real):
             print(f"CRITICAL ERROR: Attempting to delete the main projects directory '{proj_dir_real}'. Aborting delete.")
             return False

        shutil.rmtree(project_path) # Recursive delete
        print(f"Project '{project_name}' deleted successfully from {project_path}.")
        return True

    except ValueError as e:
         print(f"Error deleting project (invalid name?): {e}")
         return False
    except Exception as e:
        print(f"!!!!!!!! ERROR deleting project '{project_name}' !!!!!!!!")
        print(traceback.format_exc())
        return False