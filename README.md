# One-Click Python Project Builder with AI

This application uses PyQt6, UV, and LM Studio to help users create Python projects by interacting with an AI.

## Prerequisites

1.  **Python:** Python 3.11 or higher installed and added to your system's PATH.
2.  **LM Studio:**
    *   Download and install LM Studio from [https://lmstudio.ai/](https://lmstudio.ai/).
    *   Launch LM Studio.
    *   Download a compatible instruction-tuned model (e.g., `llama-3.2-1b-instruct`, `qwen2.5-7b-instruct`).
    *   Go to the "Server" tab (bottom left, looks like `<->`).
    *   Select the downloaded model and click "Start Server". Keep LM Studio running.

## How to Run

1.  Double-click `run.bat`.
2.  This will:
    *   Check for and install UV (a fast Python package manager) if needed.
    *   Create a virtual environment named `.venv` using UV.
    *   Install required Python libraries (`PyQt6`, `lmstudio`) into `.venv`.
    *   Launch the main application (`main.py`) using the virtual environment.

## Features

*   Graphical interface to manage projects and interact with the AI.
*   AI-powered code generation using models running locally via LM Studio.
*   Automatic dependency management using UV based on AI suggestions or user requests.
*   Execution of generated Python scripts within isolated project environments.
*   Basic error handling and iteration with the AI to fix code.

## Project Structure

*   `main.py`: Entry point of the application.
*   `run.bat`: Script to set up the environment and launch the app.
*   `src/`: Contains the core application logic.
    *   `gui.py`: PyQt6 user interface components.
    *   `llm_interaction.py`: Handles communication with the LM Studio SDK.
    *   `project_manager.py`: Manages project creation, loading, and structure.
    *   `utils.py`: Helper functions, including UV command execution.
*   `projet/`: Default directory where user projects are stored. Each project gets its own subfolder with a virtual environment and scripts.