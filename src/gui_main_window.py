# src/gui_main_window.py

import sys
import platform
import os
from typing import Optional, List, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLineEdit, QLabel, QSplitter, QMessageBox,
    QDialog, QDialogButtonBox, QApplication, QListWidgetItem, QFormLayout,
    QFileDialog, QComboBox, QGroupBox, QCheckBox, QSpinBox, QSizePolicy,
    QSpacerItem, QGridLayout # Utilisation retirée pour les boutons projet, mais gardé pour LLM status
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QFont, QIntValidator, QSyntaxHighlighter, QColor,
    QTextCharFormat, QIcon
)

# Import des composants nécessaires depuis les autres modules
from . import project_manager
from . import config_manager # Gère la config persistante

# Imports depuis llm_interaction.py (pour les configurations par défaut et disponibilités)
from .llm_interaction import (
    DEFAULT_LM_STUDIO_IP, DEFAULT_LM_STUDIO_PORT, DEFAULT_GEMINI_MODEL,
    AVAILABLE_GEMINI_MODELS, GOOGLE_GENAI_AVAILABLE
)
# Imports depuis gui_actions_handler.py (pour les constantes de backend et autres)
from .gui_actions_handler import (
    GuiActionsHandler, DEFAULT_MAX_CORRECTION_ATTEMPTS,
    LLM_BACKEND_LMSTUDIO, LLM_BACKEND_GEMINI,
    TASK_GENERATE_CODE_STREAM # <<< Importé pour savoir quand afficher Annuler
)
from .project_manager import DEFAULT_MAIN_SCRIPT


# --- Syntax Highlighting (Inchangé) ---
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []
        # Règles de coloration
        keywordFormat = QTextCharFormat(); keywordFormat.setForeground(QColor("lightblue")); keywordFormat.setFontWeight(QFont.Weight.Bold)
        keywords = ["def", "class", "import", "from", "return", "if", "else", "elif", "for", "while", "try", "except", "finally", "with", "as", "in", "True", "False", "None", "self", "lambda", "yield", "pass", "continue", "break", "is", "not", "and", "or", "del", "global", "nonlocal", "assert"]
        self.highlightingRules.extend([(r'\b' + k + r'\b', keywordFormat) for k in keywords])
        stringFormat = QTextCharFormat(); stringFormat.setForeground(QColor("lightgreen"))
        self.highlightingRules.append((r'"[^"\\]*(\\.[^"\\]*)*"', stringFormat)); self.highlightingRules.append((r"'[^'\\]*(\\.[^'\\]*)*'", stringFormat))
        commentFormat = QTextCharFormat(); commentFormat.setForeground(QColor("gray")); self.highlightingRules.append((r'#.*', commentFormat))
        numberFormat = QTextCharFormat(); numberFormat.setForeground(QColor("orange")); self.highlightingRules.append((r'\b[0-9]+\b', numberFormat)); self.highlightingRules.append((r'\b0x[0-9A-Fa-f]+\b', numberFormat))
        functionFormat = QTextCharFormat(); functionFormat.setForeground(QColor("yellow")); self.highlightingRules.append((r'\b[A-Za-z_][A-Za-z0-9_]*(?=\()', functionFormat))
        decoratorFormat = QTextCharFormat(); decoratorFormat.setForeground(QColor("magenta")); self.highlightingRules.append((r'@[A-Za-z_][A-Za-z0-9_.]*', decoratorFormat))

    def highlightBlock(self, text):
        if len(text) > 2000: return # Optimisation
        for pattern, format_rule in self.highlightingRules:
            try:
                import re
                for match in re.finditer(pattern, text):
                    start, end = match.span()
                    self.setFormat(start, end - start, format_rule)
            except Exception: pass # Ignore regex errors
        self.setCurrentBlockState(0)


# --- Fenêtre Principale ---
class MainWindow(QMainWindow):
    # --- Déclarations UI ---
    llm_backend_selector: QComboBox
    lmstudio_group: QGroupBox; llm_ip_input: QLineEdit; llm_port_input: QLineEdit
    gemini_group: QGroupBox; gemini_api_key_input: QLineEdit; gemini_model_selector: QComboBox
    project_list_widget: QListWidget

    # Nouveaux Groupes pour les boutons projet
    project_actions_group: QGroupBox
    export_group: QGroupBox
    manage_files_group: QGroupBox

    # Boutons individuels
    new_project_button: QPushButton; delete_project_button: QPushButton
    export_button: QPushButton; export_source_button: QPushButton
    add_file_button: QPushButton; add_folder_button: QPushButton

    llm_status_label: QLabel; llm_reconnect_button: QPushButton
    code_editor_text: QTextEdit; save_code_button: QPushButton; run_script_button: QPushButton
    auto_correct_checkbox: QCheckBox; max_attempts_spinbox: QSpinBox
    execution_log_text: QTextEdit; status_log_text: QTextEdit
    chat_display_text: QTextEdit; chat_input_text: QLineEdit; chat_send_button: QPushButton
    cancel_llm_button: QPushButton # <<< NOUVEAU BOUTON ANNULER

    install_deps_input: QLineEdit; install_deps_button: QPushButton
    save_logs_button: QPushButton
    execution_log_area_widget: QWidget; status_log_area_widget: QWidget
    deps_group: QGroupBox
    dev_mode_button: QPushButton

    code_highlighter: PythonHighlighter
    handler: GuiActionsHandler

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pythautom - AI Python Project Builder")
        self.setGeometry(100, 100, 1450, 850) # Augmenté légèrement la largeur par défaut
        self.handler = GuiActionsHandler(self)

        self.setup_ui()
        self.load_initial_settings()

        # Cache les outils dev au démarrage
        self.set_dev_elements_visibility(False)
        self.dev_mode_button.setChecked(False)

        # Charge la liste des projets et tente la connexion après un court délai
        QTimer.singleShot(0, self.handler.load_project_list)
        self.update_llm_ui_for_backend()
        QTimer.singleShot(100, self.handler.attempt_llm_connection)


    def setup_ui(self):
        """Sets up the main window widgets and layouts."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # ======================================================================
        # --- Left Panel ---
        # ======================================================================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMinimumWidth(300)
        left_panel.setMaximumWidth(400) # Un peu plus de largeur possible

        # --- Projects Section ---
        project_label = QLabel("Projects:")
        left_layout.addWidget(project_label)
        self.project_list_widget = QListWidget()
        self.project_list_widget.currentItemChanged.connect(self.handler.load_selected_project)
        left_layout.addWidget(self.project_list_widget)

        # --- Project Actions Group ---
        self.project_actions_group = QGroupBox("Project Actions")
        project_actions_layout = QHBoxLayout(self.project_actions_group)
        self.new_project_button = QPushButton("New")
        self.new_project_button.clicked.connect(self.handler.create_new_project_dialog)
        project_actions_layout.addWidget(self.new_project_button)
        self.delete_project_button = QPushButton("Delete"); self.delete_project_button.setEnabled(False)
        self.delete_project_button.clicked.connect(self.handler.confirm_delete_project)
        project_actions_layout.addWidget(self.delete_project_button)
        left_layout.addWidget(self.project_actions_group) # Ajout du groupe au layout principal

        # --- Manage Files Group ---
        self.manage_files_group = QGroupBox("Manage Files")
        manage_files_layout = QHBoxLayout(self.manage_files_group)
        self.add_file_button = QPushButton("Add File"); self.add_file_button.setEnabled(False)
        self.add_file_button.clicked.connect(self.handler.add_file_to_project)
        manage_files_layout.addWidget(self.add_file_button)
        self.add_folder_button = QPushButton("Add Folder"); self.add_folder_button.setEnabled(False)
        self.add_folder_button.clicked.connect(self.handler.add_folder_to_project)
        manage_files_layout.addWidget(self.add_folder_button)
        left_layout.addWidget(self.manage_files_group) # Ajout du groupe

        # --- Export Group ---
        self.export_group = QGroupBox("Export")
        export_layout = QHBoxLayout(self.export_group)
        self.export_button = QPushButton("Export Executable"); self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.handler.prompt_export_project)
        export_layout.addWidget(self.export_button)
        self.export_source_button = QPushButton("Export Source"); self.export_source_button.setEnabled(False)
        self.export_source_button.clicked.connect(self.handler.prompt_export_source_distribution)
        export_layout.addWidget(self.export_source_button)
        left_layout.addWidget(self.export_group) # Ajout du groupe


        # --- LLM Configuration Section (structure inchangée) ---
        llm_config_label = QLabel("LLM Configuration:"); llm_config_label.setStyleSheet("font-weight: bold; margin-top: 15px;")
        left_layout.addWidget(llm_config_label)
        backend_layout = QHBoxLayout(); backend_layout.addWidget(QLabel("Backend:"))
        self.llm_backend_selector = QComboBox(); self.llm_backend_selector.addItems([LLM_BACKEND_LMSTUDIO, LLM_BACKEND_GEMINI])
        if not GOOGLE_GENAI_AVAILABLE: self.llm_backend_selector.model().item(1).setEnabled(False); self.llm_backend_selector.setToolTip("Install 'google-generai'")
        self.llm_backend_selector.currentTextChanged.connect(self.handler.on_llm_backend_changed)
        backend_layout.addWidget(self.llm_backend_selector); left_layout.addLayout(backend_layout)
        # LM Studio Group
        self.lmstudio_group = QGroupBox("LM Studio Settings")
        lmstudio_layout = QFormLayout(self.lmstudio_group); self.llm_ip_input = QLineEdit()
        self.llm_ip_input.editingFinished.connect(self.handler.on_llm_config_changed)
        lmstudio_layout.addRow("Server IP:", self.llm_ip_input); self.llm_port_input = QLineEdit(); self.llm_port_input.setValidator(QIntValidator(1, 65535))
        self.llm_port_input.editingFinished.connect(self.handler.on_llm_config_changed)
        lmstudio_layout.addRow("Port:", self.llm_port_input); left_layout.addWidget(self.lmstudio_group)
        # Gemini Group
        self.gemini_group = QGroupBox("Google Gemini Settings")
        gemini_layout = QFormLayout(self.gemini_group); self.gemini_api_key_input = QLineEdit(); self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.editingFinished.connect(self.handler.on_llm_config_changed)
        gemini_layout.addRow("API Key:", self.gemini_api_key_input); self.gemini_model_selector = QComboBox(); self.gemini_model_selector.addItems(AVAILABLE_GEMINI_MODELS)
        self.gemini_model_selector.currentTextChanged.connect(self.handler.on_llm_config_changed)
        gemini_layout.addRow("Model Name:", self.gemini_model_selector); left_layout.addWidget(self.gemini_group)
        # LLM Status (utilise QGridLayout pour aligner le bouton Re-Check)
        llm_status_layout = QGridLayout()
        llm_status_layout.setContentsMargins(0, 5, 0, 0)
        self.llm_status_label = QLabel("LLM Status: Initializing...")
        self.llm_status_label.setWordWrap(True)
        llm_status_layout.addWidget(self.llm_status_label, 0, 0)
        self.llm_reconnect_button = QPushButton("Re-Check")
        self.llm_reconnect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.llm_reconnect_button.clicked.connect(self.handler.attempt_llm_connection)
        llm_status_layout.addWidget(self.llm_reconnect_button, 0, 1, Qt.AlignmentFlag.AlignRight)
        llm_status_layout.setColumnStretch(0, 1); llm_status_layout.setColumnStretch(1, 0)
        left_layout.addLayout(llm_status_layout)


        # --- Espaceur pour pousser les éléments Dev vers le bas (inchangé) ---
        left_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # --- Section Dépendances Manuelles (structure inchangée, positionnée par l'espaceur) ---
        self.deps_group = QGroupBox("Manual Dependencies")
        deps_group_layout = QVBoxLayout(self.deps_group)
        deps_input_layout = QHBoxLayout()
        self.install_deps_input = QLineEdit(); self.install_deps_input.setPlaceholderText("requests pillow ...")
        deps_input_layout.addWidget(self.install_deps_input)
        self.install_deps_button = QPushButton("Install")
        self.install_deps_button.clicked.connect(self.handler.install_specific_dependencies)
        deps_input_layout.addWidget(self.install_deps_button)
        deps_group_layout.addLayout(deps_input_layout)
        self.deps_group.setEnabled(False)
        left_layout.addWidget(self.deps_group)

        # --- Section Logs (structure inchangée, positionnée par l'espaceur) ---
        self.save_logs_button = QPushButton("Save Logs")
        self.save_logs_button.setToolTip("Save Status and Execution logs to a file")
        self.save_logs_button.clicked.connect(self.handler.save_logs_to_file)
        left_layout.addWidget(self.save_logs_button)
        self.status_log_area_widget = QWidget()
        status_log_layout = QVBoxLayout(self.status_log_area_widget); status_log_layout.setContentsMargins(0,0,0,0)
        status_label = QLabel("Process Status:"); status_label.setStyleSheet("font-weight: bold;")
        status_log_layout.addWidget(status_label)
        self.status_log_text = QTextEdit(); self.status_log_text.setReadOnly(True); self.status_log_text.setFont(QFont("Arial", 8)); self.status_log_text.setMaximumHeight(100)
        status_log_layout.addWidget(self.status_log_text)
        left_layout.addWidget(self.status_log_area_widget)

        # --- Bouton Dev Tools (Tout en bas, inchangé) ---
        self.dev_mode_button = QPushButton("Show Dev Tools")
        self.dev_mode_button.setCheckable(True); self.dev_mode_button.setChecked(False)
        self.dev_mode_button.setToolTip("Show/Hide Developer Tools (Manual Dependencies, Logs)")
        self.dev_mode_button.toggled.connect(self.handler.toggle_dev_mode)
        left_layout.addWidget(self.dev_mode_button)

        # --- Fin du Panneau Gauche ---
        main_layout.addWidget(left_panel)


        # ======================================================================
        # --- Center Panel (Inchangé, mais visibilité Execution Log gérée par Dev Tools) ---
        # ======================================================================
        center_splitter = QSplitter(Qt.Orientation.Vertical)
        # --- Code Editor Area ---
        code_area = QWidget()
        code_layout = QVBoxLayout(code_area)
        code_label = QLabel(f"Project Code ({DEFAULT_MAIN_SCRIPT}):")
        self.code_editor_text = QTextEdit(); self.code_editor_text.setFont(QFont("Courier New", 10))
        self.code_highlighter = PythonHighlighter(self.code_editor_text.document())
        self.save_code_button = QPushButton("Save Code"); self.save_code_button.setEnabled(False)
        self.save_code_button.clicked.connect(self.handler.save_current_code)
        code_layout.addWidget(code_label); code_layout.addWidget(self.code_editor_text, 1)
        run_controls_layout = QHBoxLayout(); self.auto_correct_checkbox = QCheckBox("Enable Auto-Correction"); self.auto_correct_checkbox.setChecked(True)
        run_controls_layout.addWidget(self.auto_correct_checkbox); self.max_attempts_spinbox = QSpinBox(); self.max_attempts_spinbox.setRange(1, 10); self.max_attempts_spinbox.setValue(DEFAULT_MAX_CORRECTION_ATTEMPTS)
        run_controls_layout.addWidget(QLabel("Max Attempts:")); run_controls_layout.addWidget(self.max_attempts_spinbox); run_controls_layout.addStretch()
        self.run_script_button = QPushButton(f"Run Project"); self.run_script_button.setToolTip(f"Run {DEFAULT_MAIN_SCRIPT}"); self.run_script_button.setEnabled(False)
        self.run_script_button.clicked.connect(self.handler.run_current_project_script)
        run_controls_layout.addWidget(self.run_script_button); code_layout.addLayout(run_controls_layout); code_layout.addWidget(self.save_code_button)
        center_splitter.addWidget(code_area)
        # --- Execution Log Area ---
        self.execution_log_area_widget = QWidget()
        execution_log_layout = QVBoxLayout(self.execution_log_area_widget); execution_log_layout.setContentsMargins(0,5,0,0)
        execution_log_label = QLabel("Execution / Dependency / Export Logs:")
        self.execution_log_text = QTextEdit(); self.execution_log_text.setReadOnly(True); self.execution_log_text.setFont(QFont("Courier New", 9))
        execution_log_layout.addWidget(execution_log_label); execution_log_layout.addWidget(self.execution_log_text, 1)
        center_splitter.addWidget(self.execution_log_area_widget)
        center_splitter.setSizes([600, 200]); main_layout.addWidget(center_splitter, 1)

        # ======================================================================
        # --- Right Panel (Chat) ---
        # ======================================================================
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        right_panel.setMinimumWidth(350); right_panel.setMaximumWidth(500)

        chat_label = QLabel("AI Assistant Chat:")
        right_layout.addWidget(chat_label)

        self.chat_display_text = QTextEdit()
        self.chat_display_text.setReadOnly(True)
        self.chat_display_text.setFont(QFont("Arial", 9))
        right_layout.addWidget(self.chat_display_text, 1)

        chat_input_label = QLabel("Your Request:")
        right_layout.addWidget(chat_input_label)

        self.chat_input_text = QLineEdit()
        self.chat_input_text.setPlaceholderText("e.g., 'Create a simple calculator'")
        self.chat_input_text.returnPressed.connect(self.handler.send_chat_message)
        right_layout.addWidget(self.chat_input_text)

        # Layout pour les boutons Send et Cancel
        chat_buttons_layout = QHBoxLayout()

        self.chat_send_button = QPushButton("Send Request / Refine Code")
        self.chat_send_button.setEnabled(False)
        self.chat_send_button.clicked.connect(self.handler.send_chat_message)
        chat_buttons_layout.addWidget(self.chat_send_button)

        # <<< NOUVEAU BOUTON ANNULER >>>
        self.cancel_llm_button = QPushButton("Cancel Generation")
        self.cancel_llm_button.setVisible(False) # Caché par défaut
        self.cancel_llm_button.clicked.connect(self.handler.cancel_current_task) # Connecté au handler
        # Définir un nom d'objet pour un style potentiel
        self.cancel_llm_button.setObjectName("cancelButton")
        chat_buttons_layout.addWidget(self.cancel_llm_button)

        right_layout.addLayout(chat_buttons_layout) # Ajoute le layout des boutons

        main_layout.addWidget(right_panel)

        # Stretch factors (inchangés)
        main_layout.setStretchFactor(left_panel, 0)
        main_layout.setStretchFactor(center_splitter, 1)
        main_layout.setStretchFactor(right_panel, 0)
        # --- End of UI Setup ---


    def load_initial_settings(self):
        """Charge les paramètres depuis config_manager et met à jour l'UI."""
        print("Loading initial UI settings from config...")

        # --- Blocage des signaux ---
        self.gemini_api_key_input.blockSignals(True)
        self.gemini_model_selector.blockSignals(True)
        self.llm_ip_input.blockSignals(True)
        self.llm_port_input.blockSignals(True)
        # --------------------------

        try:
            saved_api_key = config_manager.get_api_key()
            if saved_api_key: self.gemini_api_key_input.setText(saved_api_key); print("Loaded saved Gemini API Key.")
            else: print("No saved Gemini API Key found.")

            last_gemini_model = config_manager.get_last_used_gemini_model()
            model_index = -1
            if last_gemini_model:
                model_index = self.gemini_model_selector.findText(last_gemini_model, Qt.MatchFlag.MatchExactly)
            if model_index != -1: self.gemini_model_selector.setCurrentIndex(model_index); print(f"Set Gemini model to last used: {last_gemini_model}")
            else:
                default_index = self.gemini_model_selector.findText(DEFAULT_GEMINI_MODEL, Qt.MatchFlag.MatchExactly)
                if default_index != -1: self.gemini_model_selector.setCurrentIndex(default_index); print(f"Set Gemini model to default: {DEFAULT_GEMINI_MODEL}")
                else: print("Warning: Default or last used Gemini model not found in available list.")

            last_lmstudio_ip = config_manager.get_last_used_lmstudio_ip()
            last_lmstudio_port = config_manager.get_last_used_lmstudio_port()
            self.llm_ip_input.setText(last_lmstudio_ip or DEFAULT_LM_STUDIO_IP)
            self.llm_port_input.setText(str(last_lmstudio_port or DEFAULT_LM_STUDIO_PORT))
            print(f"Set LM Studio IP to: {self.llm_ip_input.text()}")
            print(f"Set LM Studio Port to: {self.llm_port_input.text()}")

        finally:
            # --- Déblocage des signaux ---
            self.gemini_api_key_input.blockSignals(False)
            self.gemini_model_selector.blockSignals(False)
            self.llm_ip_input.blockSignals(False)
            self.llm_port_input.blockSignals(False)
            # ----------------------------
        print("Initial UI settings loaded.")

    def update_llm_ui_for_backend(self):
        """Met à jour la visibilité des groupes LLM."""
        selected_backend = self.llm_backend_selector.currentText()
        is_lmstudio = selected_backend == LLM_BACKEND_LMSTUDIO
        is_gemini = selected_backend == LLM_BACKEND_GEMINI

        print(f"Updating LLM UI visibility for backend: {selected_backend}")

        self.llm_ip_input.blockSignals(True); self.llm_port_input.blockSignals(True)
        self.gemini_api_key_input.blockSignals(True); self.gemini_model_selector.blockSignals(True)

        try:
            self.lmstudio_group.setVisible(is_lmstudio)
            self.gemini_group.setVisible(is_gemini)
        finally:
            self.llm_ip_input.blockSignals(False); self.llm_port_input.blockSignals(False)
            self.gemini_api_key_input.blockSignals(False); self.gemini_model_selector.blockSignals(False)

        print(f"LLM UI visibility updated.")


    def set_dev_elements_visibility(self, visible: bool):
        """Affiche ou masque les éléments UI liés au mode développeur."""
        print(f"Setting Dev Elements Visibility: {visible}")

        # Panneau de GAUCHE
        if hasattr(self, 'deps_group'): self.deps_group.setVisible(visible)
        if hasattr(self, 'save_logs_button'): self.save_logs_button.setVisible(visible)
        if hasattr(self, 'status_log_area_widget'): self.status_log_area_widget.setVisible(visible)

        # Panneau CENTRAL
        if hasattr(self, 'execution_log_area_widget'): self.execution_log_area_widget.setVisible(visible)

        # Bouton Dev (toujours visible, texte change)
        if hasattr(self, 'dev_mode_button'): self.dev_mode_button.setText("Hide Dev Tools" if visible else "Show Dev Tools")


    def closeEvent(self, event):
        """Gère la fermeture de la fenêtre."""
        self.handler.handle_close_event(event)

# --- Fin de la classe MainWindow ---