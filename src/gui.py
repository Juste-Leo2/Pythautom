# src/gui.py
# VERSION AVEC AUTO-CORRECTION + BOUTON DELETE

import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QTextEdit, QLineEdit, QLabel, QSplitter, QMessageBox,
    QDialog, QDialogButtonBox, QApplication, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
import json
import re # Pour cleanup et sanitization
import traceback
import os
import subprocess # Pour type hinting
from typing import List, Any, Optional, Dict, Callable

# Importer nos modules locaux
from . import project_manager
from . import utils
from .llm_interaction import LLMClient
from .project_manager import DEFAULT_MAIN_SCRIPT

# --- CONSTANTES POUR LES TYPES DE TÂCHES ---
TASK_IDLE = "idle"
TASK_IDENTIFY_DEPS = "identify_deps"
TASK_INSTALL_DEPS = "install_deps"
TASK_GENERATE_CODE = "generate_code"
TASK_RUN_SCRIPT = "run_script"
TASK_CHECK_CONNECTION = "check_connection"
# --- FIN CONSTANTES ---


# --- Syntax Highlighting (Inchangé) ---
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
        if len(text) > 1500: return
        for p, f in self.highlightingRules:
            try:
                for m in re.finditer(p, text):
                     s, e = m.span(); self.setFormat(s, e - s, f)
            except Exception: pass
        self.setCurrentBlockState(0)


# --- Worker Thread (Inchangé, émet (str, object)) ---
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
        self.progress.emit(f"Starting: {self.task_type}..."); self._is_cancelled = False; task_result: Any = None
        try:
            if self._is_cancelled: raise InterruptedError("Cancelled before execution")
            if self.task_type == TASK_IDENTIFY_DEPS: task_result = self.task_callable(*self.args, **self.kwargs); msg = "Dependency ID finished."
            elif self.task_type == TASK_INSTALL_DEPS: task_result = self.task_callable(*self.args, **self.kwargs); msg = f"Install {'OK' if task_result else 'failed'}."
            elif self.task_type == TASK_GENERATE_CODE: actual_kwargs = self.kwargs.copy(); actual_kwargs.setdefault("fragment_callback", self.code_fragment_received.emit); self.task_callable(*self.args, **actual_kwargs); task_result = True; msg = "Code generation/correction finished."
            elif self.task_type == TASK_RUN_SCRIPT: task_result = self.task_callable(*self.args, **self.kwargs); msg = "Script execution finished."
            elif self.task_type == TASK_CHECK_CONNECTION: task_result = self.task_callable(*self.args, **self.kwargs); msg = "Connection check finished."
            else: raise NotImplementedError(f"Unknown task type {self.task_type}")
            if not self._is_cancelled: self.progress.emit(msg); self.result.emit(self.task_type, task_result)
        except InterruptedError as ie: print(f"Task '{self.task_type}' interrupted: {ie}"); self.progress.emit(f"Task '{self.task_type}' cancelled.")
        except Exception as e:
            if not self._is_cancelled: error_msg = f"Error in worker task '{self.task_type}': {e}"; print(f"EXCEPTION:\n{traceback.format_exc()}"); self.progress.emit(error_msg); self.result.emit(self.task_type, e)
            else: print(f"Exception ({e}) but task was cancelled.")
        finally: print(f"[Worker {id(self)}] FINISHED task '{self.task_type}'. Emitting finished (Cancelled={self._is_cancelled})."); self.finished.emit()


# --- Fenêtre Principale ---
class MainWindow(QMainWindow):
    _current_task_phase: str = TASK_IDLE
    _current_user_prompt: str = ""
    _identified_dependencies: List[str] = []
    _pending_install_deps: List[str] = []
    _code_to_correct: Optional[str] = None
    _last_execution_error: Optional[str] = None
    _correction_attempts: int = 0
    MAX_CORRECTION_ATTEMPTS: int = 2

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Python Project Builder (v2.7 - Delete Project)") # Version updated
        self.setGeometry(100, 100, 1200, 750)
        self.current_project: Optional[str] = None; self.llm_client = LLMClient(); self.thread: Optional[QThread] = None; self.worker: Optional[Worker] = None
        self.delete_project_button: Optional[QPushButton] = None # Référence ajoutée
        self.setup_ui(); self.load_project_list(); self.check_llm_connection()

    def setup_ui(self):
        """Configure l'interface utilisateur."""
        main_widget=QWidget(); self.setCentralWidget(main_widget); main_layout=QHBoxLayout(main_widget)
        # --- Left Panel ---
        left_panel=QWidget(); left_layout=QVBoxLayout(left_panel); left_panel.setFixedWidth(250)
        project_label=QLabel("Projects:"); self.project_list_widget=QListWidget(); self.project_list_widget.currentItemChanged.connect(self.load_selected_project)
        left_layout.addWidget(project_label); left_layout.addWidget(self.project_list_widget)
        # --- Layout pour les boutons de projet ---
        project_button_layout=QHBoxLayout()
        self.new_project_button=QPushButton("New Project"); self.new_project_button.clicked.connect(self.create_new_project_dialog); project_button_layout.addWidget(self.new_project_button)
        # --- AJOUT BOUTON DELETE ---
        self.delete_project_button = QPushButton("Delete Project"); self.delete_project_button.clicked.connect(self.confirm_delete_project); self.delete_project_button.setEnabled(False); project_button_layout.addWidget(self.delete_project_button)
        # --- FIN AJOUT ---
        left_layout.addLayout(project_button_layout) # Ajouter le layout
        # Reste du Left Panel
        self.llm_status_label=QLabel("LLM Status: Unknown"); left_layout.addWidget(self.llm_status_label); self.llm_reconnect_button=QPushButton("Check/Reconnect LLM"); self.llm_reconnect_button.clicked.connect(self.check_llm_connection); left_layout.addWidget(self.llm_reconnect_button); left_layout.addStretch(); main_layout.addWidget(left_panel)
        # --- Right Panel (inchangé) ---
        right_splitter = QSplitter(Qt.Orientation.Vertical); interaction_code_widget=QWidget(); interaction_code_layout=QHBoxLayout(interaction_code_widget); interaction_area=QWidget(); interaction_layout=QVBoxLayout(interaction_area); interaction_label=QLabel("AI Interaction / Status:"); self.ai_output_text=QTextEdit(); self.ai_output_text.setReadOnly(True); self.ai_output_text.setFont(QFont("Arial", 9)); self.ai_input_text=QLineEdit(); self.ai_input_text.setPlaceholderText("Describe what you want to build or modify..."); self.ai_send_button=QPushButton("Generate / Modify Code"); self.ai_send_button.clicked.connect(self.start_generation_process); self.ai_send_button.setEnabled(False); interaction_layout.addWidget(interaction_label); interaction_layout.addWidget(self.ai_output_text, 1); interaction_layout.addWidget(self.ai_input_text); interaction_layout.addWidget(self.ai_send_button); interaction_area.setMinimumWidth(350); code_area=QWidget(); code_layout=QVBoxLayout(code_area); code_label=QLabel("Project Code (main.py):"); self.code_editor_text=QTextEdit(); self.code_editor_text.setFont(QFont("Courier New", 10)); self.code_highlighter = PythonHighlighter(self.code_editor_text.document()); self.save_code_button=QPushButton("Save Code"); self.save_code_button.clicked.connect(self.save_current_code); self.save_code_button.setEnabled(False); code_layout.addWidget(code_label); code_layout.addWidget(self.code_editor_text, 1); code_layout.addWidget(self.save_code_button); interaction_code_layout.addWidget(interaction_area); interaction_code_layout.addWidget(code_area, 1); right_splitter.addWidget(interaction_code_widget); output_widget=QWidget(); output_layout=QVBoxLayout(output_widget); output_label=QLabel("Execution Output / Logs:"); self.output_console_text=QTextEdit(); self.output_console_text.setReadOnly(True); self.output_console_text.setFont(QFont("Courier New", 9)); self.run_script_button=QPushButton("Run Project Script (main.py)"); self.run_script_button.clicked.connect(self.run_current_project_script); self.run_script_button.setEnabled(False); output_layout.addWidget(output_label); output_layout.addWidget(self.output_console_text, 1); output_layout.addWidget(self.run_script_button); right_splitter.addWidget(output_widget); right_splitter.setSizes([450, 300]); main_layout.addWidget(right_splitter, 1)

    # Utiliser les constantes dans start_worker
    def start_worker(self, task_type: str, task_callable: Callable, *args, **kwargs) -> bool:
        if self.thread is not None and self.thread.isRunning(): print(f"Warning: Task '{task_type}' requested, but previous thread active."); QMessageBox.warning(self, "Busy", "Task already running."); return False
        self._current_task_phase = task_type; self.set_ui_enabled(False, task_type)
        self.thread = QThread(); self.thread.setObjectName(f"WorkerThread_{task_type}_{id(self.thread)}")
        self.worker = Worker(task_type, task_callable, *args, **kwargs); self.worker.moveToThread(self.thread)
        self.worker.progress.connect(self.log_to_ai_output); self.worker.result.connect(self.handle_worker_result); self.worker.code_fragment_received.connect(self.append_code_fragment)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.on_worker_task_completed); self.thread.finished.connect(self.on_thread_really_finished)
        self.thread.started.connect(self.worker.run); self.thread.start()
        print(f"Worker started for task: {task_type} on thread {self.thread.objectName()}"); return True

    def on_worker_task_completed(self): print(f"Worker task completed signal received (Phase: {self._current_task_phase}).")

    # Utiliser les constantes dans on_thread_really_finished
    def on_thread_really_finished(self):
        sender_obj = self.sender(); thread_name = sender_obj.objectName() if sender_obj else "N/A"
        phase_when_thread_finished = self._current_task_phase; print(f"Thread '{thread_name}' finished. Phase is now '{phase_when_thread_finished}'. Cleaning up.")
        self.thread = None; self.worker = None; print("GUI refs cleaned.")
        # --- Logique d'enchaînement ou de fin ---
        if phase_when_thread_finished == TASK_INSTALL_DEPS:
            print("Attempting next task: install_deps") # Log technique, la phase est 'install_deps'
            if self.current_project and self._pending_install_deps:
                project_path = project_manager.get_project_path(self.current_project)
                if not self.start_worker(task_type=TASK_INSTALL_DEPS, task_callable=utils.install_project_dependencies, project_path=project_path, dependencies=self._pending_install_deps):
                     self.log_to_ai_output("! Error starting install worker."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
            else: self.log_to_ai_output("! Cannot start install, info missing."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
        elif phase_when_thread_finished == TASK_GENERATE_CODE:
            print("Attempting next task: generate_code / correct_code")
            if not self.start_code_generation_worker():
                 self.log_to_ai_output("! Error starting generation/correction worker."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
        elif phase_when_thread_finished == TASK_RUN_SCRIPT:
             # La phase logique après run_script est déterminée par handle_result. Si c'est generate_code (correction), on lance. Sinon on est idle.
            print(f"Thread finished after run_script. Next logical phase stored is: {self._current_task_phase}")
            if self._current_task_phase == TASK_GENERATE_CODE: # Doit-on corriger ?
                 if not self.start_code_generation_worker():
                     self.log_to_ai_output("! Error starting correction worker."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
            else: # Succès ou limite atteinte -> idle
                 self._current_task_phase = TASK_IDLE # Assurer idle
                 self.set_ui_enabled(True) # Activer l'UI
        elif phase_when_thread_finished == TASK_IDLE:
             print("Process is idle."); self.set_ui_enabled(True)
        else: # check_connection ou imprévu
             print(f"Phase '{phase_when_thread_finished}' ends here, assuming idle."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

    # --- MODIFIER set_ui_enabled POUR INCLURE LE BOUTON DELETE ---
    def set_ui_enabled(self, enabled: bool, current_task: Optional[str] = None):
        """Active/Désactive les éléments UI pertinents."""
        is_project_loaded = self.current_project is not None; llm_ok = self.llm_client.is_available();
        self.ai_send_button.setEnabled(enabled and is_project_loaded and llm_ok); self.run_script_button.setEnabled(enabled and is_project_loaded); self.save_code_button.setEnabled(enabled and is_project_loaded); self.new_project_button.setEnabled(enabled); self.project_list_widget.setEnabled(enabled); self.llm_reconnect_button.setEnabled(enabled); self.ai_input_text.setEnabled(enabled);
        # Gérer le bouton Delete
        if self.delete_project_button:
             self.delete_project_button.setEnabled(enabled and is_project_loaded)
        # Gestion curseur
        if not enabled:
            if not QApplication.overrideCursor(): QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            if QApplication.overrideCursor(): QApplication.restoreOverrideCursor()
            if self._current_task_phase == TASK_IDLE: self.log_to_ai_output("--- Ready ---")

    def append_code_fragment(self, fragment: str): # ... (inchangé) ...
        cursor = self.code_editor_text.textCursor(); cursor.movePosition(cursor.MoveOperation.End); self.code_editor_text.setTextCursor(cursor); self.code_editor_text.insertPlainText(fragment)

    def _cleanup_code_editor(self): # ... (inchangé - version simple) ...
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

    # Utiliser les constantes dans handle_worker_result
    # @pyqtSlot(str, object)
    def handle_worker_result(self, task_type: str, result: Any):
        print(f"[GUI handle_worker_result] Received result for emitted task_type '{task_type}'. Result type: {type(result)}")
        if task_type != self._current_task_phase: print(f"WARNING: Result type '{task_type}' differs from phase '{self._current_task_phase}'.")
        error_occurred = isinstance(result, Exception); next_phase = TASK_IDLE
        try:
            if task_type == TASK_IDENTIFY_DEPS:
                if error_occurred: self.log_to_ai_output(f"Error ID deps: {result}"); traceback.print_exc()
                else:
                    self._identified_dependencies = result if isinstance(result, list) else []; self.log_to_ai_output(f"Deps ID'd: {self._identified_dependencies or 'None'}")
                    valid_deps = [d for d in self._identified_dependencies if d and isinstance(d, str) and not d.startswith("ERROR:")]; self._pending_install_deps = valid_deps
                    if valid_deps: next_phase = TASK_INSTALL_DEPS; self.log_to_ai_output(f"Next: Install {valid_deps}")
                    else: next_phase = TASK_GENERATE_CODE; self.log_to_ai_output("Next: Generate code (no deps)")
            elif task_type == TASK_INSTALL_DEPS:
                if error_occurred or not result: self.log_to_ai_output(f"Error installing deps: {result}");
                if error_occurred: traceback.print_exc()
                else: next_phase = TASK_GENERATE_CODE; self.log_to_ai_output("Install OK. Next: Generate code"); self._pending_install_deps = []
            elif task_type == TASK_GENERATE_CODE:
                 if error_occurred: self.log_to_ai_output(f"Error generating/correcting code: {result}");
                 if error_occurred: traceback.print_exc()
                 else: self.log_to_ai_output("Code stream finished. Cleaning..."); self._cleanup_code_editor(); self.log_to_ai_output("Code generated/corrected. Verifying...")
                 next_phase = TASK_RUN_SCRIPT # <- Exécuter pour vérifier
                 self.log_to_ai_output("--- Next step determined: Run script to verify ---")
            elif task_type == TASK_RUN_SCRIPT:
                 self.log_to_console(f"--- Script execution task finished ---")
                 execution_successful = False
                 if isinstance(result, subprocess.CompletedProcess):
                     output_str = f"--- Script Output --- (Exit Code: {result.returncode})\n"; stdout_clean = result.stdout.strip() if result.stdout else ""; stderr_clean = result.stderr.strip() if result.stderr else ""
                     if stdout_clean: output_str += "[STDOUT]:\n" + stdout_clean + "\n"; 
                     else: output_str += "[STDOUT]: (No output)\n"
                     if stderr_clean: output_str += "[STDERR]:\n" + stderr_clean + "\n"; 
                     else: output_str += "[STDERR]: (No output)\n"
                     output_str += "---------------------"; self.log_to_console(output_str)
                     if result.returncode == 0:
                         execution_successful = True; self.log_to_ai_output("--- Script executed successfully! Process complete. ---"); self._correction_attempts = 0; next_phase = TASK_IDLE
                     elif self._correction_attempts < self.MAX_CORRECTION_ATTEMPTS:
                          self._correction_attempts += 1; self.log_to_ai_output(f"--- Script error. Attempting correction ({self._correction_attempts}/{self.MAX_CORRECTION_ATTEMPTS})... ---")
                          self._code_to_correct = self.code_editor_text.toPlainText(); self._last_execution_error = stderr_clean if stderr_clean else f"Script failed (Exit Code: {result.returncode})"
                          next_phase = TASK_GENERATE_CODE; self.log_to_ai_output("--- Next step determined: Correct code ---")
                     else: # Limite tentatives
                          self.log_to_ai_output(f"--- MAX CORRECTION ATTEMPTS ({self.MAX_CORRECTION_ATTEMPTS}) REACHED. Aborting. ---"); self.log_to_console(f"ERROR: Script failed after {self.MAX_CORRECTION_ATTEMPTS} attempts."); next_phase = TASK_IDLE
                 elif error_occurred: self.log_to_console(f"--- ERROR running script task: {result} ---"); traceback.print_exc(); next_phase = TASK_IDLE
                 else: self.log_to_console(f"--- Unknown result for run_script: {type(result)} ---"); next_phase = TASK_IDLE
            elif task_type == TASK_CHECK_CONNECTION:
                 status = "Error"; color = "red";
                 if isinstance(result, bool): status = "Connected" if result else "Disconnected"; color = "green" if result else "red"; self.log_to_ai_output(f"LLM Check: {status}")
                 elif error_occurred: status = f"Error: {result}"; color = "red"; self.log_to_ai_output(f"LLM Check Error: {result}"); traceback.print_exc()
                 self.llm_status_label.setText(f"LLM Status: {status}"); self.llm_status_label.setStyleSheet(f"color: {color};"); next_phase = TASK_IDLE
            else: self.log_to_ai_output(f"--- Unhandled task result for task: {task_type} ---"); next_phase = TASK_IDLE
        except Exception as handler_ex: print(f"EXCEPTION in handle_worker_result: {handler_ex}"); traceback.print_exc(); self.log_to_ai_output(f"Internal error: {handler_ex}"); next_phase = TASK_IDLE
        finally: self._current_task_phase = next_phase; print(f"Next logical phase set to: {self._current_task_phase}")


    # Utiliser les constantes dans start_code_generation_worker
    def start_code_generation_worker(self) -> bool:
        if not self.current_project or not self._current_user_prompt: self.log_to_ai_output("Error: Cannot start code gen."); self._current_task_phase = TASK_IDLE; return False
        is_correction = bool(self._last_execution_error); code_context = self._code_to_correct if is_correction else ""
        if is_correction: self.log_to_ai_output(f"--- Preparing code correction (Attempt {self._correction_attempts})... ---")
        else: self.log_to_ai_output("--- Preparing code generation... ---")
        self.code_editor_text.clear()
        # Lance la tâche de génération/correction
        started = self.start_worker(task_type=TASK_GENERATE_CODE, task_callable=self.llm_client.generate_code_streaming, user_prompt=self._current_user_prompt, project_name=self.current_project, current_code=code_context, dependencies_identified=self._identified_dependencies, execution_error=self._last_execution_error)
        # Réinitialiser les infos de correction APRÈS avoir lancé la tâche
        if started: self._code_to_correct = None; self._last_execution_error = None
        elif not started: self._current_task_phase = TASK_IDLE # Reset si échec démarrage
        return started

    def log_to_console(self, message: str): # ... (inchangé) ...
        self.output_console_text.append(str(message)); self.output_console_text.verticalScrollBar().setValue(self.output_console_text.verticalScrollBar().maximum()); print(f"CONSOLE: {message}")
    def log_to_ai_output(self, message: str): # ... (inchangé) ...
        self.ai_output_text.append(str(message)); self.ai_output_text.verticalScrollBar().setValue(self.ai_output_text.verticalScrollBar().maximum()); print(f"AI_LOG: {message}")

    # Utiliser les constantes dans check_llm_connection
    def check_llm_connection(self):
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", f"Busy: {self._current_task_phase}"); return
        self.llm_status_label.setText("LLM: Checking..."); self.llm_status_label.setStyleSheet("color: orange;"); QApplication.processEvents()
        if not self.start_worker(task_type=TASK_CHECK_CONNECTION, task_callable=self.llm_client.check_connection):
             self.llm_status_label.setText("LLM: Check Failed (Busy)"); self.llm_status_label.setStyleSheet("color: red;")

    # Utiliser les constantes dans start_generation_process
    def start_generation_process(self):
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", f"Busy: {self._current_task_phase}"); return
        user_prompt = self.ai_input_text.text().strip();
        if not self.current_project: QMessageBox.warning(self, "No Project", "Select project."); return
        if not self.llm_client.is_available(): QMessageBox.warning(self, "LLM Error", "LLM not connected."); return
        if not user_prompt: QMessageBox.warning(self, "Input Needed", "Enter request."); return
        # --- RESET CORRECTION STATE ---
        self._current_user_prompt = user_prompt; self._identified_dependencies = []; self._pending_install_deps = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0
        # ----------------------------
        self.log_to_ai_output(f"\n>>> User Request: {user_prompt}"); self.log_to_ai_output("--- Starting: Identifying dependencies... ---"); self.ai_input_text.clear()
        if not self.start_worker(task_type=TASK_IDENTIFY_DEPS, task_callable=self.llm_client.identify_dependencies, user_prompt=self._current_user_prompt, project_name=self.current_project):
             self.log_to_ai_output("--- Could not start ID deps (Busy?) ---")


    # --- Méthodes de gestion de projet (avec check 'idle') ---
    def load_project_list(self):
        if self._current_task_phase != TASK_IDLE: print("Busy, skipping project list load"); return
        self.project_list_widget.clear();
        try: projects = project_manager.list_projects(); self.project_list_widget.addItems(projects if projects else ["No projects found"])
        except Exception as e: print(f"Error loading list:{e}"); self.project_list_widget.addItem("Error loading list")

    # --- MODIFIER load_selected_project POUR GÉRER DELETE BUTTON ---
    def load_selected_project(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        is_valid_selection = current_item is not None and (current_item.flags() & Qt.ItemFlag.ItemIsSelectable)
        # Activer/désactiver le bouton delete en fonction de la sélection et de l'état idle
        if self.delete_project_button:
            self.delete_project_button.setEnabled(is_valid_selection and self._current_task_phase == TASK_IDLE)

        if not is_valid_selection:
             if self.current_project: self.clear_project_view() # Nettoyer si on désélectionne
             return

        project_name = current_item.text()
        if self._current_task_phase != TASK_IDLE: # Vérifier si occupé AVANT de charger
             print(f"Busy ({self._current_task_phase}), cannot switch project.");
             self.project_list_widget.setCurrentItem(previous_item) # Revenir en arrière
             return

        # Charger le projet
        self.current_project = project_name; self.setWindowTitle(f"AI Builder - {project_name}"); print(f"Loading project: {project_name}")
        self.ai_output_text.clear(); self.output_console_text.clear(); self.log_to_ai_output(f"--- Project '{project_name}' loaded ---"); self.reload_project_data(); self.set_ui_enabled(True)
        # Assurer activation bouton delete (redondant mais sûr)
        if self.delete_project_button: self.delete_project_button.setEnabled(True)

    def reload_project_data(self, update_editor=True):
        if self._current_task_phase != TASK_IDLE: print("Busy, skipping reload"); return
        if not self.current_project: return; print(f"[GUI] Reloading data for '{self.current_project}'.");
        if update_editor: code = project_manager.get_project_script_content(self.current_project); self.code_editor_text.setPlainText(code if code else f"# Empty {DEFAULT_MAIN_SCRIPT}")

    # --- MODIFIER clear_project_view POUR GÉRER DELETE BUTTON ---
    def clear_project_view(self):
        # if self._current_task_phase != TASK_IDLE: print("Busy, skipping clear view"); return # Check non nécessaire ici car appelé quand idle ou après delete
        print("Clearing project view...")
        self.current_project = None; self.setWindowTitle("AI Builder"); self.code_editor_text.clear(); self.ai_output_text.clear(); self.output_console_text.clear(); self.ai_input_text.clear()
        self._current_task_phase = TASK_IDLE; self._current_user_prompt = ""; self._identified_dependencies = []; self._pending_install_deps = []; self._code_to_correct=None; self._last_execution_error=None; self._correction_attempts=0
        self.set_ui_enabled(False) # Désactiver les boutons projet
        # Assurer que le bouton delete est désactivé
        if self.delete_project_button: self.delete_project_button.setEnabled(False)


    def create_new_project_dialog(self):
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot create project now."); return
        dialog = QDialog(self); dialog.setWindowTitle("New Project"); layout=QVBoxLayout(dialog); label=QLabel("Enter project name:"); name_input=QLineEdit(); layout.addWidget(label); layout.addWidget(name_input); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec():
            raw_name = name_input.text().strip();
            if not raw_name: QMessageBox.warning(self, "Invalid Name", "Name empty."); return
            base_name = os.path.basename(raw_name); project_name = re.sub(r'[<>:"/\\|?* ]', '_', base_name);
            if not project_name: QMessageBox.warning(self, "Invalid Name", "Name invalid."); return
            print(f"Sanitized project name: '{project_name}'")
            if project_manager.create_project(project_name): self.log_to_console(f"Project '{project_name}' created."); self.load_project_list(); items=self.project_list_widget.findItems(project_name, Qt.MatchFlag.MatchExactly); self.project_list_widget.setCurrentItem(items[0] if items else None)
            else: QMessageBox.critical(self, "Error", f"Failed create '{project_name}'. Check logs.")


    def confirm_delete_project(self):
        """Asks confirmation and deletes the selected project."""
        if self._current_task_phase != TASK_IDLE:
            QMessageBox.warning(self, "Busy", "Cannot delete project while a task is running.")
            return

        selected_item = self.project_list_widget.currentItem()
        if not selected_item or not (selected_item.flags() & Qt.ItemFlag.ItemIsSelectable):
            QMessageBox.warning(self, "No Project Selected", "Please select a project from the list to delete.")
            return

        project_name = selected_item.text()

        reply = QMessageBox.warning(self,
                                    "Confirm Deletion",
                                    f"Are you absolutely sure you want to permanently delete the project '{project_name}' and all its contents?\n\nThis action cannot be undone.",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Yes:
            print(f"User confirmed deletion of project '{project_name}'.")
            self.log_to_ai_output(f"--- Deleting project '{project_name}'... ---")
            QApplication.processEvents()

            deleted = project_manager.delete_project(project_name)

            if deleted:
                self.log_to_console(f"Project '{project_name}' deleted successfully.")
                self.log_to_ai_output(f"--- Project '{project_name}' deleted. ---")
                # Si le projet supprimé était celui affiché, nettoyer la vue
                if self.current_project == project_name:
                    # clear_project_view met la phase à idle et appelle set_ui_enabled(False)
                    self.clear_project_view()
                # Recharger la liste des projets
                self.load_project_list()
                # --- AJOUTER CETTE LIGNE ---
                # S'assurer que l'UI est réactivée APRES le nettoyage/rechargement
                self.set_ui_enabled(True)
                # --------------------------
            else:
                # Gérer l'échec de la suppression
                self.log_to_console(f"Failed to delete project '{project_name}'. Check console logs.")
                self.log_to_ai_output(f"--- ERROR deleting project '{project_name}'. ---")
                QMessageBox.critical(self, "Deletion Error", f"Could not delete project '{project_name}'. See console for details.")
                # --- AJOUTER CETTE LIGNE AUSSI ---
                # Réactiver l'UI même après une erreur pour que l'utilisateur puisse continuer
                self.set_ui_enabled(True)
                # ---------------------------------
        else:
            # L'utilisateur a annulé
            print(f"Deletion of project '{project_name}' cancelled by user.")
            self.log_to_ai_output("--- Project deletion cancelled. ---")
            # Pas besoin de changer l'état de l'UI ici, car rien n'a été fait.

    def save_current_code(self):
        """Handles the manual saving of code from the editor."""
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot save code now."); return
        if not self.current_project: QMessageBox.warning(self, "No Project", "Select project."); return
        code = self.code_editor_text.toPlainText(); print(f"[GUI] Save '{self.current_project}'. Len: {len(code)}")
        if not code:
             reply = QMessageBox.question(self,'Confirm Empty','Save empty?', QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.No: self.log_to_console("Empty save cancelled."); return
        try:
            if project_manager.save_project_script_content(self.current_project, code): self.log_to_console(f"Code saved.")
            else: QMessageBox.critical(self, "Save Error", f"Failed save. Check logs.")
        except Exception as e: print(f"EXCEPTION save: {e}"); traceback.print_exc(); QMessageBox.critical(self, "Save Error", f"Error: {e}")

    # Utiliser les constantes dans run_current_project_script
    def run_current_project_script(self):
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self, "Busy", "Cannot run script now."); return
        if not self.current_project: QMessageBox.warning(self, "No Project", "Select project."); return
        try: project_path = project_manager.get_project_path(self.current_project)
        except Exception as e: msg=f"Error get path: {e}"; print(msg); QMessageBox.critical(self, "Run Error", msg); return
        script_file = os.path.join(project_path, DEFAULT_MAIN_SCRIPT)
        if not os.path.isdir(project_path): msg = f"Dir not found: '{project_path}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
        if not os.path.exists(script_file): msg = f"Script not found: '{DEFAULT_MAIN_SCRIPT}'"; self.log_to_console(msg); QMessageBox.critical(self, "Run Error", msg); return
        self.log_to_console(f"\n--- Running script: {self.current_project} ---")
        # L'état sera mis par start_worker
        if not self.start_worker(task_type=TASK_RUN_SCRIPT, task_callable=utils.run_project_script, project_path=project_path):
            self.log_to_console("--- Could not start script execution (Busy?) ---")


    def closeEvent(self, event): # ... (inchangé) ...
        if self._current_task_phase != TASK_IDLE: reply = QMessageBox.question(self, 'Confirm Exit', f'Task ({self._current_task_phase}) running. Exit?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        else: reply = QMessageBox.question(self, 'Confirm Exit', 'Sure?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: print("Closing..."); event.accept()
        else: print("Close ignored."); event.ignore()