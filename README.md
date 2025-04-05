# PythAutom: One-Click Python Project Builder with AI

[![Français](https://img.shields.io/badge/Langue-Français-blue.svg)](READMEFR.md)

PythAutom is a desktop application leveraging PyQt6, UV, and LM Studio to empower users in creating Python projects through interaction with an AI model running locally **OR ACROSS YOUR NETWORK!** Get ready to build efficiently.

### ✨ Network Capabilities Unlocked! ✨

*   **Connect Anywhere:** PythAutom seamlessly links up with your LM Studio server. While it defaults to your local machine (`localhost:1234`), it's ready for **network action!** 🔥
*   **Remote AI Power:** Running LM Studio on a dedicated server or another PC on your network? PythAutom can tap into that power! Just ensure your LM Studio server is configured to be accessible over the network (check LM Studio's server options!). 🔥
*   **Flexibility:** Build from your main workstation while leveraging AI power from elsewhere on your LAN! Maximum flexibility! 🎉

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

1.  Simply **double-click** the `run.bat` file located in the project's root directory.
2.  This batch script automates the setup process:
    *   It checks if **UV** (a *lightning-fast* Python package installer and resolver - Huge thanks to the Astral team for this incredible tool!) is installed. If not, it downloads and installs it locally within the project structure.
    *   It uses UV to create an isolated Python virtual environment named `.venv`.
    *   It installs the required Python libraries (`PyQt6`, `lmstudio-client`) into the `.venv` environment using UV.
    *   Finally, it launches the main PythAutom application (`main.py`) using the Python interpreter from the `.venv` environment.

## Features

*   **Graphical User Interface (GUI):** Provides an intuitive interface built with PyQt6 to manage projects and interact with the AI.
*   **AI-Powered Code Generation:** Utilizes language models running locally (or on your network!) via the LM Studio server to generate Python code based on user prompts.
*   **Automatic Dependency Management:** Leverages UV to automatically install required libraries based on AI suggestions or explicit user requests within the project's context.
*   **Isolated Project Execution:** Runs generated Python scripts within their specific, isolated virtual environments managed by UV.
*   **Basic Error Handling & Iteration:** Includes basic mechanisms to catch errors during script execution and allows iterating with the AI to debug and fix the code.

## Planned Improvements / Roadmap

*   [ ] Enhanced conversational interaction with the AI.
*   [ ] Feature to export generated projects as standalone packages or structures.
*   [ ] Integration of AI vision capabilities (e.g., interpreting diagrams or UI mockups).
*   [ ] Improved auto-correction mechanisms for generated code based on errors.

---
