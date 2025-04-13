# src/gui_main_window.py

import sys
import platform
from typing import Optional, List, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLineEdit, QLabel, QSplitter, QMessageBox,
    QDialog, QDialogButtonBox, QApplication, QListWidgetItem, QFormLayout,
    QFileDialog, QComboBox, QGroupBox, QCheckBox, QSpinBox, QSizePolicy
    # REMOVE QTextCharFormat from here if it was present
)
from PyQt6.QtCore import Qt, QTimer # Keep QTimer here
from PyQt6.QtGui import (
    QFont, QIntValidator, QSyntaxHighlighter, QColor,
    QTextCharFormat 
)
# Import other necessary components
from . import project_manager
from .llm_interaction import (
    DEFAULT_LM_STUDIO_IP, DEFAULT_LM_STUDIO_PORT, DEFAULT_GEMINI_MODEL,
    AVAILABLE_GEMINI_MODELS, GOOGLE_GENAI_AVAILABLE
)
from .project_manager import DEFAULT_MAIN_SCRIPT
from .gui_actions_handler import GuiActionsHandler, LLM_BACKEND_LMSTUDIO, LLM_BACKEND_GEMINI, DEFAULT_MAX_CORRECTION_ATTEMPTS

# --- Syntax Highlighting (Copied from original gui.py, no changes needed) ---
# [Paste the PythonHighlighter class here - identical to the one in the original gui.txt]
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []
        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor("lightblue"))
        keywordFormat.setFontWeight(QFont.Weight.Bold)
        keywords = ["def", "class", "import", "from", "return", "if", "else", "elif", "for", "while", "try", "except", "finally", "with", "as", "in", "True", "False", "None", "self", "lambda", "yield", "pass", "continue", "break", "is", "not", "and", "or", "del", "global", "nonlocal", "assert"]
        self.highlightingRules.extend([(r'\b' + k + r'\b', keywordFormat) for k in keywords])

        stringFormat = QTextCharFormat()
        stringFormat.setForeground(QColor("lightgreen"))
        self.highlightingRules.append((r'"[^"\\]*(\\.[^"\\]*)*"', stringFormat))
        self.highlightingRules.append((r"'[^'\\]*(\\.[^'\\]*)*'", stringFormat))

        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor("gray"))
        self.highlightingRules.append((r'#.*', commentFormat))

        numberFormat = QTextCharFormat()
        numberFormat.setForeground(QColor("orange"))
        self.highlightingRules.append((r'\b[0-9]+\b', numberFormat))
        self.highlightingRules.append((r'\b0x[0-9A-Fa-f]+\b', numberFormat))

        functionFormat = QTextCharFormat()
        functionFormat.setForeground(QColor("yellow"))
        self.highlightingRules.append((r'\b[A-Za-z_][A-Za-z0-9_]*(?=\()', functionFormat))

        decoratorFormat = QTextCharFormat()
        decoratorFormat.setForeground(QColor("magenta"))
        self.highlightingRules.append((r'@[A-Za-z_][A-Za-z0-9_.]*', decoratorFormat))

    def highlightBlock(self, text):
        if len(text) > 2000: return # Perf optimization
        for pattern, format_rule in self.highlightingRules:
            try:
                # Use re.finditer for better performance on longer lines if needed
                for match in __import__('re').finditer(pattern, text):
                    start, end = match.span()
                    self.setFormat(start, end - start, format_rule)
            except Exception: pass # Ignore regex errors
        self.setCurrentBlockState(0)


# --- Fenêtre Principale ---
class MainWindow(QMainWindow):
    # --- UI Elements (Declare them here for type hinting) ---
    llm_backend_selector: QComboBox; lmstudio_group: QGroupBox; llm_ip_input: QLineEdit; llm_port_input: QLineEdit
    gemini_group: QGroupBox; gemini_api_key_input: QLineEdit; gemini_model_selector: QComboBox
    project_list_widget: QListWidget; new_project_button: QPushButton; delete_project_button: QPushButton; export_button: QPushButton
    llm_status_label: QLabel; llm_reconnect_button: QPushButton
    code_editor_text: QTextEdit; save_code_button: QPushButton; run_script_button: QPushButton
    auto_correct_checkbox: QCheckBox; max_attempts_spinbox: QSpinBox
    execution_log_text: QTextEdit; status_log_text: QTextEdit
    chat_display_text: QTextEdit; chat_input_text: QLineEdit; chat_send_button: QPushButton
    code_highlighter: PythonHighlighter

    # --- Handler ---
    handler: GuiActionsHandler

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pythautom - AI Python Project Builder")
        self.setGeometry(100, 100, 1400, 850)

        # Instantiate the handler, passing self (the main window)
        self.handler = GuiActionsHandler(self)

        # Setup UI
        self.setup_ui()

        # Initial state setup via handler
        self.handler.load_project_list()
        self.update_llm_ui_for_backend() # Initial UI update based on default selection
        self.handler.attempt_llm_connection() # Attempt connection on startup

    def setup_ui(self):
        """Sets up the main window widgets and layouts."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget) # Main layout is horizontal

        # --- Left Panel (Projects & LLM Config) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMinimumWidth(280)
        left_panel.setMaximumWidth(350) # Control width

        # Projects Section
        project_label = QLabel("Projects:")
        self.project_list_widget = QListWidget()
        # Connect signal to the handler's method
        self.project_list_widget.currentItemChanged.connect(self.handler.load_selected_project)
        left_layout.addWidget(project_label)
        left_layout.addWidget(self.project_list_widget)

        project_button_layout = QHBoxLayout()
        self.new_project_button = QPushButton("New")
        self.new_project_button.setToolTip("Create a new project")
        # Connect signal to the handler's method
        self.new_project_button.clicked.connect(self.handler.create_new_project_dialog)
        project_button_layout.addWidget(self.new_project_button)

        self.delete_project_button = QPushButton("Delete")
        self.delete_project_button.setToolTip("Delete selected project")
        # Connect signal to the handler's method
        self.delete_project_button.clicked.connect(self.handler.confirm_delete_project)
        self.delete_project_button.setEnabled(False)
        project_button_layout.addWidget(self.delete_project_button)

        self.export_button = QPushButton("Export")
        self.export_button.setToolTip(f"Create executable bundle (.zip) for {platform.system()}")
        # Connect signal to the handler's method
        self.export_button.clicked.connect(self.handler.prompt_export_project)
        self.export_button.setEnabled(False)
        project_button_layout.addWidget(self.export_button)
        left_layout.addLayout(project_button_layout)

        # LLM Configuration Section
        llm_config_label = QLabel("LLM Configuration:")
        llm_config_label.setStyleSheet("font-weight: bold; margin-top: 15px;")
        left_layout.addWidget(llm_config_label)

        backend_layout = QHBoxLayout()
        backend_layout.addWidget(QLabel("Backend:"))
        self.llm_backend_selector = QComboBox()
        self.llm_backend_selector.addItems([LLM_BACKEND_LMSTUDIO, LLM_BACKEND_GEMINI])
        if not GOOGLE_GENAI_AVAILABLE:
            self.llm_backend_selector.model().item(1).setEnabled(False)
            self.llm_backend_selector.setToolTip("Google Gemini requires 'google-generai' library installed.")
        # Connect signal to this window's method (which might then call handler if needed)
        self.llm_backend_selector.currentTextChanged.connect(self.update_llm_ui_for_backend)
        backend_layout.addWidget(self.llm_backend_selector)
        left_layout.addLayout(backend_layout)

        # LM Studio Group
        self.lmstudio_group = QGroupBox("LM Studio Settings")
        lmstudio_layout = QFormLayout(self.lmstudio_group)
        self.llm_ip_input = QLineEdit(DEFAULT_LM_STUDIO_IP)
        self.llm_ip_input.setPlaceholderText("Server IP Address")
        lmstudio_layout.addRow("Server IP:", self.llm_ip_input)
        self.llm_port_input = QLineEdit(str(DEFAULT_LM_STUDIO_PORT))
        self.llm_port_input.setPlaceholderText("Port")
        self.llm_port_input.setValidator(QIntValidator(1, 65535))
        lmstudio_layout.addRow("Port:", self.llm_port_input)
        left_layout.addWidget(self.lmstudio_group)

        # Gemini Group
        self.gemini_group = QGroupBox("Google Gemini Settings")
        gemini_layout = QFormLayout(self.gemini_group)
        self.gemini_api_key_input = QLineEdit()
        self.gemini_api_key_input.setPlaceholderText("Enter your Google API Key")
        self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.setToolTip("Store securely!")
        gemini_layout.addRow("API Key:", self.gemini_api_key_input)
        self.gemini_model_selector = QComboBox()
        self.gemini_model_selector.addItems(AVAILABLE_GEMINI_MODELS)
        try:
            # Find default model index robustly
            default_index = -1
            if DEFAULT_GEMINI_MODEL in AVAILABLE_GEMINI_MODELS:
                default_index = AVAILABLE_GEMINI_MODELS.index(DEFAULT_GEMINI_MODEL)
            if default_index != -1:
                 self.gemini_model_selector.setCurrentIndex(default_index)
            else: # Fallback if default not found
                 if AVAILABLE_GEMINI_MODELS: self.gemini_model_selector.setCurrentIndex(0)
        except Exception: pass # Ignore potential errors during setup
        self.gemini_model_selector.setToolTip("Select the Gemini model to use.")
        gemini_layout.addRow("Model Name:", self.gemini_model_selector)
        left_layout.addWidget(self.gemini_group)

        # LLM Status and Reconnect
        self.llm_status_label = QLabel("LLM Status: Unknown")
        left_layout.addWidget(self.llm_status_label)
        self.llm_reconnect_button = QPushButton("Connect / Re-Check LLM")
        # Connect signal to the handler's method
        self.llm_reconnect_button.clicked.connect(self.handler.attempt_llm_connection)
        left_layout.addWidget(self.llm_reconnect_button)

        # Status Log Area
        status_label = QLabel("Process Status:")
        status_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        left_layout.addWidget(status_label)
        self.status_log_text = QTextEdit()
        self.status_log_text.setReadOnly(True)
        self.status_log_text.setFont(QFont("Arial", 8))
        self.status_log_text.setMaximumHeight(100) # Limit height
        left_layout.addWidget(self.status_log_text)

        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # --- Center Panel (Code Editor & Execution Log) ---
        center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Code Editor Area
        code_area = QWidget()
        code_layout = QVBoxLayout(code_area)
        code_label = QLabel(f"Project Code ({DEFAULT_MAIN_SCRIPT}):")
        self.code_editor_text = QTextEdit()
        self.code_editor_text.setFont(QFont("Courier New", 10))
        self.code_highlighter = PythonHighlighter(self.code_editor_text.document())
        self.save_code_button = QPushButton("Save Code")
        # Connect signal to the handler's method
        self.save_code_button.clicked.connect(self.handler.save_current_code)
        self.save_code_button.setEnabled(False)
        code_layout.addWidget(code_label)
        code_layout.addWidget(self.code_editor_text, 1) # Stretch factor
        code_layout.addWidget(self.save_code_button)
        center_splitter.addWidget(code_area)

        # Execution Log Area
        execution_log_area = QWidget()
        execution_log_layout = QVBoxLayout(execution_log_area)
        execution_log_label = QLabel("Execution / Dependency / Export Logs:")
        self.execution_log_text = QTextEdit()
        self.execution_log_text.setReadOnly(True)
        self.execution_log_text.setFont(QFont("Courier New", 9))

        # Run Controls Layout
        run_controls_layout = QHBoxLayout()
        self.auto_correct_checkbox = QCheckBox("Enable Auto-Correction")
        self.auto_correct_checkbox.setChecked(True)
        self.auto_correct_checkbox.setToolTip("If checked, automatically ask the AI to fix errors after script execution fails.")
        run_controls_layout.addWidget(self.auto_correct_checkbox)

        self.max_attempts_spinbox = QSpinBox()
        self.max_attempts_spinbox.setRange(1, 10)
        self.max_attempts_spinbox.setValue(DEFAULT_MAX_CORRECTION_ATTEMPTS)
        self.max_attempts_spinbox.setToolTip("Maximum number of automatic correction attempts if script fails.")
        run_controls_layout.addWidget(QLabel("Max Attempts:"))
        run_controls_layout.addWidget(self.max_attempts_spinbox)
        run_controls_layout.addStretch()

        self.run_script_button = QPushButton(f"Run Project Script ({DEFAULT_MAIN_SCRIPT})")
        # Connect signal to the handler's method
        self.run_script_button.clicked.connect(self.handler.run_current_project_script)
        self.run_script_button.setEnabled(False)
        run_controls_layout.addWidget(self.run_script_button)

        execution_log_layout.addWidget(execution_log_label)
        execution_log_layout.addWidget(self.execution_log_text, 1) # Stretch factor
        execution_log_layout.addLayout(run_controls_layout)
        center_splitter.addWidget(execution_log_area)

        center_splitter.setSizes([500, 300]) # Initial sizes
        main_layout.addWidget(center_splitter, 1) # Allow center panel to stretch

        # --- Right Panel (Chat) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_panel.setMinimumWidth(350)
        right_panel.setMaximumWidth(500) # Control max width

        chat_label = QLabel("AI Assistant Chat:")
        right_layout.addWidget(chat_label)

        self.chat_display_text = QTextEdit()
        self.chat_display_text.setReadOnly(True)
        self.chat_display_text.setFont(QFont("Arial", 9))
        right_layout.addWidget(self.chat_display_text, 1)

        chat_input_label = QLabel("Your Request (describe initial goal or modifications):")
        right_layout.addWidget(chat_input_label)
        self.chat_input_text = QLineEdit()
        self.chat_input_text.setPlaceholderText("e.g., 'Create a simple calculator', 'Add a button to...'")
        # Connect signal to the handler's method
        self.chat_input_text.returnPressed.connect(self.handler.send_chat_message)
        right_layout.addWidget(self.chat_input_text)

        self.chat_send_button = QPushButton("Send Request / Refine Code")
        # Connect signal to the handler's method
        self.chat_send_button.clicked.connect(self.handler.send_chat_message)
        self.chat_send_button.setEnabled(False)
        right_layout.addWidget(self.chat_send_button)
        main_layout.addWidget(right_panel)

        # Set overall stretch factors
        main_layout.setStretchFactor(left_panel, 0)
        main_layout.setStretchFactor(center_splitter, 1)
        main_layout.setStretchFactor(right_panel, 0)
        # --- End of UI Setup ---

    def update_llm_ui_for_backend(self):
        """Updates visibility of LLM settings based on backend selection."""
        selected_backend = self.llm_backend_selector.currentText()
        is_lmstudio = selected_backend == LLM_BACKEND_LMSTUDIO
        is_gemini = selected_backend == LLM_BACKEND_GEMINI

        self.lmstudio_group.setVisible(is_lmstudio)
        self.gemini_group.setVisible(is_gemini)

        # Notify handler if backend type changed (it might reset client)
        if self.handler.llm_client and self.handler.llm_client.get_backend_name() != selected_backend:
            self.handler.llm_client = None # Handler manages the client instance
            self.llm_status_label.setText("LLM Status: Backend Changed")
            self.llm_status_label.setStyleSheet("color: orange;")
            # Let handler update UI state after client reset if needed
            self.handler.set_ui_enabled(self.handler._current_task_phase == self.handler.TASK_IDLE)

    def closeEvent(self, event):
        """Handles the application close event, confirms if busy."""
        # Delegate confirmation and cancellation to the handler
        self.handler.handle_close_event(event)

