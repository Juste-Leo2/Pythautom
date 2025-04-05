#main.py
import sys
from PyQt6.QtWidgets import QApplication
from src.gui import MainWindow # Use relative import from src

def main():
    """Main function to initialize and run the application."""
    app = QApplication(sys.argv)

    # You could load stylesheets here if desired
    # app.setStyleSheet(...)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    # Ensure the 'src' directory can be imported (if running main.py directly)
    # This might not be strictly necessary if run via run.bat setting PYTHONPATH,
    # but good practice for direct execution.
    import os
    # Add project root to sys.path if main.py is executed directly
    if os.path.basename(os.getcwd()) != 'your-app-folder' and os.path.exists('src'):
         # If running from root, Python should find src. If running from src, imports work.
         pass # Usually handled by Python's module search path

    # Create required directories if they don't exist
    from src import project_manager
    project_manager.ensure_projects_dir()

    main()