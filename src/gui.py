# src/gui.py
# VERSION FINALE : Base Originale + IP/Port + Logique de Chaînage Corrigée

import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLineEdit, QLabel, QSplitter, QMessageBox,
    QDialog, QDialogButtonBox, QApplication, QListWidgetItem, QFormLayout # Ajout QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QIntValidator # Ajout QIntValidator
)
import json
import re # Pour cleanup et sanitization (nom projet)
import traceback
import os
import subprocess # Pour type hinting
from typing import List, Any, Optional, Dict, Callable

# Importer nos modules locaux
from . import project_manager # Utilise le project_manager fourni
from . import utils
# Importer LLMClient et les valeurs par défaut
try:
    from .llm_interaction import LLMClient, DEFAULT_LM_STUDIO_PORT, DEFAULT_LM_STUDIO_IP
except ImportError:
    print("Warning: Could not import default IP/Port from llm_interaction. Using hardcoded defaults.")
    from .llm_interaction import LLMClient
    DEFAULT_LM_STUDIO_IP = "127.0.0.1"
    DEFAULT_LM_STUDIO_PORT = 1234
from .project_manager import DEFAULT_MAIN_SCRIPT

# --- CONSTANTES (avec la nouvelle constante de connexion) ---
TASK_IDLE = "idle"
TASK_IDENTIFY_DEPS = "identify_deps"
TASK_INSTALL_DEPS = "install_deps"
TASK_GENERATE_CODE = "generate_code"
TASK_RUN_SCRIPT = "run_script"
TASK_ATTEMPT_CONNECTION = "attempt_connection" # Remplacement de check_connection
# --- FIN CONSTANTES ---

# --- Syntax Highlighting (Original) ---
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent); self.highlightingRules = []
        keywordFormat=QTextCharFormat(); keywordFormat.setForeground(QColor("lightblue")); keywordFormat.setFontWeight(QFont.Weight.Bold)
        keywords=["def","class","import","from","return","if","else","elif","for","while","try","except","finally","with","as","in","True","False","None","self","lambda","yield","pass","continue","break","is","not","and","or","del","global","nonlocal","assert"]
        self.highlightingRules.extend([(r'\b' + k + r'\b', keywordFormat) for k in keywords])
        stringFormat=QTextCharFormat(); stringFormat.setForeground(QColor("lightgreen"))
        self.highlightingRules.append((r'"[^"\\]*(\\.[^"\\]*)*"', stringFormat)); self.highlightingRules.append((r"'[^'\\]*(\\.[^'\\]*)*'", stringFormat))
        commentFormat=QTextCharFormat(); commentFormat.setForeground(QColor("gray")); self.highlightingRules.append((r'#.*', commentFormat))
        numberFormat=QTextCharFormat(); numberFormat.setForeground(QColor("orange")); self.highlightingRules.append((r'\b[0-9]+\b', numberFormat)); self.highlightingRules.append((r'\b0x[0-9A-Fa-f]+\b', numberFormat))
        functionFormat=QTextCharFormat(); functionFormat.setForeground(QColor("yellow")); self.highlightingRules.append((r'\b[A-Za-z_][A-Za-z0-9_]*(?=\()', functionFormat))
        decoratorFormat=QTextCharFormat(); decoratorFormat.setForeground(QColor("magenta")); self.highlightingRules.append((r'@[A-Za-z_][A-Za-z0-9_.]*', decoratorFormat))
    def highlightBlock(self, text):
        if len(text) > 2000: return # Augmenté un peu la limite
        for p, f in self.highlightingRules:
            try:
                for m in re.finditer(p, text):
                     s, e = m.span(); self.setFormat(s, e - s, f)
            except Exception: pass
        self.setCurrentBlockState(0)

# --- Worker Thread (Modifié pour TASK_ATTEMPT_CONNECTION) ---
class Worker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    code_fragment_received = pyqtSignal(str)
    result = pyqtSignal(str, object) # task_type, actual_result

    def __init__(self, task_type: str, task_callable: Callable, *args, **kwargs):
        super().__init__(); self.task_type = task_type; self.task_callable = task_callable; self.args = args; self.kwargs = kwargs; self._is_cancelled = False
    def cancel(self): self._is_cancelled = True; self.progress.emit(f"Task '{self.task_type}' cancellation requested..."); print(f"[Worker {id(self)}] Cancellation flag set.")
    def run(self):
        print(f"[Worker {id(self)}] STARTING task type: '{self.task_type}', callable: {self.task_callable.__name__}")
        self.progress.emit(f"Starting: {self.task_type}..."); self._is_cancelled = False; task_result: Any = None; msg = ""
        try:
            if self._is_cancelled: raise InterruptedError("Cancelled before execution")
            if self.task_type == TASK_IDENTIFY_DEPS: task_result = self.task_callable(*self.args, **self.kwargs); msg = "Dependency ID finished."
            elif self.task_type == TASK_INSTALL_DEPS: install_ok = self.task_callable(*self.args, **self.kwargs); task_result = install_ok; msg = f"Install {'OK' if install_ok else 'failed'}."
            elif self.task_type == TASK_GENERATE_CODE: actual_kwargs = self.kwargs.copy(); actual_kwargs.setdefault("fragment_callback", self.code_fragment_received.emit); self.task_callable(*self.args, **actual_kwargs); task_result = True; msg = "Code generation/correction finished."
            elif self.task_type == TASK_RUN_SCRIPT: task_result = self.task_callable(*self.args, **self.kwargs); msg = "Script execution finished."
            elif self.task_type == TASK_ATTEMPT_CONNECTION: task_result = self.task_callable(*self.args, **self.kwargs); msg = f"Connection attempt finished ({'Success' if task_result else 'Failed'})."
            else: raise NotImplementedError(f"Unknown task type {self.task_type}")

            if not self._is_cancelled: self.progress.emit(msg); self.result.emit(self.task_type, task_result)
        except InterruptedError as ie: print(f"Task '{self.task_type}' interrupted: {ie}"); self.progress.emit(f"Task '{self.task_type}' cancelled.")
        except Exception as e:
            if not self._is_cancelled: error_msg = f"Error in worker task '{self.task_type}': {e}"; print(f"EXCEPTION:\n{traceback.format_exc()}"); self.progress.emit(error_msg); self.result.emit(self.task_type, e)
            else: print(f"Exception ({e}) but task was cancelled.")
        finally: print(f"[Worker {id(self)}] FINISHED task '{self.task_type}'. Emitting finished (Cancelled={self._is_cancelled})."); self.finished.emit()

# --- Fenêtre Principale ---
class MainWindow(QMainWindow):
    # Garde les attributs de l'original
    _current_task_phase: str = TASK_IDLE
    _current_user_prompt: str = ""
    _identified_dependencies: List[str] = []
    _pending_install_deps: List[str] = []
    _code_to_correct: Optional[str] = None
    _last_execution_error: Optional[str] = None
    _correction_attempts: int = 0
    MAX_CORRECTION_ATTEMPTS: int = 2

    # Ajout références UI pour IP/Port
    llm_ip_input: QLineEdit
    llm_port_input: QLineEdit
    # Références UI de l'original (pour vérification)
    project_list_widget: QListWidget
    new_project_button: QPushButton
    delete_project_button: Optional[QPushButton] = None
    llm_status_label: QLabel
    llm_reconnect_button: QPushButton
    ai_output_text: QTextEdit
    ai_input_text: QLineEdit
    ai_send_button: QPushButton
    code_editor_text: QTextEdit
    save_code_button: QPushButton
    output_console_text: QTextEdit
    run_script_button: QPushButton
    code_highlighter: PythonHighlighter


    def __init__(self):
        super().__init__()
        # Titre et géométrie originaux modifiés
        self.setWindowTitle("Pythautom - AI Python Project Builder")
        self.setGeometry(100, 100, 1200, 800) # Un peu plus grand
        self.current_project: Optional[str] = None
        self.llm_client = LLMClient() # Initialise sans connecter
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        # self.delete_project_button déjà initialisé à None

        self.setup_ui()
        self.load_project_list()
        self.attempt_llm_connection() # Tente connexion au démarrage

    def setup_ui(self):
        """Configure l'interface utilisateur (basé sur l'original + IP/Port)."""
        main_widget=QWidget(); self.setCentralWidget(main_widget); main_layout=QHBoxLayout(main_widget)
        left_panel=QWidget(); left_layout=QVBoxLayout(left_panel)
        left_panel.setFixedWidth(270) # Légèrement élargi pour IP/Port
        project_label=QLabel("Projects:"); self.project_list_widget=QListWidget(); self.project_list_widget.currentItemChanged.connect(self.load_selected_project)
        left_layout.addWidget(project_label); left_layout.addWidget(self.project_list_widget)
        project_button_layout=QHBoxLayout()
        self.new_project_button=QPushButton("New Project"); self.new_project_button.clicked.connect(self.create_new_project_dialog); project_button_layout.addWidget(self.new_project_button)
        # Assure que delete_project_button est créé
        self.delete_project_button = QPushButton("Delete Project"); self.delete_project_button.clicked.connect(self.confirm_delete_project); self.delete_project_button.setEnabled(False); project_button_layout.addWidget(self.delete_project_button)
        left_layout.addLayout(project_button_layout)

        # --- AJOUT: LLM Connection Settings ---
        llm_settings_label = QLabel("LM Studio Connection:")
        llm_settings_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        left_layout.addWidget(llm_settings_label)
        llm_form_layout = QFormLayout()
        self.llm_ip_input = QLineEdit(DEFAULT_LM_STUDIO_IP)
        self.llm_ip_input.setPlaceholderText("Server IP Address")
        llm_form_layout.addRow("Server IP:", self.llm_ip_input)
        self.llm_port_input = QLineEdit(str(DEFAULT_LM_STUDIO_PORT))
        self.llm_port_input.setPlaceholderText("Port")
        self.llm_port_input.setValidator(QIntValidator(1, 65535))
        llm_form_layout.addRow("Port:", self.llm_port_input)
        left_layout.addLayout(llm_form_layout)
        # --- FIN AJOUT ---

        self.llm_status_label=QLabel("LLM Status: Unknown")
        left_layout.addWidget(self.llm_status_label)
        self.llm_reconnect_button=QPushButton("Connect / Re-Check LLM")
        self.llm_reconnect_button.clicked.connect(self.attempt_llm_connection) # Connecté à la bonne fonction
        left_layout.addWidget(self.llm_reconnect_button); left_layout.addStretch(); main_layout.addWidget(left_panel)

        # --- Right Panel (Original) ---
        right_splitter = QSplitter(Qt.Orientation.Vertical); interaction_code_widget=QWidget(); interaction_code_layout=QHBoxLayout(interaction_code_widget); interaction_area=QWidget(); interaction_layout=QVBoxLayout(interaction_area); interaction_label=QLabel("AI Interaction / Status:"); self.ai_output_text=QTextEdit(); self.ai_output_text.setReadOnly(True); self.ai_output_text.setFont(QFont("Arial", 9)); self.ai_input_text=QLineEdit(); self.ai_input_text.setPlaceholderText("Describe what you want to build or modify..."); self.ai_send_button=QPushButton("Generate / Modify Code"); self.ai_send_button.clicked.connect(self.start_generation_process); self.ai_send_button.setEnabled(False); interaction_layout.addWidget(interaction_label); interaction_layout.addWidget(self.ai_output_text, 1); interaction_layout.addWidget(self.ai_input_text); interaction_layout.addWidget(self.ai_send_button); interaction_area.setMinimumWidth(350); code_area=QWidget(); code_layout=QVBoxLayout(code_area); code_label=QLabel(f"Project Code ({DEFAULT_MAIN_SCRIPT}):"); self.code_editor_text=QTextEdit(); self.code_editor_text.setFont(QFont("Courier New", 10)); self.code_highlighter = PythonHighlighter(self.code_editor_text.document()); self.save_code_button=QPushButton("Save Code"); self.save_code_button.clicked.connect(self.save_current_code); self.save_code_button.setEnabled(False); code_layout.addWidget(code_label); code_layout.addWidget(self.code_editor_text, 1); code_layout.addWidget(self.save_code_button); interaction_code_layout.addWidget(interaction_area); interaction_code_layout.addWidget(code_area, 1); right_splitter.addWidget(interaction_code_widget); output_widget=QWidget(); output_layout=QVBoxLayout(output_widget); output_label=QLabel("Execution Output / Logs:"); self.output_console_text=QTextEdit(); self.output_console_text.setReadOnly(True); self.output_console_text.setFont(QFont("Courier New", 9)); self.run_script_button=QPushButton(f"Run Project Script ({DEFAULT_MAIN_SCRIPT})"); self.run_script_button.clicked.connect(self.run_current_project_script); self.run_script_button.setEnabled(False); output_layout.addWidget(output_label); output_layout.addWidget(self.output_console_text, 1); output_layout.addWidget(self.run_script_button); right_splitter.addWidget(output_widget); right_splitter.setSizes([450, 300]); main_layout.addWidget(right_splitter, 1)


    # --- MODIFIÉ : start_worker (utilise lambda pour _on_thread_finished) ---
    def start_worker(self, task_type: str, task_callable: Callable, *args, **kwargs) -> bool:
        """Starts a background task in a QThread."""
        if self.thread is not None and self.thread.isRunning():
            print(f"Warning: Task '{task_type}' requested, but previous thread active."); QMessageBox.warning(self, "Busy", "Task already running."); return False
        # Définit la phase *avant* de démarrer le thread
        self._current_task_phase = task_type
        self.set_ui_enabled(False, task_type) # Désactive UI
        self.thread = QThread(); self.thread.setObjectName(f"WorkerThread_{task_type}_{id(self.thread)}")
        self.worker = Worker(task_type, task_callable, *args, **kwargs)
        self.worker.moveToThread(self.thread)
        # Connecte les signaux du worker
        self.worker.progress.connect(self.log_to_ai_output)
        self.worker.result.connect(self.handle_worker_result)
        self.worker.code_fragment_received.connect(self.append_code_fragment)
        # Connecte les signaux de fin
        self.worker.finished.connect(self.thread.quit) # Worker fini -> Thread arrête la boucle d'event
        self.worker.finished.connect(self.worker.deleteLater) # Programme suppression worker
        self.thread.finished.connect(self.thread.deleteLater) # Programme suppression thread
        # --- CORRECTION : Connexion explicite avec le type de tâche terminé ---
        # Utilise une lambda pour capturer la valeur actuelle de task_type
        self.thread.finished.connect(lambda task=task_type: self._on_thread_finished(finished_task_type=task))
        # --- FIN CORRECTION ---
        # Connecte le démarrage du worker au démarrage du thread
        self.thread.started.connect(self.worker.run)
        self.thread.start() # Démarre la boucle d'événements du thread
        print(f"Worker started for task: {task_type} on thread {self.thread.objectName()}"); return True

    # Supprimé : on_worker_task_completed (n'était pas utilisé dans la logique finale)
    # def on_worker_task_completed(self):
    #     print(f"Worker task completed signal received (Phase was: {self._current_task_phase}).")

    # --- CORRIGÉ : _on_thread_finished (appelle run_current_project_script avec le nouveau paramètre) ---
    def _on_thread_finished(self, finished_task_type: str):
        """Handles the logic after a worker thread finishes, deciding the next step."""
        sender_obj = self.sender()
        thread_name = sender_obj.objectName() if sender_obj else "N/A"
        next_logical_phase = getattr(self, '_next_logical_phase_after_result', TASK_IDLE)
        print(f"Thread '{thread_name}' finished. Task that finished: '{finished_task_type}'. Next logical phase: '{next_logical_phase}'. Cleaning up GUI refs.")

        self.thread = None; self.worker = None
        print("GUI refs cleaned.")

        try:
            # CAS 1: ID_DEPS terminée
            if finished_task_type == TASK_IDENTIFY_DEPS:
                if next_logical_phase == TASK_INSTALL_DEPS and self._pending_install_deps:
                    print("Transition: ID_DEPS -> INSTALL_DEPS")
                    self.log_to_ai_output(f"--- Starting installation: {self._pending_install_deps} ---")
                    if self.current_project:
                        project_path = project_manager.get_project_path(self.current_project)
                        if not self.start_worker(task_type=TASK_INSTALL_DEPS, task_callable=utils.install_project_dependencies, project_path=project_path, dependencies=self._pending_install_deps):
                            self.log_to_ai_output("! Error starting install worker."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
                    else: self.log_to_ai_output("! Cannot start install, no project."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
                elif next_logical_phase == TASK_GENERATE_CODE:
                    print("Transition: ID_DEPS -> GENERATE_CODE (no deps)")
                    if not self.start_code_generation_worker():
                        self.log_to_ai_output("! Error starting generation worker (no deps)."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
                else: print(f"ID_DEPS finished, next phase '{next_logical_phase}'. Setting IDLE."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

            # CAS 2: INSTALL_DEPS terminée
            elif finished_task_type == TASK_INSTALL_DEPS:
                if next_logical_phase == TASK_GENERATE_CODE:
                    print("Transition: INSTALL_DEPS -> GENERATE_CODE")
                    if not self.start_code_generation_worker():
                        self.log_to_ai_output("! Error starting generation worker after install."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
                else: print("INSTALL_DEPS finished (or failed), next phase is IDLE."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

            # CAS 3: GENERATE_CODE terminée
            elif finished_task_type == TASK_GENERATE_CODE:
                if next_logical_phase == TASK_RUN_SCRIPT:
                    print("Transition: GENERATE_CODE -> RUN_SCRIPT")
                    if self.current_project:
                        code_content = self.code_editor_text.toPlainText()
                        if project_manager.save_project_script_content(self.current_project, code_content): self.log_to_console(f"Code auto-saved before execution.")
                        else: self.log_to_console(f"Warning: Failed to auto-save code before execution.")
                    # --- MODIFICATION : Appelle run_current_project_script avec called_from_chain=True ---
                    self.run_current_project_script(called_from_chain=True)
                    # --- FIN MODIFICATION ---
                else: print(f"GENERATE_CODE finished, next phase '{next_logical_phase}'. Setting IDLE."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

            # CAS 4: RUN_SCRIPT terminée
            elif finished_task_type == TASK_RUN_SCRIPT:
                if next_logical_phase == TASK_GENERATE_CODE: # Correction
                    print("Transition: RUN_SCRIPT -> GENERATE_CODE (Correction)")
                    if not self.start_code_generation_worker():
                         self.log_to_ai_output("! Error starting correction worker."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
                else: # Succès ou max tentatives
                     print("RUN_SCRIPT finished, next phase is IDLE.")
                     self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

            # CAS 5: ATTEMPT_CONNECTION terminée
            elif finished_task_type == TASK_ATTEMPT_CONNECTION:
                 print("ATTEMPT_CONNECTION finished, next phase is IDLE.")
                 self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

            # CAS 6: Autre
            else: print(f"Task '{finished_task_type}' finished. No specific chaining logic. Setting IDLE."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

        except Exception as e:
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"); print(f"ERROR in _on_thread_finished chaining logic for '{finished_task_type}':"); print(traceback.format_exc()); print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            self.log_to_ai_output(f"! Internal error during task chaining: {e}"); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
        finally:
            if hasattr(self, '_next_logical_phase_after_result'): del self._next_logical_phase_after_result

    # --- MODIFIÉ : run_current_project_script (accepte called_from_chain) ---
    def run_current_project_script(self, called_from_chain: bool = False):
        """
        Runs the project script. Includes a check to prevent manual execution
        while busy, unless called internally from the task chain.
        """
        # --- MODIFICATION : Ajout de 'not called_from_chain' à la condition ---
        if not called_from_chain and self._current_task_phase != TASK_IDLE:
            QMessageBox.warning(self, "Busy", "Cannot run script while another task is running.")
            return
        # --- FIN MODIFICATION ---

        if not self.current_project:
            # Si appelé manuellement sans projet
            if not called_from_chain: QMessageBox.warning(self, "No Project", "Select project.")
            else: print("Error: run_current_project_script called from chain without current_project set.") # Erreur interne
            return

        script_name = DEFAULT_MAIN_SCRIPT
        try:
            project_path = project_manager.get_project_path(self.current_project)
            script_file = os.path.join(project_path, script_name)
            if not os.path.isdir(project_path): msg = f"Dir not found: '{project_path}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
            if not os.path.exists(script_file): msg = f"Script not found: '{script_name}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
            if not utils.ensure_project_venv(project_path): msg = f"Failed ensure venv '{self.current_project}'."; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
        except Exception as e: msg=f"Error preparing to run script: {e}"; print(msg); traceback.print_exc(); QMessageBox.critical(self, "Run Error", msg); return

        self.log_to_console(f"\n--- Attempting to run script: {self.current_project}/{script_name} ---")

        started_successfully = self.start_worker(
            task_type=TASK_RUN_SCRIPT,
            task_callable=utils.run_project_script,
            project_path=project_path,
            script_name=script_name
        )

        if not started_successfully:
            self.log_to_console("--- Could not start script execution (Busy? Task overlap?). Reverting to Idle. ---")
            # Remet explicitement la phase à IDLE car la tâche n'a pas démarré.
            # Important pour que set_ui_enabled fonctionne correctement
            self._current_task_phase = TASK_IDLE
            self.set_ui_enabled(True)

    # --- MODIFIÉ : set_ui_enabled (gère IP/Port et bool()) ---
    def set_ui_enabled(self, enabled: bool, current_task: Optional[str] = None):
        """Active/Désactive les éléments UI pertinents."""
        llm_ok = self.llm_client.is_available(); is_project_loaded = self.current_project is not None
        # Applique l'état général 'enabled'
        self.new_project_button.setEnabled(enabled)
        self.project_list_widget.setEnabled(enabled)
        self.llm_reconnect_button.setEnabled(enabled)
        # Active/désactive les champs IP/Port si l'UI générale est activée
        if hasattr(self, 'llm_ip_input'): self.llm_ip_input.setEnabled(enabled); self.llm_port_input.setEnabled(enabled)
        # Gère les éléments dépendant du projet chargé et/ou LLM
        self.ai_send_button.setEnabled(enabled and is_project_loaded and llm_ok)
        self.run_script_button.setEnabled(enabled and is_project_loaded)
        self.save_code_button.setEnabled(enabled and is_project_loaded)
        self.ai_input_text.setEnabled(enabled and is_project_loaded and llm_ok)
        self.code_editor_text.setReadOnly(not enabled) # ReadOnly quand désactivé (busy)
        # Gère le bouton Delete
        if self.delete_project_button:
             selected_item = self.project_list_widget.currentItem(); is_valid_selection = False
             if selected_item: item_is_selectable = bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable); is_valid_selection = item_is_selectable
             # Actif seulement si UI générale activée, projet chargé ET item valide sélectionné
             self.delete_project_button.setEnabled(enabled and is_project_loaded and is_valid_selection)
        # Gestion curseur et message "Ready"
        if not enabled:
            if not QApplication.overrideCursor(): QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            if QApplication.overrideCursor(): QApplication.restoreOverrideCursor()
            # Affiche "Ready" seulement si on revient à IDLE (pas entre les tâches chaînées)
            # et que _on_thread_finished a bien remis la phase à IDLE
            if self._current_task_phase == TASK_IDLE:
                status_suffix = f"(LLM: {'Connected' if llm_ok else 'Disconnected'})"; self.log_to_ai_output(f"--- Ready {status_suffix} ---")

    def append_code_fragment(self, fragment: str): # Original
        cursor = self.code_editor_text.textCursor(); cursor.movePosition(cursor.MoveOperation.End); self.code_editor_text.setTextCursor(cursor); self.code_editor_text.insertPlainText(fragment)

    def _cleanup_code_editor(self): # Original
        print("Attempting simple code editor cleanup..."); full_code = self.code_editor_text.toPlainText(); original_stripped = full_code.strip();
        if not original_stripped: print("Editor empty, no cleanup."); return
        start_pos_content = 0; cleaned_from_start = False; start_marker_py = "```python"; start_marker_plain = "```"; lower_stripped = original_stripped.lower()
        if lower_stripped.startswith(start_marker_py): idx = len(start_marker_py); end_of_marker_line = original_stripped.find('\n', idx);
        if lower_stripped.startswith(start_marker_py) and end_of_marker_line != -1: start_pos_content = end_of_marker_line + 1; cleaned_from_start = True; print(f"Found '{start_marker_py}'.")
        elif original_stripped.startswith(start_marker_plain): idx = len(start_marker_plain); end_of_marker_line = original_stripped.find('\n', idx);
        if not cleaned_from_start and original_stripped.startswith(start_marker_plain) and end_of_marker_line != -1: start_pos_content = end_of_marker_line + 1; cleaned_from_start = True; print(f"Found '{start_marker_plain}'.")
        end_pos_content = len(original_stripped); cleaned_from_end = False; end_marker = "```"; idx_end = original_stripped.rfind(end_marker, start_pos_content);
        if idx_end != -1 and (original_stripped.endswith(end_marker) or original_stripped[idx_end + len(end_marker):].strip() == ""): end_pos_content = idx_end; cleaned_from_end = True; print(f"Found '{end_marker}' near end.")
        if cleaned_from_start or cleaned_from_end: extracted_code = original_stripped[start_pos_content:end_pos_content]; final_cleaned_code = extracted_code.strip();
        if final_cleaned_code and final_cleaned_code != original_stripped: print(f"Code cleaned."); self.code_editor_text.setPlainText(final_cleaned_code); self.log_to_ai_output("--- Cleaned fences (simple). ---")
        elif not final_cleaned_code and (cleaned_from_start or cleaned_from_end): print("Clean resulted in empty code."); self.code_editor_text.clear(); self.log_to_ai_output("--- Cleaned fences (empty). ---")
        else: print("Code unchanged after cleanup.")

    # --- MODIFIÉ : handle_worker_result (stocke next_phase) ---
    def handle_worker_result(self, task_type: str, result: Any):
        # Stocke la phase logique suivante pour _on_thread_finished
        self._next_logical_phase_after_result = TASK_IDLE
        print(f"[GUI handle_worker_result] Received result for task '{task_type}'. Current phase: '{self._current_task_phase}'. Result type: {type(result)}")
        if task_type != self._current_task_phase: print(f"WARNING: Result type '{task_type}' differs from phase '{self._current_task_phase}'. Ignoring."); return

        error_occurred = isinstance(result, Exception)
        next_phase = TASK_IDLE # Sera modifié ci-dessous si nécessaire

        try:
            if task_type == TASK_IDENTIFY_DEPS:
                if error_occurred: self.log_to_ai_output(f"Error ID deps: {result}"); print(traceback.format_exc())
                else:
                    self._identified_dependencies = result if isinstance(result, list) else []; self.log_to_ai_output(f"Deps ID'd: {self._identified_dependencies or 'None needed'}")
                    valid_deps = [d for d in self._identified_dependencies if isinstance(d, str) and d and not d.startswith("ERROR:")]; self._pending_install_deps = valid_deps
                    if valid_deps: next_phase = TASK_INSTALL_DEPS; self.log_to_ai_output(f"-> Next: Install dependencies: {valid_deps}")
                    else: next_phase = TASK_GENERATE_CODE; self.log_to_ai_output("-> Next: Generate code (no deps)")
            elif task_type == TASK_INSTALL_DEPS:
                 install_successful = not error_occurred and result is True
                 if install_successful: next_phase = TASK_GENERATE_CODE; self.log_to_ai_output("Install OK. Next: Generate code"); self._pending_install_deps = []
                 else: self.log_to_ai_output(f"Error installing deps: {result}");
                 if error_occurred: traceback.print_exc()
                 # Reste idle si échec
            elif task_type == TASK_GENERATE_CODE:
                 if error_occurred: self.log_to_ai_output(f"Error generating/correcting code: {result}"); print(traceback.format_exc())
                 else: self.log_to_ai_output("Code stream finished. Cleaning..."); self._cleanup_code_editor(); self.log_to_ai_output("Code generated/corrected. Verifying..."); next_phase = TASK_RUN_SCRIPT; # self.log_to_ai_output("--- Next step determined: Run script to verify ---") # Log moins utile ici
            elif task_type == TASK_RUN_SCRIPT:
                 self.log_to_console(f"--- Script execution task finished ---"); execution_successful = False
                 if isinstance(result, subprocess.CompletedProcess):
                     output_str = f"--- Script Output --- (Exit Code: {result.returncode})\n"; stdout_clean = result.stdout.strip() if result.stdout else ""; stderr_clean = result.stderr.strip() if result.stderr else ""
                     output_str += f"[STDOUT]:\n{stdout_clean}\n" if stdout_clean else "[STDOUT]: (No output)\n"; output_str += f"[STDERR]:\n{stderr_clean}\n" if stderr_clean else "[STDERR]: (No output)\n"; output_str += "---------------------"; self.log_to_console(output_str)
                     if result.returncode == 0: execution_successful = True; self.log_to_ai_output("--- Script executed successfully! Process complete. ---"); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; next_phase = TASK_IDLE
                     elif self._correction_attempts < self.MAX_CORRECTION_ATTEMPTS: self._correction_attempts += 1; self.log_to_ai_output(f"--- Script error. Attempting correction ({self._correction_attempts}/{self.MAX_CORRECTION_ATTEMPTS})... ---"); self._code_to_correct = self.code_editor_text.toPlainText(); self._last_execution_error = stderr_clean if stderr_clean else f"Script failed (Exit Code: {result.returncode})"; next_phase = TASK_GENERATE_CODE; # self.log_to_ai_output("--- Next step determined: Correct code ---") # Log moins utile
                     else: self.log_to_ai_output(f"--- MAX CORRECTION ATTEMPTS ({self.MAX_CORRECTION_ATTEMPTS}) REACHED. Aborting. ---"); self.log_to_console(f"ERROR: Script failed after {self.MAX_CORRECTION_ATTEMPTS} attempts."); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; next_phase = TASK_IDLE
                 elif error_occurred: self.log_to_console(f"--- ERROR running script task: {result} ---"); traceback.print_exc(); next_phase = TASK_IDLE
                 else: self.log_to_console(f"--- Unknown result for run_script: {type(result)} ---"); next_phase = TASK_IDLE
            elif task_type == TASK_ATTEMPT_CONNECTION:
                 status = "Error"; color = "red"; llm_connected = False
                 if isinstance(result, bool): llm_connected = result; status = "Connected" if llm_connected else "Disconnected"; color = "green" if llm_connected else "red"; self.log_to_ai_output(f"LLM Connection Attempt: {status}")
                 elif error_occurred: status = f"Error: {result}"; color = "red"; self.log_to_ai_output(f"LLM Connection Attempt Error: {result}"); print(traceback.format_exc())
                 self.llm_status_label.setText(f"LLM Status: {status}"); self.llm_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                 next_phase = TASK_IDLE
            else: self.log_to_ai_output(f"--- Unhandled task result for task: {task_type} ---"); next_phase = TASK_IDLE
        except Exception as handler_ex: print(f"EXCEPTION in handle_worker_result: {handler_ex}"); traceback.print_exc(); self.log_to_ai_output(f"Internal error: {handler_ex}"); next_phase = TASK_IDLE
        finally:
             # Stocke la phase logique suivante pour _on_thread_finished
             self._next_logical_phase_after_result = next_phase
             print(f"Handler finished for '{task_type}'. Next logical phase stored as: '{next_phase}'")

    def start_code_generation_worker(self) -> bool:
        """Starts the worker for generating or correcting code."""
        # Vérifications initiales (projet, prompt, connexion LLM)
        if not self.current_project or not self._current_user_prompt:
            self.log_to_ai_output("Error: Cannot start code gen. Project/Prompt missing.");
            # Pas besoin de mettre TASK_IDLE ici, car on n'a pas changé de phase
            return False
        if not self.llm_client.is_available():
            self.log_to_ai_output("Error: LLM not connected.");
            QMessageBox.warning(self, "LLM Error", "LLM not connected.")
            return False

        # Détermine si c'est une correction et prépare le contexte
        is_correction = bool(self._last_execution_error and self._code_to_correct is not None)
        # Utilise le code sauvegardé pour la correction, sinon chaîne vide
        code_context = self._code_to_correct if is_correction else ""

        # --- CORRECTION : Clear l'éditeur AVANT de démarrer la génération/correction ---
        self.log_to_ai_output("--- Clearing editor before receiving new/corrected code ---")
        self.code_editor_text.clear()
        # --- FIN CORRECTION ---

        # Loggue le type d'opération
        if is_correction:
            self.log_to_ai_output(f"--- Preparing code correction (Attempt {self._correction_attempts})... ---")
        else:
            # Le clear est maintenant fait avant
            self.log_to_ai_output("--- Preparing code generation... ---")
            # self.code_editor_text.clear() # Ancienne position

        # Prépare les arguments et lance le worker
        started = self.start_worker(
            task_type=TASK_GENERATE_CODE,
            task_callable=self.llm_client.generate_code_streaming,
            user_prompt=self._current_user_prompt,
            project_name=self.current_project,
            current_code=code_context, # Envoie l'ancien code si correction
            dependencies_identified=self._identified_dependencies,
            execution_error=self._last_execution_error if is_correction else None
        )

        # Si le démarrage échoue, repasse en idle
        if not started:
            self._current_task_phase = TASK_IDLE
            # set_ui_enabled sera appelé par la suite normale si start_worker retourne False
            # ou par _on_thread_finished si besoin. On peut l'assurer ici aussi:
            self.set_ui_enabled(True)

        return started

    def log_to_console(self, message: str): # Original
        self.output_console_text.append(str(message)); self.output_console_text.verticalScrollBar().setValue(self.output_console_text.verticalScrollBar().maximum()); print(f"CONSOLE_LOG: {message}")
    def log_to_ai_output(self, message: str): # Original
        self.ai_output_text.append(str(message)); self.ai_output_text.verticalScrollBar().setValue(self.ai_output_text.verticalScrollBar().maximum()); print(f"AI_LOG: {message}")

    # --- NOUVELLE FONCTION : attempt_llm_connection ---
    def attempt_llm_connection(self): # Fonction pour IP/Port
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", f"Busy: {self._current_task_phase}"); return
        host_ip = self.llm_ip_input.text().strip(); port_str = self.llm_port_input.text().strip()
        try:
            if not host_ip: raise ValueError("IP address cannot be empty.")
            port = int(port_str);
            if not (1 <= port <= 65535): raise ValueError("Port number must be between 1 and 65535.")
        except ValueError as e: QMessageBox.warning(self, "Input Error", str(e)); return
        self.llm_status_label.setText(f"LLM: Connecting to {host_ip}:{port}..."); self.llm_status_label.setStyleSheet("color: orange;"); QApplication.processEvents()
        if not self.start_worker(task_type=TASK_ATTEMPT_CONNECTION, task_callable=self.llm_client.connect, host=host_ip, port=port):
             self.llm_status_label.setText("LLM: Connection Failed (Busy)"); self.llm_status_label.setStyleSheet("color: red; font-weight: bold;");
             if self._current_task_phase == TASK_ATTEMPT_CONNECTION: self._current_task_phase = TASK_IDLE
             self.set_ui_enabled(True)

    # --- MODIFIÉ : start_generation_process (check LLM + clear outputs) ---
    def start_generation_process(self): # Original + ajouts
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", f"Busy: {self._current_task_phase}"); return
        user_prompt = self.ai_input_text.text().strip();
        if not self.current_project: QMessageBox.warning(self, "No Project", "Select project."); return
        if not self.llm_client.is_available(): QMessageBox.warning(self, "LLM Error", "LLM not connected."); return
        if not user_prompt: QMessageBox.warning(self, "Input Needed", "Enter request."); return
        # Reset état (original)
        self._current_user_prompt = user_prompt; self._identified_dependencies = []; self._pending_install_deps = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0
        # Clear outputs
        self.ai_output_text.clear(); self.output_console_text.clear(); self.code_editor_text.clear()
        self.log_to_ai_output(f"\n>>> New Request: {user_prompt}"); self.log_to_ai_output("--- Starting: Identifying dependencies... ---");
        # Démarre ID deps (original)
        if not self.start_worker(task_type=TASK_IDENTIFY_DEPS, task_callable=self.llm_client.identify_dependencies, user_prompt=self._current_user_prompt, project_name=self.current_project):
             self.log_to_ai_output("--- Could not start ID deps (Busy?) ---")
             self.set_ui_enabled(True)

    # --- Méthodes gestion projet (originales, sauf corrections mineures) ---
    def load_project_list(self): # Original
        # Note: l'original avait un check "busy", on le garde
        if self._current_task_phase != TASK_IDLE: print("Busy, skipping project list load"); return
        self.project_list_widget.clear();
        try:
            projects = project_manager.list_projects()
            if projects: self.project_list_widget.addItems(projects); self.project_list_widget.setEnabled(True) # Active si projets trouvés
            else: self.project_list_widget.addItem("No projects found"); self.project_list_widget.setEnabled(False)
        except Exception as e: print(f"Error loading list:{e}"); self.project_list_widget.addItem("Error loading list"); self.project_list_widget.setEnabled(False)

    def load_selected_project(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]): # Original + bool fix
        is_valid_selection = False
        if current_item is not None:
             item_is_selectable = bool(current_item.flags() & Qt.ItemFlag.ItemIsSelectable)
             is_valid_text = current_item.text() not in ["No projects found", "Error loading list"]
             is_valid_selection = item_is_selectable and is_valid_text
        if self.delete_project_button: self.delete_project_button.setEnabled(is_valid_selection and self._current_task_phase == TASK_IDLE)
        if not is_valid_selection:
             if self.current_project: self.clear_project_view()
             self.set_ui_enabled(self._current_task_phase == TASK_IDLE)
             return
        project_name = current_item.text()
        if self._current_task_phase != TASK_IDLE:
             print(f"Busy ({self._current_task_phase}), cannot switch project.");
             self.project_list_widget.blockSignals(True); self.project_list_widget.setCurrentItem(previous_item); self.project_list_widget.blockSignals(False)
             QMessageBox.warning(self, "Busy", f"Cannot switch project while task '{self._current_task_phase}' is running."); return
        if self.current_project != project_name:
            self.current_project = project_name; self.setWindowTitle(f"Pythautom - {project_name}"); print(f"Loading project: {project_name}")
            self.ai_output_text.clear(); self.output_console_text.clear(); self.log_to_ai_output(f"--- Project '{project_name}' loaded ---"); self.reload_project_data();
            self._current_user_prompt = ""; self._identified_dependencies = []; self._pending_install_deps = []; self._code_to_correct=None; self._last_execution_error=None; self._correction_attempts=0; self.ai_input_text.clear()
        self.set_ui_enabled(True)

    def reload_project_data(self, update_editor=True): # Original
        if not self.current_project: return; print(f"[GUI] Reloading data for '{self.current_project}'.");
        if update_editor:
             try: code = project_manager.get_project_script_content(self.current_project); self.code_editor_text.setPlainText(code if code is not None else f"# Empty or error reading {DEFAULT_MAIN_SCRIPT}")
             except Exception as e: self.code_editor_text.setPlainText(f"# Error loading: {e}"); self.log_to_console(f"Error reload data: {e}")

    def clear_project_view(self): # Original
        print("Clearing project view...")
        self.current_project = None; self.setWindowTitle("Pythautom - AI Python Project Builder") # Titre mis à jour
        self.code_editor_text.clear(); self.ai_output_text.clear(); self.output_console_text.clear(); self.ai_input_text.clear()
        self._current_task_phase = TASK_IDLE; self._current_user_prompt = ""; self._identified_dependencies = []; self._pending_install_deps = []; self._code_to_correct=None; self._last_execution_error=None; self._correction_attempts=0
        self.set_ui_enabled(True) # Appelle avec True, set_ui_enabled gère les désactivations

    def create_new_project_dialog(self): # Original + sanitization simple
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot create project now."); return
        dialog = QDialog(self); dialog.setWindowTitle("New Project"); layout=QVBoxLayout(dialog); label=QLabel("Enter project name:"); name_input=QLineEdit(); layout.addWidget(label); layout.addWidget(name_input); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec():
            raw_name = name_input.text().strip();
            if not raw_name: QMessageBox.warning(self, "Invalid Name", "Name empty."); return
            base_name = os.path.basename(raw_name); project_name = re.sub(r'[<>:"/\\|?* ]', '_', base_name); project_name = re.sub(r'_+', '_', project_name).strip('_')
            if not project_name or project_name in ['.', '..']: QMessageBox.warning(self, "Invalid Name", f"Name invalid after sanitization: '{project_name}'"); return
            print(f"Using sanitized project name: '{project_name}'")
            try:
                if project_manager.create_project(project_name):
                    self.log_to_console(f"Project '{project_name}' created."); self.load_project_list(); items=self.project_list_widget.findItems(project_name, Qt.MatchFlag.MatchExactly); self.project_list_widget.setCurrentItem(items[0] if items else None)
                else: QMessageBox.critical(self, "Error", f"Failed create '{project_name}'. Already exists?")
            except Exception as e: QMessageBox.critical(self, "Error", f"Error creating '{project_name}': {e}"); print(traceback.format_exc())

    def confirm_delete_project(self): # Original + bool fix + UI reactivation fix
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot delete project now."); return
        selected_item = self.project_list_widget.currentItem()
        is_valid_item = False
        if selected_item: is_valid_item = bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable)
        if not selected_item or not is_valid_item: QMessageBox.warning(self, "No Project Selected", "Select a valid project to delete."); return
        project_name = selected_item.text()
        project_path_str = ""; 
        try:
            project_path_str = project_manager.get_project_path(project_name)
        except Exception:
            pass
        reply = QMessageBox.warning(self,"Confirm Deletion", f"Delete '{project_name}'?\nPath: {project_path_str}\n\nCannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            print(f"Confirmed deletion '{project_name}'."); self.log_to_ai_output(f"--- Deleting '{project_name}'... ---")
            self.set_ui_enabled(False, "Deleting project"); QApplication.processEvents(); deleted = False; error_msg = ""; e_obj=None
            try: deleted = project_manager.delete_project(project_name)
            except Exception as e: e_obj=e; print(traceback.format_exc()); error_msg = f"Error: {e}"; QMessageBox.critical(self, "Deletion Error", error_msg)
            finally: # Assure que l'UI est réactivée
                if deleted:
                    self.log_to_console(f"Project '{project_name}' deleted."); self.log_to_ai_output(f"--- Project '{project_name}' deleted. ---")
                    if self.current_project == project_name: self.clear_project_view() # clear appelle set_ui_enabled
                    self.load_project_list()
                    if self.current_project != project_name: self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True) # Réactive si vue non clearée
                else:
                 if not error_msg: error_msg = f"Failed delete '{project_name}'. Check logs."
                 self.log_to_console(error_msg); self.log_to_ai_output(f"--- ERROR deleting '{project_name}'. ---")
                 if not e_obj: QMessageBox.critical(self, "Deletion Error", error_msg)
                 self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True) # Réactive UI après erreur
        else: print(f"Deletion '{project_name}' cancelled."); self.log_to_ai_output("--- Project deletion cancelled. ---")

    def save_current_code(self): # Original + strip()
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot save code now."); return
        if not self.current_project: QMessageBox.warning(self, "No Project", "Select project."); return
        code = self.code_editor_text.toPlainText(); print(f"[GUI] Save '{self.current_project}'. Len: {len(code)}")
        if not code.strip():
             reply = QMessageBox.question(self,'Confirm Empty','Save empty file?', QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.No: self.log_to_console("Empty save cancelled."); return
        try:
            if project_manager.save_project_script_content(self.current_project, code): self.log_to_console(f"Code saved.")
            else: QMessageBox.critical(self, "Save Error", f"Failed save. Check logs.")
        except Exception as e: print(f"EXCEPTION save: {e}"); traceback.print_exc(); QMessageBox.critical(self, "Save Error", f"Error: {e}")

    def run_current_project_script(self): # Original + venv check + clear output + script_name arg + gestion échec start_worker
        """Runs the project script, ensuring UI is re-enabled if worker fails to start."""
        # Vérifications initiales (inchangées)
        if self._current_task_phase != TASK_IDLE:
            # Si on essaie de run manuellement alors qu'une tâche tourne
            QMessageBox.warning(self, "Busy", "Cannot run script while another task is running.")
            return
        if not self.current_project:
            QMessageBox.warning(self, "No Project", "Select project.")
            return

        script_name = DEFAULT_MAIN_SCRIPT
        try:
            project_path = project_manager.get_project_path(self.current_project)
            script_file = os.path.join(project_path, script_name)
            if not os.path.isdir(project_path): msg = f"Dir not found: '{project_path}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
            if not os.path.exists(script_file): msg = f"Script not found: '{script_name}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
            # Vérifie/Crée le venv avant de tenter l'exécution
            if not utils.ensure_project_venv(project_path):
                 msg = f"Failed ensure venv '{self.current_project}'."; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
        except Exception as e:
            msg=f"Error preparing to run script: {e}"; print(msg); traceback.print_exc(); QMessageBox.critical(self, "Run Error", msg); return

        # Clear output avant run (si appelé manuellement, sinon déjà fait)
        # self.output_console_text.clear() # Optionnel: clear systématique ?
        self.log_to_console(f"\n--- Attempting to run script: {self.current_project}/{script_name} ---")

        # --- Tentative de démarrage du worker ---
        started_successfully = self.start_worker(
            task_type=TASK_RUN_SCRIPT,
            task_callable=utils.run_project_script,
            project_path=project_path,
            script_name=script_name
        )

        # --- CORRECTION : Gérer l'échec de start_worker ---
        if not started_successfully:
            self.log_to_console("--- Could not start script execution (Busy? Task overlap?). Reverting to Idle. ---")
            # Si start_worker a échoué, l'UI est restée désactivée. Il faut la réactiver.
            # Remet explicitement la phase à IDLE car la tâche n'a pas démarré.
            self._current_task_phase = TASK_IDLE
            self.set_ui_enabled(True)
        # --- FIN CORRECTION ---
        # Si started_successfully est True, l'UI reste désactivée et le worker s'exécute.

    def closeEvent(self, event): # Original + cancel worker
        if self._current_task_phase != TASK_IDLE: reply = QMessageBox.question(self, 'Confirm Exit', f'Task ({self._current_task_phase}) running. Exit?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        else: reply = QMessageBox.question(self, 'Confirm Exit', 'Sure?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            print("Closing...");
            if self.thread and self.thread.isRunning() and self.worker: # Check if worker exists before cancelling
                 print("Attempting to cancel running task...")
                 self.worker.cancel()
            event.accept()
        else: print("Close ignored."); event.ignore()
