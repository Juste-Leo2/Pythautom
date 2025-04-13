# main.py
import sys
from PyQt6.QtWidgets import QApplication
# Import from the new main window file
from src.gui_main_window import MainWindow
import os
# Ensure project_manager is imported for its side effects (defining PROJECTS_DIR etc.)
from src import project_manager
from src import utils # Might be needed if main calls utils directly later

def main():
    """Main function to initialize and run the application."""
    app = QApplication(sys.argv)

    # Optional: Load stylesheets if you have one
    # try:
    #     with open("stylesheet.qss", "r") as f:
    #         app.setStyleSheet(f.read())
    # except FileNotFoundError:
    #     print("Stylesheet not found, using default style.")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    # Ensure the main 'projets' directory exists before starting GUI
    try:
        project_manager.ensure_projects_dir()
    except Exception as e:
         print(f"CRITICAL ERROR: Could not ensure projects directory exists: {e}")
         # Optionally show a simple GUI error message here before exiting
         # Needs QApplication instance, so might be complex. Printing is safer.
         sys.exit(1) # Exit if the base directory cannot be created

    # Check for UV dependency early?
    try:
        uv_check = utils.run_uv_command(["--version"], capture=True)
        if uv_check is None or uv_check.returncode != 0:
             print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
             print("!!! WARNING: 'uv' command failed or not found.             !!!")
             print("!!! Virtual environment and dependency management WILL FAIL. !!!")
             print("!!! Please install uv: https://github.com/astral-sh/uv     !!!")
             print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
             # Optionally show a warning dialog? For now, just print.
    except Exception as uv_e:
         print(f"Error checking for UV: {uv_e}")


    main()