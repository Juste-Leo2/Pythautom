# PythAutom: One-Click Python Project Builder with AI

[![Français](https://img.shields.io/badge/Langue-Français-blue.svg)](READMEFR.md)

PythAutom is a desktop application leveraging PyQt6, UV, and LM Studio to empower users in creating Python projects through interaction with an AI model running locally or across your network. Build smarter and faster — effortlessly. 🚀

### ✨ New Features Added! ✨

*   **Project Export:** 🗂️ You can now export your generated Python projects as standalone packages or folder structures.
*   **External AI Integration:** 🤖 Use AI models beyond your local LM Studio server — PythAutom now supports external model connections.
*   **Support for Reasoning Models (LM Studio):** 🧠 PythAutom is now fully compatible with reasoning-capable models from LM Studio.
*   **Linux Compatibility:** 🐧 PythAutom now runs smoothly on Linux systems!

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
    *   **Network Setup (Optional):** If you want PythAutom to connect across the network, make sure LM Studio is set to allow connections from other devices (check the server settings in LM Studio, you might need to bind to `0.0.0.0` instead of `localhost`).
    *   **Important:** Keep LM Studio running with the server active while using PythAutom.

## How to Run

Depending on your operating system:

### 🪟 Windows:

1.  Double-click the `run_windows.bat` file located in the project's root directory.

### 🐧 Linux:

1.  Open a terminal and run:
    ```bash
    chmod +x run_linux.sh
    ./run_linux.sh
    ```

Both scripts will:

*   Check if **UV** (a *lightning-fast* Python package installer and resolver - Huge thanks to the Astral team!) is installed. If not, it will be installed locally in the project.
*   Use UV to create an isolated Python virtual environment named `.venv`.
*   Install required Python libraries (`PyQt6`, `lmstudio-client`) inside that environment.
*   Launch the main application (`main.py`) using the Python interpreter from `.venv`.

## Features

*   **Graphical User Interface (GUI):** Provides an intuitive interface built with PyQt6 to manage projects and interact with the AI.
*   **AI-Powered Code Generation:** Utilizes language models running locally (or on your network!) via the LM Studio server to generate Python code based on user prompts.
*   **Automatic Dependency Management:** Leverages UV to automatically install required libraries based on AI suggestions or explicit user requests within the project's context.
*   **Isolated Project Execution:** Runs generated Python scripts within their specific, isolated virtual environments managed by UV.
*   **Basic Error Handling & Iteration:** Includes basic mechanisms to catch errors during script execution and allows iterating with the AI to debug and fix the code.

## Planned Improvements / Roadmap

*   [x] Enhanced conversational interaction with the AI.
*   [x] Feature to export generated projects as standalone packages or structures.
*   [x] Improved auto-correction mechanisms for generated code based on errors.
*   [ ] Integration of AI vision capabilities (e.g., interpreting diagrams or UI mockups).
*   [ ] Ability to import files (images, audio, or video) for future multimodal features.
