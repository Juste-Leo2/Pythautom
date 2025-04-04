# PythAutom: One-Click Python Project Builder with AI

[![Français](https://img.shields.io/badge/Langue-Français-blue.svg)](READMEFR.md)

PythAutom is a desktop application leveraging PyQt6, UV, and LM Studio to empower users in creating Python projects through interaction with a locally running AI model.

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1.  **Python:** Version **3.11 or higher** must be installed and correctly added to your system's `PATH` environment variable.
2.  **LM Studio:**
    *   Download and install LM Studio from the official website: [https://lmstudio.ai/](https://lmstudio.ai/)
    *   Launch the LM Studio application.
    *   Navigate to the model download section (search icon).
    *   Download a compatible instruction-tuned model (e.g., `Qwen/Qwen1.5-7B-Chat-GGUF` or similar).
    *   Go to the **Local Server** tab (icon looks like `<->` on the left).
    *   Select your downloaded model from the dropdown at the top.
    *   Click the **"Start Server"** button.
    *   **Important:** Keep LM Studio running with the server active while using PythAutom.

## How to Run

1.  Simply **double-click** the `run.bat` file located in the project's root directory.
2.  This batch script automates the setup process:
    *   It checks if **UV** (a fast Python package installer and resolver) is installed. If not, it downloads and installs it locally within the project structure.
    *   It uses UV to create an isolated Python virtual environment named `.venv`.
    *   It installs the required Python libraries (`PyQt6`, `lmstudio-client`) into the `.venv` environment using UV.
    *   Finally, it launches the main PythAutom application (`main.py`) using the Python interpreter from the `.venv` environment.

## Features

*   **Graphical User Interface (GUI):** Provides an intuitive interface built with PyQt6 to manage projects and interact with the AI.
*   **AI-Powered Code Generation:** Utilizes language models running locally via the LM Studio server to generate Python code based on user prompts.
*   **Automatic Dependency Management:** Leverages UV to automatically install required libraries based on AI suggestions or explicit user requests within the project's context.
*   **Isolated Project Execution:** Runs generated Python scripts within their specific, isolated virtual environments managed by UV.
*   **Basic Error Handling & Iteration:** Includes basic mechanisms to catch errors during script execution and allows iterating with the AI to debug and fix the code.

## Planned Improvements / Roadmap

*   [ ] Enhanced conversational interaction with the AI.
*   [ ] Feature to export generated projects as standalone packages or structures.
*   [ ] Integration of AI vision capabilities (e.g., interpreting diagrams or UI mockups).
*   [ ] Improved auto-correction mechanisms for generated code based on errors.

---
