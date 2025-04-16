# main.py
import sys
import os
from PyQt6.QtWidgets import QApplication

# Import components from the project
from src import project_manager
from src import utils
# Import the main window class
from src.gui_main_window import MainWindow
# Import the configuration manager (we'll create this logic later)
from src import config_manager # Supposons un nouveau module

def main():
    """Main function to initialize and run the application."""

    # --- Load Application Configuration ---
    # Load any saved settings before creating the UI
    # This might include API keys, last used settings, etc.
    # The config_manager module will handle the actual loading/saving logic.
    print("Loading application configuration...")
    app_config = config_manager.load_app_config()
    # We don't necessarily pass app_config to MainWindow directly.
    # The handler might access it via the config_manager later.
    print(f"Configuration loaded. API Key found: {'Yes' if config_manager.get_api_key() else 'No'}")
    # -------------------------------------

    app = QApplication(sys.argv)

    # Optional: Load stylesheets if you have one (remains unchanged)
    # try:
    #     with open("stylesheet.qss", "r") as f:
    #         app.setStyleSheet(f.read())
    # except FileNotFoundError:
    #     print("Stylesheet not found, using default style.")

    # --- Create and Show Main Window ---
    window = MainWindow() # MainWindow itself doesn't need the config directly
    window.show()
    # ----------------------------------

    # --- Start Application Event Loop ---
    exit_code = app.exec()
    # -----------------------------------

    # --- Optional: Save config on exit? ---
    # Generally better to save settings when they change, but could add here.
    # print("Saving configuration before exit...")
    # config_manager.save_app_config() # Example if needed
    # --------------------------------------

    sys.exit(exit_code)

if __name__ == "__main__":
    # --- Pre-Flight Checks ---
    # 1. Ensure the main 'projets' directory exists (remains unchanged)
    try:
        print("Ensuring projects directory exists...")
        project_manager.ensure_projects_dir()
        print(f"Projects directory location: {project_manager.get_absolute_projects_dir()}")
    except Exception as e:
         print(f"CRITICAL ERROR: Could not ensure projects directory exists: {e}")
         sys.exit(1) # Exit if the base directory cannot be created

    # 2. Check for UV dependency (remains unchanged)
    try:
        print("Checking for 'uv' command...")
        uv_check = utils.run_uv_command(["--version"], capture=True)
        if uv_check is None or uv_check.returncode != 0:
             print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
             print("!!! WARNING: 'uv' command failed or not found.             !!!")
             print("!!! Virtual environment and dependency management WILL FAIL. !!!")
             print("!!! Please install uv: https://github.com/astral-sh/uv     !!!")
             print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        else:
             # Log the version found if successful
             uv_version_output = uv_check.stdout.strip() or uv_check.stderr.strip()
             print(f"UV check successful: {uv_version_output}")
    except Exception as uv_e:
         print(f"Error checking for UV: {uv_e}")
    # --- End Pre-Flight Checks ---

    # --- Run Main Application ---
    main()
    # -------------------------