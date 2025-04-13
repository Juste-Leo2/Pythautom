# src/exporter.py
# No changes needed from the previous version for streaming/LM Studio fix.
# It already uses the progress_callback correctly.
import os
import platform
import subprocess
import shutil
import tempfile
import traceback
from typing import Callable

# Importe les modules du projet (attention aux imports relatifs)
try:
    from . import project_manager
    from . import utils
except ImportError:
    # Fallback si exécuté hors contexte (peu probable ici)
    print("WARNING: exporter.py running with fallback imports.")
    import project_manager
    import utils

# Renamed helper to be clearer, passes messages directly to callback
def _report_progress(message: str, callback: Callable[[str], None]):
    """Helper function to print and send progress via callback."""
    print(f"[Exporter] {message}")
    # The callback function (likely in GUI) will handle prepending "Export:" if needed
    callback(message)

def create_executable_bundle(project_name: str, output_zip_path: str, progress_callback: Callable[[str], None]) -> bool:
    """
    Creates a standalone executable bundle for the current OS using PyInstaller.

    Args:
        project_name: The name of the project to export.
        output_zip_path: The full path where the final .zip file should be saved.
        progress_callback: A function to call to report progress/errors to the GUI console.

    Returns:
        True if the export was successful, False otherwise.
    """
    _report_progress(f"Starting export for project '{project_name}'...", callback=progress_callback)
    build_dir = None # Pour le nettoyage dans finally
    dist_dir = None  # Pour le nettoyage dans finally
    success = False  # Flag pour le retour final

    try:
        # 1. Obtenir les chemins nécessaires
        _report_progress("Getting project paths...", callback=progress_callback)
        try:
            project_path = project_manager.get_project_path(project_name) # Gets absolute path
            main_script_name = project_manager.DEFAULT_MAIN_SCRIPT # Nom du script principal
            main_script_path = os.path.join(project_path, main_script_name)
            if not os.path.exists(main_script_path):
                raise FileNotFoundError(f"Main script '{main_script_name}' not found in project at '{project_path}'.")
        except Exception as e:
            _report_progress(f"Error getting project paths: {e}", callback=progress_callback)
            return False # Ne peut pas continuer sans les chemins

        # 2. Assurer l'existence du Venv
        _report_progress("Ensuring virtual environment exists...", callback=progress_callback)
        # Pass the progress callback down to utils.ensure_project_venv
        if not utils.ensure_project_venv(project_path, progress_callback=progress_callback):
            _report_progress("Failed to ensure virtual environment.", callback=progress_callback)
            return False

        # 3. Installer PyInstaller dans le Venv
        _report_progress("Installing PyInstaller in project venv...", callback=progress_callback)
        # Pass the progress callback down to utils.install_project_dependencies
        install_ok = utils.install_project_dependencies(project_path, ["pyinstaller"], progress_callback=progress_callback)
        if not install_ok:
            _report_progress("Failed to install PyInstaller.", callback=progress_callback)
            # utils.install_project_dependencies should have logged errors via callback
            return False
        _report_progress("PyInstaller installed successfully.", callback=progress_callback)

        # 4. Obtenir le chemin Python du Venv
        _report_progress("Getting Python executable from venv...", callback=progress_callback)
        python_exe = utils.get_project_python_executable(project_path)
        if not python_exe or not os.path.exists(python_exe):
            _report_progress(f"Could not find Python executable in venv (checked: {python_exe}).", callback=progress_callback)
            return False

        # 5. Créer des répertoires temporaires pour la construction
        build_dir = tempfile.mkdtemp(prefix=f"pythautom_{project_name}_build_")
        dist_dir = tempfile.mkdtemp(prefix=f"pythautom_{project_name}_dist_")
        _report_progress(f"Using temp build dir: {build_dir}", callback=progress_callback)
        _report_progress(f"Using temp dist dir: {dist_dir}", callback=progress_callback)

        # 6. Définir les options PyInstaller
        pyinstaller_options = [
            "--noconsole",        # No console window for the final app
            "--onedir",           # Create a folder containing the executable and dependencies
            f"--name={project_name}", # Name of the executable and output folder
            "--distpath", dist_dir,   # Where to put the final bundled folder
            "--workpath", build_dir,  # Where to put temporary build files
            # Add hidden imports if needed
            # "--hidden-import=pkg_resources.py2_warn",
            # Add data files if needed
            # "--add-data=path/to/data:destination/folder",
            main_script_name      # The main script relative to CWD (project_path)
        ]
        command = [python_exe, "-m", "PyInstaller"] + pyinstaller_options

        # 7. Exécuter PyInstaller
        _report_progress("Running PyInstaller... (This can take some time)", callback=progress_callback)
        print(f"[Exporter] Executing command: {' '.join(map(repr, command))}")
        print(f"[Exporter]          with CWD: {repr(project_path)}")
        pyinstaller_process = subprocess.run(
            command,
            cwd=project_path, # Execute from the project's directory
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        # Log PyInstaller output via callback
        if pyinstaller_process.stdout:
             _report_progress("--- PyInstaller STDOUT ---", callback=progress_callback)
             for line in pyinstaller_process.stdout.splitlines():
                 _report_progress(line, callback=progress_callback)
             _report_progress("--- End PyInstaller STDOUT ---", callback=progress_callback)
        if pyinstaller_process.stderr:
             _report_progress("--- PyInstaller STDERR ---", callback=progress_callback)
             for line in pyinstaller_process.stderr.splitlines():
                  _report_progress(line, callback=progress_callback)
             _report_progress("--- End PyInstaller STDERR ---", callback=progress_callback)

        # 8. Vérifier le résultat PyInstaller
        if pyinstaller_process.returncode != 0:
            _report_progress(f"PyInstaller failed! (Exit Code: {pyinstaller_process.returncode})", callback=progress_callback)
            return False
        else:
             _report_progress("PyInstaller completed successfully.", callback=progress_callback)

        # 9. Zipper le dossier de sortie
        app_folder_path = os.path.join(dist_dir, project_name)
        if not os.path.isdir(app_folder_path):
             _report_progress(f"Error: PyInstaller output folder '{app_folder_path}' not found in dist directory '{dist_dir}'.", callback=progress_callback)
             return False

        _report_progress(f"Creating archive '{os.path.basename(output_zip_path)}'...", callback=progress_callback)
        try:
            os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
            zip_base_name = output_zip_path.rsplit('.', 1)[0]
            shutil.make_archive(
                base_name=zip_base_name,
                format='zip',
                root_dir=dist_dir,
                base_dir=project_name
            )
            _report_progress("Archive created successfully.", callback=progress_callback)
            success = True
        except Exception as zip_e:
            _report_progress(f"Error creating zip archive: {zip_e}", callback=progress_callback)
            traceback.print_exc()
            return False

        return success

    except Exception as e:
        error_msg = f"An unexpected error occurred during export: {e}"
        _report_progress(error_msg, callback=progress_callback)
        print(f"[Exporter] {error_msg}")
        traceback.print_exc()
        return False

    finally:
        # 10. Nettoyage
        try:
            if build_dir and os.path.exists(build_dir):
                print(f"[Exporter] Cleaning up temp build directory: {build_dir}")
                try: shutil.rmtree(build_dir)
                except OSError as rm_err:
                    print(f"[Exporter] Warning: Error removing build dir {build_dir}: {rm_err}")
                    _report_progress(f"Warning: Error cleaning up temp build dir: {rm_err}", callback=progress_callback)

            if dist_dir and os.path.exists(dist_dir):
                 print(f"[Exporter] Cleaning up temp dist directory: {dist_dir}")
                 try: shutil.rmtree(dist_dir)
                 except OSError as rm_err:
                    print(f"[Exporter] Warning: Error removing dist dir {dist_dir}: {rm_err}")
                    _report_progress(f"Warning: Error cleaning up temp dist dir: {rm_err}", callback=progress_callback)
        except Exception as cleanup_e:
             final_warning = f"Warning: Error during cleanup of temp dirs: {cleanup_e}"
             _report_progress(final_warning, callback=progress_callback)
             print(f"[Exporter] {final_warning}")
             traceback.print_exc()