# src/utils.py
# No changes needed from the previous version for streaming/LM Studio fix.
# Progress callback already implemented correctly.
import subprocess
import sys
import os
import platform
import traceback
import datetime # For timestamp
# import re # Not needed here, used in project_manager
from typing import List, Optional, Callable, Union

from . import project_manager # Use relative import within the package

# Default dummy callback
def _dummy_progress_callback(message: str):
     # print(f"[Dummy Callback] {message}")
     pass

def get_timestamp():
    """Returns a simple ISO-like timestamp string."""
    # Changed to ISO format for better compatibility
    return datetime.datetime.now().isoformat()

# --- UV Command Execution ---

def get_uv_executable_path():
    """Finds the path to the UV executable. Assumes 'uv' is in PATH."""
    return "uv"

def run_uv_command(args: List[str], cwd: Optional[str] = None, capture: bool = True, progress_callback: Optional[Callable[[str], None]] = None) -> Optional[subprocess.CompletedProcess]:
    """
    Runs a UV command using subprocess, handling paths and optional progress logging.

    Args:
        args: List of arguments FOR uv (e.g., ["pip", "install", "requests"]).
        cwd: Working directory for the command (absolute path preferred).
        capture: Whether to capture stdout/stderr (True) or let them print directly (False).
        progress_callback: Optional function to send command output lines to.

    Returns:
        subprocess.CompletedProcess object or None on critical error (e.g., uv not found).
    """
    uv_exe = get_uv_executable_path()
    command = [uv_exe] + args
    abs_cwd = os.path.abspath(cwd) if cwd else os.path.abspath(os.getcwd())

    if not os.path.isdir(abs_cwd):
        err_msg = f"ERROR: Invalid CWD provided to run_uv_command: {abs_cwd}"
        print(err_msg)
        if progress_callback: progress_callback(err_msg)
        return subprocess.CompletedProcess(args=command, returncode=-1, stdout="", stderr=f"Invalid CWD: {abs_cwd}")

    log_progress = progress_callback or _dummy_progress_callback
    command_str_repr = ' '.join(map(repr, command))
    log_progress(f"Running UV: {command_str_repr}")
    log_progress(f"  in CWD: {repr(abs_cwd)}")

    try:
        result = subprocess.run(
            command,
            cwd=abs_cwd,
            capture_output=capture,
            text=True,
            check=False,
            encoding='utf-8',
            errors='replace'
        )

        if capture and progress_callback:
            # Log stdout/stderr line by line for better readability in GUI console
            if result.stdout:
                log_progress("--- UV STDOUT ---")
                for line in result.stdout.splitlines(): log_progress(line)
                log_progress("--- End UV STDOUT ---")
            if result.stderr:
                log_progress("--- UV STDERR ---")
                for line in result.stderr.splitlines(): log_progress(line)
                log_progress("--- End UV STDERR ---")

        if result.returncode != 0:
            log_progress(f"UV Command failed with exit code {result.returncode}")

        return result

    except FileNotFoundError:
        error_msg = f"ERROR: '{uv_exe}' command not found. Is UV installed and in PATH?"
        print(error_msg)
        log_progress(error_msg)
        return None # Critical failure
    except Exception as e:
        error_msg = f"ERROR running UV command {command_str_repr} in CWD {repr(abs_cwd)}: {e}"
        print(error_msg)
        traceback.print_exc()
        log_progress(error_msg)
        log_progress(traceback.format_exc())
        return subprocess.CompletedProcess(args=command, returncode=-1, stdout="", stderr=str(e))


# --- Project Environment Helpers ---

def get_project_venv_path(project_base_path: str) -> str:
    """Returns the standard ABSOLUTE path for a project's virtual environment."""
    abs_project_base_path = os.path.abspath(project_base_path)
    return os.path.join(abs_project_base_path, ".venv")

def get_project_python_executable(project_base_path: str) -> Optional[str]:
    """Gets the ABSOLUTE path to the Python executable within the project's venv."""
    venv_path = get_project_venv_path(project_base_path) # Gets absolute path
    if platform.system() == "Windows":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")
    return python_exe # Return path even if it doesn't exist yet

def ensure_project_venv(project_path: str, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    Creates a UV virtual environment for the project if it doesn't exist.

    Args:
        project_path: Absolute path to the project directory.
        progress_callback: Optional function to send status updates to.

    Returns:
        True if venv exists or was created successfully, False otherwise.
    """
    abs_project_path = os.path.abspath(project_path)
    venv_path = get_project_venv_path(abs_project_path)
    indicator_file = os.path.join(venv_path, "pyvenv.cfg")

    log_progress = progress_callback or _dummy_progress_callback
    log_progress(f"Ensuring venv for project: {abs_project_path}")
    log_progress(f"Checking for indicator file: {indicator_file}")

    if not os.path.exists(indicator_file):
        log_progress(f"Venv indicator not found. Attempting to create venv at: {venv_path}")
        try:
            if not os.path.isdir(abs_project_path):
                 log_progress(f"Creating project directory: {abs_project_path}")
                 os.makedirs(abs_project_path, exist_ok=True)
        except OSError as e:
            log_progress(f"ERROR: Could not create project directory {abs_project_path}: {e}")
            return False

        venv_args = ["venv", venv_path, "--seed"]
        result = run_uv_command(venv_args, cwd=abs_project_path, progress_callback=log_progress)

        if not os.path.exists(indicator_file):
             log_progress(f"ERROR: UV command ran (exit code {result.returncode if result else 'N/A'}) but indicator file '{indicator_file}' still not found.")
             return False
        if result is None or result.returncode != 0:
             log_progress(f"ERROR: Failed to create virtual environment at {venv_path} (UV command failed).")
             return False

        log_progress(f"Virtual environment created successfully at {venv_path}.")
        return True
    else:
        log_progress("Virtual environment already exists.")
        return True # Already exists

def install_project_dependencies(project_path: str, dependencies: Union[str, List[str]], progress_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    Installs dependencies into the project's venv using UV.

    Args:
        project_path: Absolute path to the project directory.
        dependencies: A list of dependency strings or a single space-separated string.
        progress_callback: Optional function to send status updates/logs to.

    Returns:
        True if installation was successful or no dependencies needed, False otherwise.
    """
    abs_project_path = os.path.abspath(project_path)
    log_progress = progress_callback or _dummy_progress_callback

    if isinstance(dependencies, str): deps_list = dependencies.split()
    elif isinstance(dependencies, list): deps_list = dependencies
    else:
        log_progress(f"ERROR: Invalid dependencies format: {type(dependencies)}")
        return False

    deps_list = [dep.strip() for dep in deps_list if dep.strip()]
    if not deps_list:
        log_progress("No dependencies provided to install.")
        return True

    log_progress(f"Ensuring venv exists before installing dependencies in {abs_project_path}...")
    if not ensure_project_venv(abs_project_path, progress_callback=log_progress):
         log_progress(f"ERROR: Failed to ensure project venv exists. Cannot install dependencies.")
         return False

    log_progress(f"Installing dependencies via 'uv pip install': {deps_list}")
    install_args = ["pip", "install"] + deps_list
    result = run_uv_command(install_args, cwd=abs_project_path, progress_callback=log_progress)

    if result and result.returncode == 0:
        log_progress(f"Successfully installed: {', '.join(deps_list)}")
        # Update metadata after successful install
        try:
             meta = project_manager.load_project_metadata(os.path.basename(abs_project_path))
             current_deps = set(meta.get("dependencies", []))
             current_deps.update(deps_list)
             meta["dependencies"] = sorted(list(current_deps))
             project_manager.save_project_metadata(os.path.basename(abs_project_path), meta)
        except Exception as meta_e:
             log_progress(f"Warning: Failed to update project metadata after install: {meta_e}")
        return True
    else:
        log_progress(f"ERROR: Failed to install dependencies: {deps_list}")
        return False

def run_project_script(project_path: str, script_name: str = "main.py", progress_callback: Optional[Callable[[str], None]] = None) -> Optional[subprocess.CompletedProcess]:
    """
    Runs a Python script within the project's UV environment using 'uv run'.

    Args:
        project_path: Absolute path to the project directory.
        script_name: Name of the script file relative to project_path.
        progress_callback: Optional function to send execution output/status to.

    Returns:
        subprocess.CompletedProcess object containing execution results, or None if
        uv command itself failed critically (e.g., not found).
    """
    abs_project_path = os.path.abspath(project_path)
    log_progress = progress_callback or _dummy_progress_callback

    log_progress(f"Preparing to run script: {abs_project_path}/{script_name}")

    log_progress("Checking virtual environment...")
    if not ensure_project_venv(abs_project_path, progress_callback=log_progress):
        log_progress(f"ERROR: Failed to ensure venv exists. Cannot run script.")
        return subprocess.CompletedProcess(args=[], returncode=-1, stdout="", stderr="Failed to ensure virtual environment.")

    script_path_abs = os.path.join(abs_project_path, script_name)
    if not os.path.exists(script_path_abs):
        error_msg = f"Error: Script file not found at {script_path_abs}"
        log_progress(error_msg)
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=error_msg)

    log_progress(f"Executing script '{script_name}' using 'uv run -- python {script_name}'...")
    try:
        run_args = ["run", "--", "python", script_name]
        # Use capture=True so progress_callback can log stdout/stderr from result
        result = run_uv_command(run_args, cwd=abs_project_path, capture=True, progress_callback=log_progress)

        if result:
             log_progress(f"--- Script execution finished (Exit Code: {result.returncode}) ---")
        else:
             log_progress(f"--- Script execution failed (Could not run UV command) ---")
             constructed_args_for_error = [get_uv_executable_path()] + run_args
             return subprocess.CompletedProcess(args=constructed_args_for_error, returncode=-127, stdout="", stderr="Failed to execute uv command.")

        return result

    except Exception as e:
        error_msg = f"Error setting up or interpreting 'uv run' for script {script_path_abs}: {e}"
        print(error_msg)
        traceback.print_exc()
        log_progress(error_msg)
        log_progress(traceback.format_exc())
        constructed_args_for_error = [get_uv_executable_path()] + run_args
        return subprocess.CompletedProcess(args=constructed_args_for_error, returncode=-1, stdout="", stderr=f"Exception during script execution setup: {e}")