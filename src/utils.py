# src/utils.py
import subprocess
import sys
import os
import platform
import traceback # Keep for detailed error reporting

# --- UV Command Execution ---

def get_uv_executable_path():
    """Finds the path to the UV executable."""
    return "uv"

# run_uv_command is CORRECT as it is: it expects arguments ONLY and prepends uv_exe
def run_uv_command(args, cwd=None, capture=True):
    """Runs a UV command using subprocess, logging CWD and using absolute paths.
       Expects 'args' to be a list of arguments *for* uv, not including 'uv' itself."""
    uv_exe = get_uv_executable_path()
    command = [uv_exe] + args # Prepend the executable name to the arguments

    abs_cwd = os.path.abspath(cwd) if cwd else os.path.abspath(os.getcwd())
    cwd_repr = repr(abs_cwd)
    command_str_repr = ' '.join(map(repr, command))

    print(f"Running UV command: {command_str_repr}")
    print(f"           with CWD: {cwd_repr}")
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
        if result.returncode != 0:
            print(f"UV Command Error (Code {result.returncode}) in {abs_cwd}:")
            if capture:
                stdout_log = result.stdout.strip()
                stderr_log = result.stderr.strip()
                if stdout_log: print("STDOUT:", stdout_log)
                if stderr_log: print("STDERR:", stderr_log)
        # else: Optionally log success output if needed

        return result
    except FileNotFoundError:
        print(f"Error: '{uv_exe}' command not found. Is UV installed and in PATH?")
        return None
    except Exception as e:
        print(f"Error running UV command {command_str_repr} in CWD {cwd_repr}: {e}")
        traceback.print_exc()
        return None

# --- Project Environment Helpers ---

def get_project_venv_path(project_base_path):
    """Returns the standard ABSOLUTE path for a project's virtual environment."""
    abs_project_base_path = os.path.abspath(project_base_path)
    return os.path.join(abs_project_base_path, ".venv")

def get_project_python_executable(project_base_path):
    """Gets the ABSOLUTE path to the Python executable within the project's venv."""
    venv_path = get_project_venv_path(project_base_path)
    if platform.system() == "Windows":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")
    if not os.path.exists(python_exe):
        print(f"Warning: Python executable not found at expected path: {python_exe}")
    return python_exe

def ensure_project_venv(project_path):
    """Creates a UV virtual environment for the project if it doesn't exist using absolute paths."""
    abs_project_path = os.path.abspath(project_path)
    venv_path = get_project_venv_path(abs_project_path)
    indicator_file = os.path.join(venv_path, "pyvenv.cfg")

    print(f"Ensuring venv for project at absolute path: {abs_project_path}")
    print(f"Checking for venv indicator file: {indicator_file}")

    if not os.path.exists(indicator_file):
        print(f"Indicator not found. Creating virtual environment...")
        try:
            os.makedirs(abs_project_path, exist_ok=True)
            print(f"Directory ensured: {abs_project_path}")
        except OSError as e:
            print(f"ERROR: Could not create project directory {abs_project_path}: {e}")
            return False

        print(f"Target venv path for UV command (absolute): {venv_path}")

        # --- CORRECTION HERE: Pass only arguments to run_uv_command ---
        # Arguments for the 'uv venv' command
        venv_args = ["venv", venv_path, "--seed"]
        result = run_uv_command(venv_args, cwd=abs_project_path) # Pass only args
        # ------------------------------------------------------------

        if not os.path.exists(indicator_file):
             print(f"ERROR: UV command ran (exit code {result.returncode if result else 'N/A'}) but indicator file '{indicator_file}' still not found.")
             if result and result.stderr: print(f"UV stderr might have clues:\n{result.stderr.strip()}")
             return False
        if not result or result.returncode != 0:
             print(f"ERROR: Failed to create virtual environment at {venv_path} (UV command failed).")
             return False

        print(f"Virtual environment indicator file found after creation at {indicator_file}.")
        return True
    else:
        return True # Already exists

def install_project_dependencies(project_path, dependencies):
    """Installs dependencies into the project's venv using UV, absolute paths, and relying on CWD."""
    abs_project_path = os.path.abspath(project_path)
    if not dependencies: return True # Nothing to do

    print(f"Attempting to ensure venv exists for project (absolute): {abs_project_path}")
    if not ensure_project_venv(abs_project_path):
         print(f"ERROR: Failed to ensure project venv exists. Cannot install dependencies.")
         return False

    if isinstance(dependencies, str): dependencies = dependencies.split()
    if not isinstance(dependencies, list) or not all(isinstance(dep, str) for dep in dependencies): return False
    dependencies = [dep for dep in dependencies if dep]
    if not dependencies: return True # Empty list after filtering

    print(f"Installing dependencies in '{abs_project_path}' using 'uv pip install': {dependencies}")

    # --- CORRECTION HERE: Pass only arguments to run_uv_command ---
    # Arguments for the 'uv pip install' command
    install_args = ["pip", "install"] + dependencies
    result = run_uv_command(install_args, cwd=abs_project_path) # Pass only args
    # ------------------------------------------------------------

    if result and result.returncode == 0:
        print(f"Successfully installed {', '.join(dependencies)} in {abs_project_path}")
        return True
    else:
        print(f"ERROR: Failed to install dependencies {dependencies} in {abs_project_path}")
        return False

def run_project_script(project_path, script_name="main.py"):
    """Runs a Python script within the project's UV environment using 'uv run' and absolute paths."""
    abs_project_path = os.path.abspath(project_path)
    venv_path = get_project_venv_path(abs_project_path)
    pyvenv_cfg_path = os.path.join(venv_path, "pyvenv.cfg")

    print(f"Running script for project (absolute path): {abs_project_path}")
    print(f"Checking for venv indicator file: {pyvenv_cfg_path}")

    if not os.path.exists(pyvenv_cfg_path):
        print(f"Venv indicator not found. Attempting ensure_project_venv...")
        if not ensure_project_venv(abs_project_path):
            print(f"ERROR: Failed to ensure venv exists. Cannot run script.")
            return subprocess.CompletedProcess(args=[], returncode=-1, stdout="", stderr=f"Failed to ensure virtual environment exists at {venv_path}")
        else: print(f"Venv ensured/created. Proceeding...")

    script_path = os.path.join(abs_project_path, script_name)
    if not os.path.exists(script_path):
        print(f"Error: Script file not found at {script_path}")
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=f"Script not found: {script_path}")

    print(f"Running script '{script_path}' using 'uv run -- python {script_name}'...")
    try:
        # --- CORRECTION HERE: Pass only arguments to run_uv_command ---
        # Arguments for the 'uv run' command
        run_args = ["run", "--", "python", script_name]
        result = run_uv_command(run_args, cwd=abs_project_path) # Pass only args
        # ----------------------------------------------------------

        print("-" * 20 + f" Script Output ({script_name}) " + "-" * 20)
        if result:
            output_log = f"Exit Code: {result.returncode}\n"
            stdout_clean = result.stdout.strip() if result.stdout else ""
            stderr_clean = result.stderr.strip() if result.stderr else ""
            if stdout_clean: output_log += "STDOUT:\n" + stdout_clean + "\n"
            else: output_log += "STDOUT: [No output]\n"
            if stderr_clean: output_log += "STDERR:\n" + stderr_clean + "\n"
            else: output_log += "STDERR: [No output]\n"
            print(output_log.strip())
        else:
             print("ERROR: run_uv_command failed to return a result.")
             # Construct arguments list manually for CompletedProcess if command list not available
             constructed_args_for_error = [get_uv_executable_path()] + run_args # Best guess
             return subprocess.CompletedProcess(args=constructed_args_for_error, returncode=-1, stdout="", stderr="Failed to execute uv command.")

        print("-" * (42 + len(script_name)))
        return result

    except FileNotFoundError: # This shouldn't happen if run_uv_command handles it, but keep as safety
        print(f"Error: '{get_uv_executable_path()}' command not found. Is UV installed and in PATH?")
        return subprocess.CompletedProcess(args=[get_uv_executable_path()], returncode=127, stdout="", stderr="uv command not found")
    except Exception as e:
        print(f"Error running script {script_path} via 'uv run': {e}")
        traceback.print_exc()
        constructed_args_for_error = [get_uv_executable_path()] + run_args # Best guess
        return subprocess.CompletedProcess(args=constructed_args_for_error, returncode=1, stdout="", stderr=f"Exception during script execution: {e}")