# PythAutom: One-Click Python Project Builder with AI

[![Français](https://img.shields.io/badge/Langue-Français-blue.svg)](READMEFR.md)

PythAutom is a desktop application leveraging PyQt6, UV, and LM Studio to empower users in creating Python projects through interaction with an AI model running locally or across your network. Build smarter and faster — effortlessly. 🚀

### ✨ What's New in Version 3.0 ✨

*   **File Import:** 📁 You can now import files into your projects through the interface.
*   **Advanced Export:** 🧳 Export directly from the project source for handling complex structures.
*   **Interrupt AI Generation:** ✋ You can now cancel an ongoing AI generation task at any time.
*   **Developer Tools Panel:** 🛠️ Access logs and manually install additional packages via a dedicated Dev Tools window.
*   **Improved Auto-Correction:** 🔁 Enhanced logic to detect and correct code issues more effectively.

## Prerequisites

Before you begin, make sure the following are properly installed and configured:

1.  **Python:** Version **3.11.9 or higher**, and it must be added to your system `PATH`.  
    👉 Download here: [https://www.python.org/downloads/release/python-3119/](https://www.python.org/downloads/release/python-3119/)

2.  **Choose Your AI Backend** (2 supported options):

### 🧠 Option 1: LM Studio (Recommended for local/offline use)

*   Download LM Studio: [https://lmstudio.ai/](https://lmstudio.ai/)
*   Launch LM Studio and open the model browser (search icon).
*   Download an instruction-tuned model such as `Openhands LM 7B v0.1`.
*   Go to the **Local Server** tab (`<->` icon).
*   Select the model, then click **"Start Server"**.
*   *(Optional)* Bind LM Studio to `0.0.0.0` to allow remote network access.
*   Keep LM Studio running while using PythAutom.

### ☁️ Option 2: Gemini (Google Generative AI API)

*   Visit: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
*   Create an API key.
*   In PythAutom, switch to **Gemini mode** and paste your key in the provided field.

## How to Run

Depending on your operating system:

### 🪟 Windows:

1.  Double-click `run_windows.bat` at the root of the project.

### 🐧 Linux:

1.  Open a terminal and run:
    ```bash
    chmod +x run_linux.sh
    ./run_linux.sh
    ```

These scripts will:

*   Check for **UV** (and auto-install it if missing),
*   Create a `.venv` isolated Python environment,
*   Install `PyQt6`, `lmstudio-client`, **and `google-generativeai`** inside that environment,
*   Automatically launch `main.py` using the virtual environment.

## Features

*   **User-Friendly GUI:** Built with PyQt6 to manage Python projects and chat with the AI assistant.
*   **AI Code Generation:** Generates code based on prompts using LM Studio or Gemini models.
*   **Dual AI Support:** Choose between local LM Studio servers or Gemini cloud API.
*   **Smart Dependency Management:** UV installs needed packages based on the AI’s analysis.
*   **Isolated Environments:** Every project runs in its own dedicated `.venv` for safe execution.
*   **Debugging & Auto-Fix Loop:** Errors are detected, sent back to the AI, and fixed iteratively.
*   **File import/export tools** and **developer panel** for advanced users.

## Roadmap

*   [x] Improved conversational AI interactions.
*   [x] Ability to stop generation mid-process.
*   [x] Enhanced error correction with feedback loop.
*   [x] Built-in Dev Tools (logs + manual package installation).
*   [x] Gemini API support.
*   [ ] AI vision support.
