# src/exporter.py
import os
import platform
import subprocess
import shutil
import tempfile
import traceback
from typing import Callable, List

# Importe les modules du projet
try:
    from . import project_manager
    from . import utils
except ImportError:
    print("WARNING: exporter.py running with fallback imports.")
    import project_manager
    import utils

# Fonction helper pour les logs
def _report_progress(message: str, callback: Callable[[str], None]):
    print(f"[Exporter] {message}")
    callback(message)


def create_executable_bundle(project_name: str, output_zip_path: str, progress_callback: Callable[[str], None]) -> bool:
    """
    Crée un bundle exécutable autonome en utilisant PyInstaller,
    puis copie manuellement les fichiers de données. (Méthode 1)
    """
    _report_progress(f"Starting PyInstaller export for project '{project_name}'...", callback=progress_callback)
    build_dir = None
    dist_dir = None
    success = False

    try:
        # 1. Obtenir les chemins
        _report_progress("Getting project paths...", callback=progress_callback)
        try:
            project_path = project_manager.get_project_path(project_name)
            main_script_name = project_manager.DEFAULT_MAIN_SCRIPT
            main_script_path = os.path.join(project_path, main_script_name)
            if not os.path.exists(main_script_path):
                raise FileNotFoundError(f"Main script '{main_script_name}' not found in project at '{project_path}'.")
        except Exception as e:
            _report_progress(f"Error getting project paths: {e}", callback=progress_callback)
            return False

        # 2. Assurer Venv
        _report_progress("Ensuring virtual environment exists...", callback=progress_callback)
        if not utils.ensure_project_venv(project_path, progress_callback=progress_callback):
            _report_progress("Failed to ensure virtual environment.", callback=progress_callback)
            return False

        # 3. Installer PyInstaller
        _report_progress("Installing PyInstaller in project venv...", callback=progress_callback)
        install_ok = utils.install_project_dependencies(project_path, ["pyinstaller"], progress_callback=progress_callback)
        if not install_ok:
            _report_progress("Failed to install PyInstaller.", callback=progress_callback)
            return False
        _report_progress("PyInstaller installed successfully.", callback=progress_callback)

        # 4. Obtenir Python Exe
        _report_progress("Getting Python executable from venv...", callback=progress_callback)
        python_exe = utils.get_project_python_executable(project_path)
        if not python_exe or not os.path.exists(python_exe):
            _report_progress(f"Could not find Python executable in venv (checked: {python_exe}).", callback=progress_callback)
            return False

        # 5. Créer Dirs Temp
        build_dir = tempfile.mkdtemp(prefix=f"pythautom_{project_name}_build_")
        dist_dir = tempfile.mkdtemp(prefix=f"pythautom_{project_name}_dist_")
        _report_progress(f"Using temp build dir: {build_dir}", callback=progress_callback)
        _report_progress(f"Using temp dist dir: {dist_dir}", callback=progress_callback)

        # 6. Définir les options PyInstaller (SANS --add-data initialement)
        pyinstaller_options = [
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            f"--name={project_name}",
            "--distpath", dist_dir,
            "--workpath", build_dir,
            main_script_name
        ]
        command = [python_exe, "-m", "PyInstaller"] + pyinstaller_options

        # 7. Exécuter PyInstaller
        _report_progress("Running PyInstaller... (This can take some time)", callback=progress_callback)
        command_str_log = ' '.join(map(repr, command))
        _report_progress(f"Executing: {command_str_log}", callback=progress_callback)
        _report_progress(f"     in CWD: {repr(project_path)}", callback=progress_callback)

        pyinstaller_process = subprocess.run(
            command,
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=600
        )

        # Log sortie PyInstaller (inchangé)
        # ... (code de log identique à la version précédente) ...
        if pyinstaller_process.stdout:
             _report_progress("--- PyInstaller STDOUT ---", callback=progress_callback)
             for line in pyinstaller_process.stdout.splitlines(): _report_progress(line, callback=progress_callback)
             _report_progress("--- End PyInstaller STDOUT ---", callback=progress_callback)
        if pyinstaller_process.stderr:
             _report_progress("--- PyInstaller STDERR ---", callback=progress_callback)
             for line in pyinstaller_process.stderr.splitlines(): _report_progress(line, callback=progress_callback)
             _report_progress("--- End PyInstaller STDERR ---", callback=progress_callback)

        # 8. Vérifier le résultat
        if pyinstaller_process.returncode != 0:
            _report_progress(f"PyInstaller failed! (Exit Code: {pyinstaller_process.returncode})", callback=progress_callback)
            # ... (log des erreurs inchangé) ...
            return False
        else:
             _report_progress("PyInstaller completed successfully.", callback=progress_callback)

        # --- Copie Manuelle des Fichiers de Données ---
        _report_progress("Copying additional project data files manually...", callback=progress_callback)
        app_folder_path = os.path.join(dist_dir, project_name)

        if not os.path.isdir(app_folder_path):
             _report_progress(f"Error: PyInstaller output folder '{app_folder_path}' not found after build. Cannot copy data.", callback=progress_callback)
             return False

        try:
            contents_to_copy = project_manager.get_project_contents(project_name)

            if not contents_to_copy:
                _report_progress("  No additional data files/folders found to copy.", callback=progress_callback)
            else:
                for rel_path, item_type in contents_to_copy:
                    if item_type == 'info': continue

                    source_path_abs = os.path.join(project_path, rel_path)
                    destination_path_abs = os.path.join(app_folder_path, rel_path)

                    try:
                        if os.path.exists(source_path_abs):
                            if item_type == 'file':
                                os.makedirs(os.path.dirname(destination_path_abs), exist_ok=True)
                                shutil.copy2(source_path_abs, destination_path_abs)
                                _report_progress(f"  Copied file: '{rel_path}'", callback=progress_callback)
                            elif item_type == 'dir':
                                shutil.copytree(source_path_abs, destination_path_abs, dirs_exist_ok=True)
                                _report_progress(f"  Copied folder: '{rel_path}'", callback=progress_callback)
                        else:
                             _report_progress(f"  Warning: Source not found for manual copy, skipping: {source_path_abs}", callback=progress_callback)
                    except Exception as copy_err:
                         _report_progress(f"  ERROR copying item '{rel_path}': {copy_err}", callback=progress_callback)

        except Exception as list_err:
             _report_progress(f"Error listing project contents for manual copy: {list_err}", callback=progress_callback)
             traceback.print_exc()
        _report_progress("Manual data copying finished.", callback=progress_callback)
        # --- FIN Copie Manuelle ---

        # 9. Zipper le dossier de sortie
        _report_progress(f"Creating archive '{os.path.basename(output_zip_path)}'...", callback=progress_callback)
        try:
            os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
            zip_base_name = output_zip_path.removesuffix('.zip')
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

    # ... (gestion TimeoutExpired, Exception, finally inchangés) ...
    except subprocess.TimeoutExpired:
        error_msg = f"PyInstaller process timed out after 10 minutes."
        _report_progress(error_msg, callback=progress_callback)
        print(f"[Exporter] {error_msg}")
        return False
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


# --- NOUVELLE FONCTION D'EXPORT (Méthode 2) ---
def create_source_distribution(project_name: str, output_zip_path: str, progress_callback: Callable[[str], None]) -> bool:
    """
    Crée une archive ZIP contenant le code source, un requirements.txt figé,
    et des scripts de démarrage. (Méthode 2)
    """
    _report_progress(f"Starting source distribution export for project '{project_name}'...", callback=progress_callback)
    staging_dir = None
    success = False

    try:
        # 1. Obtenir les chemins
        _report_progress("Getting project paths...", callback=progress_callback)
        try:
            project_path = project_manager.get_project_path(project_name)
            if not os.path.isdir(project_path):
                 raise FileNotFoundError(f"Project directory not found: {project_path}")
            main_script_path = os.path.join(project_path, project_manager.DEFAULT_MAIN_SCRIPT)
            if not os.path.exists(main_script_path):
                raise FileNotFoundError(f"Main script '{project_manager.DEFAULT_MAIN_SCRIPT}' not found in project at '{project_path}'.")
        except Exception as e:
            _report_progress(f"Error getting project paths: {e}", callback=progress_callback)
            return False

        # 2. Créer un répertoire de staging temporaire
        staging_dir = tempfile.mkdtemp(prefix=f"pythautom_{project_name}_srcdist_")
        _report_progress(f"Using temp staging dir: {staging_dir}", callback=progress_callback)

        # 3. Générer requirements.txt
        _report_progress("Generating requirements.txt using 'uv pip freeze'...", callback=progress_callback)
        python_exe = utils.get_project_python_executable(project_path)
        if not python_exe or not os.path.exists(python_exe):
             _report_progress(f"Could not find Python executable in venv to freeze requirements (checked: {python_exe}).", callback=progress_callback)
             # On pourrait continuer sans requirements, mais c'est risqué
             return False

        freeze_result = utils.run_uv_command(
            ["pip", "freeze"],
            cwd=project_path, # Exécuter depuis le projet pourrait être mieux
            capture=True,
            progress_callback=progress_callback # Log la sortie de uv freeze
        )

        if freeze_result is None or freeze_result.returncode != 0:
            _report_progress("Error: Failed to run 'uv pip freeze'. Cannot generate requirements.txt.", callback=progress_callback)
            # On pourrait choisir de continuer sans requirements.txt mais l'intérêt est limité
            return False

        requirements_content = freeze_result.stdout
        if not requirements_content.strip():
             _report_progress("Warning: 'uv pip freeze' produced an empty requirements list. Continuing...", callback=progress_callback)
             # Créer un fichier vide pour éviter les erreurs plus tard
             requirements_content = "# No dependencies found in the environment.\n"


        req_file_path = os.path.join(staging_dir, "requirements.txt")
        try:
            with open(req_file_path, "w", encoding="utf-8") as f:
                f.write(requirements_content)
            _report_progress("requirements.txt generated successfully.", callback=progress_callback)
        except Exception as e:
             _report_progress(f"Error writing requirements.txt: {e}", callback=progress_callback)
             return False

        # 4. Copier les fichiers du projet dans le staging dir
        _report_progress("Copying project files to staging area...", callback=progress_callback)
        try:
            # Copier le script principal explicitement
            dest_main_script = os.path.join(staging_dir, project_manager.DEFAULT_MAIN_SCRIPT)
            shutil.copy2(main_script_path, dest_main_script)
            _report_progress(f"  Copied main script: '{project_manager.DEFAULT_MAIN_SCRIPT}'", callback=progress_callback)

            # Copier les autres contenus (fichiers de données, dossiers)
            contents_to_copy = project_manager.get_project_contents(project_name)
            if not contents_to_copy:
                 _report_progress("  No additional project files/folders found to copy.", callback=progress_callback)
            else:
                for rel_path, item_type in contents_to_copy:
                    if item_type == 'info': continue

                    source_path_abs = os.path.join(project_path, rel_path)
                    destination_path_abs = os.path.join(staging_dir, rel_path)

                    try:
                        if os.path.exists(source_path_abs):
                            if item_type == 'file':
                                os.makedirs(os.path.dirname(destination_path_abs), exist_ok=True)
                                shutil.copy2(source_path_abs, destination_path_abs)
                                _report_progress(f"  Copied file: '{rel_path}'", callback=progress_callback)
                            elif item_type == 'dir':
                                shutil.copytree(source_path_abs, destination_path_abs, dirs_exist_ok=True)
                                _report_progress(f"  Copied folder: '{rel_path}'", callback=progress_callback)
                        else:
                             _report_progress(f"  Warning: Source not found for copy, skipping: {source_path_abs}", callback=progress_callback)
                    except Exception as copy_err:
                         _report_progress(f"  ERROR copying item '{rel_path}': {copy_err}", callback=progress_callback)
                         # Optionnel: Rendre l'erreur fatale ? return False

        except Exception as list_err:
            _report_progress(f"Error preparing file list for copying: {list_err}", callback=progress_callback)
            traceback.print_exc()
            return False
        _report_progress("Project files copied.", callback=progress_callback)


        # 5. Copier les scripts de démarrage template dans le staging dir
        _report_progress("Copying startup scripts...", callback=progress_callback)
        try:
            # Détermine le chemin du dossier 'src' basé sur l'emplacement de ce fichier
            src_dir = os.path.dirname(os.path.abspath(__file__))
            template_dir = os.path.join(src_dir, "templates")

            win_template = os.path.join(template_dir, "run_windows_template.bat")
            linux_template = os.path.join(template_dir, "run_linux_template.sh")

            if os.path.exists(win_template):
                 shutil.copy2(win_template, os.path.join(staging_dir, "run_windows.bat"))
                 _report_progress("  Copied run_windows.bat", callback=progress_callback)
            else:
                 _report_progress("  Warning: Windows startup script template not found.", callback=progress_callback)

            if os.path.exists(linux_template):
                 shutil.copy2(linux_template, os.path.join(staging_dir, "run_linux.sh"))
                 # Rendre le script Linux exécutable
                 try:
                     os.chmod(os.path.join(staging_dir, "run_linux.sh"), 0o755)
                 except Exception as chmod_err:
                      _report_progress(f"  Warning: Could not set execute permission on run_linux.sh: {chmod_err}", callback=progress_callback)

                 _report_progress("  Copied run_linux.sh", callback=progress_callback)
            else:
                 _report_progress("  Warning: Linux startup script template not found.", callback=progress_callback)

        except Exception as script_copy_err:
             _report_progress(f"Error copying startup scripts: {script_copy_err}", callback=progress_callback)
             # Ne pas forcément échouer, mais prévenir
             traceback.print_exc()


        # 6. Créer l'archive ZIP à partir du contenu du staging_dir
        _report_progress(f"Creating source distribution archive '{os.path.basename(output_zip_path)}'...", callback=progress_callback)
        try:
            os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
            zip_base_name = output_zip_path.removesuffix('.zip')
            # Important: root_dir=staging_dir, base_dir='.' pour zipper le *contenu*
            shutil.make_archive(
                base_name=zip_base_name,
                format='zip',
                root_dir=staging_dir,
                base_dir='.' # Met tout à la racine du zip
            )
            _report_progress("Source distribution archive created successfully.", callback=progress_callback)
            success = True
        except Exception as zip_e:
            _report_progress(f"Error creating source distribution zip archive: {zip_e}", callback=progress_callback)
            traceback.print_exc()
            return False

        return success

    except Exception as e:
        error_msg = f"An unexpected error occurred during source distribution export: {e}"
        _report_progress(error_msg, callback=progress_callback)
        print(f"[Exporter] {error_msg}")
        traceback.print_exc()
        return False

    finally:
        # 7. Nettoyage du staging_dir
        try:
            if staging_dir and os.path.exists(staging_dir):
                print(f"[Exporter] Cleaning up temp staging directory: {staging_dir}")
                try: shutil.rmtree(staging_dir)
                except OSError as rm_err:
                    print(f"[Exporter] Warning: Error removing staging dir {staging_dir}: {rm_err}")
                    _report_progress(f"Warning: Error cleaning up temp staging dir: {rm_err}", callback=progress_callback)
        except Exception as cleanup_e:
             final_warning = f"Warning: Error during cleanup of temp staging dir: {cleanup_e}"
             _report_progress(final_warning, callback=progress_callback)
             print(f"[Exporter] {final_warning}")
             traceback.print_exc()
# --- FIN NOUVELLE FONCTION ---