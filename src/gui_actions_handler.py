# src/gui_actions_handler.py

import sys
import platform
import functools
import os
import subprocess
import re
import traceback
import ast
import shutil
from typing import List, Any, Optional, Dict, Callable, Type, Tuple
import typing

from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox,
    QApplication, QListWidgetItem, QFileDialog, QCheckBox, QSpinBox,
    QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer, QDir, QModelIndex
from PyQt6.QtGui import QTextCursor, QFont, QIntValidator

# Import des composants nécessaires depuis les autres modules
from . import project_manager
from . import utils
from . import exporter
from . import config_manager # Gère la config persistante

# Imports depuis llm_interaction
from .llm_interaction import (
    BaseLLMClient, LMStudioClient, GeminiClient,
    DEFAULT_LM_STUDIO_IP, DEFAULT_LM_STUDIO_PORT, DEFAULT_GEMINI_MODEL,
    AVAILABLE_GEMINI_MODELS, GOOGLE_GENAI_AVAILABLE
)

from .project_manager import DEFAULT_MAIN_SCRIPT

# Import de MainWindow uniquement pour la vérification de type
if typing.TYPE_CHECKING:
    from .gui_main_window import MainWindow


# ======================================================================
# --- CONSTANTES ---
# ======================================================================
TASK_IDLE = "idle"
TASK_INSTALL_DEPS = "install_deps"
# TASK_GENERATE_CODE = "generate_code" # Remplacé par STREAM
TASK_RUN_SCRIPT = "run_script"
TASK_ATTEMPT_CONNECTION = "attempt_connection"
TASK_EXPORT_PROJECT = "export_project"
TASK_EXPORT_SOURCE = "export_source"
TASK_IDENTIFY_DEPS_FROM_REQUEST = "identify_deps_from_request"
TASK_GENERATE_CODE_STREAM = "generate_code_stream_with_deps"
TASK_RESOLVE_IMPORT_PACKAGE = "resolve_import_package"

LLM_BACKEND_LMSTUDIO = "LM Studio"
LLM_BACKEND_GEMINI = "Google Gemini"

DEFAULT_MAX_CORRECTION_ATTEMPTS = config_manager.DEFAULT_CONFIG.get("ui_settings", {}).get("default_max_correction_attempts", 2)
STREAM_UPDATE_INTERVAL_MS = 50
MAX_STRUCTURE_INFO_LENGTH = 1500


# ======================================================================
# --- Worker Thread ---
# ======================================================================
class Worker(QObject):
    finished = pyqtSignal()
    log_message = pyqtSignal(str, str)
    chat_fragment_received = pyqtSignal(str)
    result = pyqtSignal(str, object)

    def __init__(self, task_type: str, task_callable: Callable, *args, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.task_callable = task_callable
        self.args = args
        self.kwargs = kwargs
        self._is_cancelled = False # Drapeau d'annulation

    def cancel(self):
        """Demande l'annulation de la tâche."""
        self._is_cancelled = True
        print(f"[Worker {id(self)}] Cancellation flag set for task '{self.task_type}'.")

    def _emit_log(self, message: str, source: str = 'status'):
        # Vérifie le drapeau avant d'émettre, sauf pour les messages d'annulation peut-être
        if not self._is_cancelled or "cancel" in message.lower():
             self.log_message.emit(message, source)

    def run(self):
        # ... (début run inchangé : log, reset _is_cancelled) ...
        print(f"[Worker {id(self)}] STARTING task: '{self.task_type}', callable: {self.task_callable.__name__}")
        self._emit_log(f"Starting: {self.task_type}...", 'status')
        self._is_cancelled = False
        task_result: Any = None
        msg = ""

        try:
            if self._is_cancelled:
                raise InterruptedError(f"Task '{self.task_type}' cancelled before execution.")

            actual_kwargs = self.kwargs.copy()
            console_logger = functools.partial(self._emit_log, source='console')
            status_logger = functools.partial(self._emit_log, source='status')

            # --- Injecte callbacks ---
            if self.task_type in [TASK_INSTALL_DEPS, TASK_EXPORT_PROJECT, TASK_RUN_SCRIPT, TASK_EXPORT_SOURCE]:
                def progress_callback_wrapper(message: str):
                    if not self._is_cancelled: console_logger(message)
                actual_kwargs['progress_callback'] = progress_callback_wrapper

            if self.task_type == TASK_GENERATE_CODE_STREAM:
                # Callback pour les fragments (inchangé)
                def fragment_emitter_wrapper(fragment: str):
                    if not self._is_cancelled: self.chat_fragment_received.emit(fragment)
                actual_kwargs['fragment_callback'] = fragment_emitter_wrapper

                # <<< NOUVEAU: Ajoute le callback de vérification d'annulation >>>
                actual_kwargs['cancellation_check'] = lambda: self._is_cancelled
                # ----------------------------------------------------------------

            # --- Exécute la Tâche ---
            if not self._is_cancelled:
                task_result = self.task_callable(*self.args, **actual_kwargs)

            # --- Définit Message de Complétion (si pas annulé) ---
            if not self._is_cancelled:
                # ... (définition de msg inchangée) ...
                if self.task_type == TASK_INSTALL_DEPS: msg = f"Dependency Install {'OK' if task_result else 'failed'}."
                elif self.task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST: msg = "Dependency identification (from request) finished."
                elif self.task_type == TASK_GENERATE_CODE_STREAM: msg = "Code generation stream finished."
                elif self.task_type == TASK_RUN_SCRIPT: msg = "Script execution finished."
                elif self.task_type == TASK_ATTEMPT_CONNECTION: msg = f"LLM Connection attempt finished ({'Success' if task_result else 'Failed'})."
                elif self.task_type == TASK_EXPORT_PROJECT: msg = f"Executable export process finished ({'Success' if task_result else 'Failed'})."
                elif self.task_type == TASK_EXPORT_SOURCE: msg = f"Source distribution export finished ({'Success' if task_result else 'Failed'})."
                elif self.task_type == TASK_RESOLVE_IMPORT_PACKAGE: msg = "Package name resolution finished."
                else: msg = f"Task '{self.task_type}' finished (unknown type)."


            # --- Gère Annulation & Émet Résultat ---
            if self._is_cancelled:
                pass # Géré par le handler
            else:
                status_logger(msg)
                self.result.emit(self.task_type, task_result)

        # ... (gestion des exceptions et bloc finally inchangés) ...
        except InterruptedError as ie:
             print(f"[Worker {id(self)}] Caught InterruptedError: {ie}")
        except Exception as e:
            if not self._is_cancelled:
                # ... (gestion erreur) ...
                 error_msg = f"Error in worker task '{self.task_type}': {e}"
                 print(f"EXCEPTION:\n{traceback.format_exc()}")
                 console_logger(f"--- Worker Error ---\nTask: {self.task_type}\n{traceback.format_exc()}\n--- End Worker Error ---")
                 status_logger(f"Error: {self.task_type} failed ({type(e).__name__}). See console log.")
                 self.result.emit(self.task_type, e)
            else:
                 print(f"[Worker {id(self)}] Exception '{e}' occurred but task '{self.task_type}' was already cancelled.")
        finally:
            is_cancelled_at_end = self._is_cancelled
            print(f"[Worker {id(self)}] FINISHED task '{self.task_type}'. Emitting finished (Cancelled={is_cancelled_at_end}).")
            self.finished.emit()



# ======================================================================
# --- Classe de Gestion des Actions ---
# ======================================================================
class GuiActionsHandler:

    # --- Attributs d'État ---
    _current_task_phase: str = TASK_IDLE
    _last_user_chat_message: str = ""
    _project_dependencies: List[str] = []
    _deps_identified_for_next_step: List[str] = []
    _pending_install_deps: List[str] = []
    _code_to_correct: Optional[str] = None
    _last_execution_error: Optional[str] = None
    _last_error_line: Optional[int] = None
    _correction_attempts: int = 0
    _chat_fragment_buffer: str = ""
    _chat_update_timer: QTimer
    _is_busy: bool = False
    _next_logical_phase_after_result: str = TASK_IDLE
    _missing_module_name: Optional[str] = None
    _was_cancelled_by_user: bool = False # <<< NOUVEAU Drapeau pour gérer l'annulation

    # --- Client & Threading ---
    current_project: Optional[str] = None
    llm_client: Optional[BaseLLMClient] = None
    thread: Optional[QThread] = None
    worker: Optional[Worker] = None

    # --- Constantes TASK ---
    TASK_IDLE = TASK_IDLE
    TASK_INSTALL_DEPS = TASK_INSTALL_DEPS
    # TASK_GENERATE_CODE = TASK_GENERATE_CODE # Obsolète
    TASK_RUN_SCRIPT = TASK_RUN_SCRIPT
    TASK_ATTEMPT_CONNECTION = TASK_ATTEMPT_CONNECTION
    TASK_EXPORT_PROJECT = TASK_EXPORT_PROJECT
    TASK_EXPORT_SOURCE = TASK_EXPORT_SOURCE
    TASK_IDENTIFY_DEPS_FROM_REQUEST = TASK_IDENTIFY_DEPS_FROM_REQUEST
    TASK_GENERATE_CODE_STREAM = TASK_GENERATE_CODE_STREAM
    TASK_RESOLVE_IMPORT_PACKAGE = TASK_RESOLVE_IMPORT_PACKAGE

    # --- Initialisation ---
    def __init__(self, main_window: 'MainWindow'):
        self.main_window = main_window
        self._is_busy = False
        self._current_task_phase = TASK_IDLE
        self.llm_client = None
        self.current_project = None
        self.thread = None
        self.worker = None
        self._last_user_chat_message = ""
        self._project_dependencies = []
        self._deps_identified_for_next_step = []
        self._pending_install_deps = []
        self._code_to_correct = None
        self._last_execution_error = None
        self._correction_attempts = 0
        self._chat_fragment_buffer = ""
        self._next_logical_phase_after_result = TASK_IDLE
        self._was_cancelled_by_user = False

        # Timer pour le chat
        self._chat_update_timer = QTimer()
        self._chat_update_timer.setInterval(STREAM_UPDATE_INTERVAL_MS)
        self._chat_update_timer.timeout.connect(self._process_chat_buffer)

    # ----------------------------------------------------------------------
    # --- Gestion du Worker ---
    # ----------------------------------------------------------------------

    def start_worker(self, task_type: str, task_callable: Callable, *args, **kwargs) -> bool:
        """Lance une tâche longue dans un thread séparé."""
        if self._is_busy:
            msg = f"Warning: Task '{task_type}' requested, but handler is busy with '{self._current_task_phase}'."
            print(msg)
            self.log_to_status(msg)
            return False

        self._is_busy = True
        self._current_task_phase = task_type
        self._was_cancelled_by_user = False # Réinitialise drapeau annulation
        self.set_ui_enabled(False, task_type) # Désactive l'UI, en passant la tâche

        self.thread = QThread()
        self.thread.setObjectName(f"WorkerThread_{task_type}_{id(self.thread)}")
        # Le worker est créé avec le drapeau _is_cancelled à False par défaut
        self.worker = Worker(task_type, task_callable, *args, **kwargs)
        self.worker.moveToThread(self.thread)

        # Connexions Signaux/Slots
        self.worker.log_message.connect(self._handle_worker_log)
        self.worker.result.connect(self.handle_worker_result)
        self.worker.chat_fragment_received.connect(self._buffer_chat_fragment)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(lambda: setattr(self, 'worker', None)) # Nettoie référence worker
        self.worker.finished.connect(self.worker.deleteLater) # Destruction worker
        self.thread.finished.connect(lambda: setattr(self, 'thread', None)) # Nettoie référence thread
        self.thread.finished.connect(self.thread.deleteLater) # Destruction thread

        # Utilise partial pour passer le type de tâche terminé
        on_finished_with_task = functools.partial(self._on_thread_finished, finished_task_type=task_type)
        self.thread.finished.connect(on_finished_with_task)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

        # Démarre le timer pour le chat si c'est une tâche de stream
        if task_type == TASK_GENERATE_CODE_STREAM:
            self._chat_fragment_buffer = ""
            self._chat_update_timer.start()

        print(f"Worker started for task: {task_type} on thread {self.thread.objectName()}. Handler is now BUSY.")
        return True

    def cancel_current_task(self):
        """Demande l'annulation de la tâche worker en cours."""
        if not self._is_busy or self.worker is None or self.thread is None or not self.thread.isRunning():
            print("Cancel requested but no cancellable task is running.")
            return

        # On ne permet l'annulation que pour certaines tâches (le stream pour l'instant)
        if self._current_task_phase == TASK_GENERATE_CODE_STREAM:
            print(f"Requesting cancellation for task '{self._current_task_phase}'...")
            self.log_to_status(f"Attempting to cancel task: {self._current_task_phase}...")
            self._was_cancelled_by_user = True # Indique que l'annulation vient de l'utilisateur
            self.worker.cancel() # Appelle la méthode cancel du worker
            # Le worker finira par émettre 'finished'. Le nettoyage et la réactivation UI se font dans _on_thread_finished.
            # On désactive immédiatement le bouton Annuler pour éviter clics multiples
            self.main_window.cancel_llm_button.setEnabled(False)
            self.main_window.cancel_llm_button.setText("Cancelling...")
        else:
            print(f"Task '{self._current_task_phase}' is not currently cancellable.")
            self.log_to_status(f"Task '{self._current_task_phase}' cannot be cancelled.")

    def _on_thread_finished(self, finished_task_type: str):
        """Appelé à la fin de l'exécution du thread worker."""
        next_phase = self._next_logical_phase_after_result
        was_cancelled = self._was_cancelled_by_user
        chain_started = False # Flag pour savoir si on a enchaîné

        print(f"[_on_thread_finished] START. Task: '{finished_task_type}'. Cancelled: {was_cancelled}. Next: '{next_phase}'. Busy: {self._is_busy}")

        # Arrête le timer du chat si nécessaire
        if finished_task_type == TASK_GENERATE_CODE_STREAM:
             self._process_chat_buffer()
             self._chat_update_timer.stop()
             print("Chat update timer stopped.")

        self._next_logical_phase_after_result = TASK_IDLE # Réinitialise la phase planifiée

        try:
            # --- Logique d'annulation ou d'enchaînement ---
            if was_cancelled:
                self.log_to_status(f"--- Task '{finished_task_type}' cancelled by user. ---")
                self.append_to_chat("System", f"(Task '{finished_task_type}' cancelled)")
                # Nettoyage spécifique
                if finished_task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST: self._deps_identified_for_next_step = []
                if finished_task_type == TASK_GENERATE_CODE_STREAM and (self._last_execution_error or self._code_to_correct):
                    print("[Cleanup] Cleaning correction markers after cancellation.")
                    self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None
                next_phase = TASK_IDLE # Force la fin

            # --- Tenter l'enchaînement si pas annulé ---
            elif next_phase != TASK_IDLE:
                print(f"[Chaining] Entering chaining logic for next_phase = '{next_phase}'")

                # ===========================================================
                # --- CORRECTION pour TASK_GENERATE_CODE_STREAM ---
                # ===========================================================
                if next_phase == TASK_GENERATE_CODE_STREAM:
                    print(f"[Chaining] Condition met for TASK_GENERATE_CODE_STREAM.")
                    is_correction_context = self._last_execution_error is not None and self._code_to_correct is not None

                    if self.current_project and self.llm_client and self.llm_client.is_available():

                        # Déclare les variables qui seront utilisées dans start_worker
                        prompt_for_llm: str
                        source_code_for_llm: str
                        dependencies_for_llm: List[str]

                        # Assigne les valeurs DANS les blocs conditionnels
                        if is_correction_context:
                            print("[Chaining] Preparing for CORRECTION stream.")
                            self.log_to_status(f"-> Generating correction stream (Attempt {self._correction_attempts})...")
                            line_info = f"(near line {self._last_error_line})" if self._last_error_line else ""
                            prompt_for_llm = (
                                f"The following Python code failed with an error. Please fix the code based on the error provided.\n\n"
                                f"**Error Message:**\n"
                                f"```text\n{self._last_execution_error}\n```\n"
                                f"**Context:** The error occurred {line_info}.\n\n"
                                f"**Instructions:** Output ONLY the complete, corrected Python code block. Do not add explanations outside the code."
                            )
                            source_code_for_llm = self._code_to_correct
                            dependencies_for_llm = self._project_dependencies # Utilise les deps existants pour correction

                        else: # Génération normale
                            print("[Chaining] Preparing for REGULAR code generation stream.")
                            self.log_to_status(f"-> Generating code stream using identified dependencies: {self._deps_identified_for_next_step}...")
                            prompt_for_llm = self._last_user_chat_message
                            source_code_for_llm = self.main_window.code_editor_text.toPlainText()
                            dependencies_for_llm = self._deps_identified_for_next_step # Utilise les deps identifiés

                        # Génère info structure (en dehors des ifs)
                        project_structure_info = self._generate_project_structure_info()

                        print(f"[Chaining] Releasing busy flag temporarily to start TASK_GENERATE_CODE_STREAM...")
                        self._is_busy = False # Libère avant
                        # Appelle start_worker AVEC les variables maintenant assignées
                        started = self.start_worker(
                            task_type=TASK_GENERATE_CODE_STREAM,
                            task_callable=self.llm_client.generate_code_stream_with_deps,
                            user_request=prompt_for_llm, # OK
                            project_name=self.current_project,
                            current_code=source_code_for_llm, # OK
                            dependencies_to_use=dependencies_for_llm, # OK
                            project_structure_info=project_structure_info
                        )

                        if started:
                            print(f"[Chaining] start_worker for TASK_GENERATE_CODE_STREAM returned True. Handler is BUSY again.")
                            chain_started = True
                            # Nettoie les marqueurs de correction SEULEMENT si on a démarré une correction
                            if is_correction_context:
                                print("[Chaining] Clearing correction markers after starting correction worker...")
                                self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None
                            # Ne pas nettoyer _deps_identified_for_next_step ici, on les a utilisés
                        else: # Echec démarrage worker
                            print(f"[Chaining] start_worker for TASK_GENERATE_CODE_STREAM returned False."); self.log_to_status("! Error starting code generation/correction stream.");
                            # Nettoyage si échec démarrage
                            if is_correction_context: self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None
                            self._deps_identified_for_next_step = [] # Nettoie aussi ici

                    else: # Conditions non remplies (projet/LLM)
                        print(f"[Chaining] Skipping TASK_GENERATE_CODE_STREAM due to missing project/LLM."); self.log_to_status("! Skipping code generation (missing project/LLM).");
                        # Nettoyage si skip
                        if is_correction_context: self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None
                        self._deps_identified_for_next_step = []

                # ===========================================================
                # --- Fin CORRECTION ---
                # ===========================================================

                # --- Blocs pour les autres 'next_phase' (inchangés structurellement) ---
                elif next_phase == TASK_INSTALL_DEPS:
                    # ... (code existant pour install deps, qui fonctionne) ...
                    print(f"[Chaining] Condition met for TASK_INSTALL_DEPS.")
                    if self._pending_install_deps and self.current_project:
                        project_path = project_manager.get_project_path(self.current_project)
                        print(f"[Chaining] Releasing busy flag temporarily to start TASK_INSTALL_DEPS...")
                        self._is_busy = False
                        started = self.start_worker(
                            task_type=TASK_INSTALL_DEPS,
                            task_callable=utils.install_project_dependencies,
                            project_path=project_path,
                            dependencies=self._pending_install_deps
                        )
                        if started:
                            print(f"[Chaining] start_worker for TASK_INSTALL_DEPS returned True. Handler is BUSY again.")
                            chain_started = True
                        else:
                            print(f"[Chaining] start_worker for TASK_INSTALL_DEPS returned False.")
                            self.log_to_console("! Error starting install worker.")
                            self.log_to_status("! Error starting dependency installation worker.")
                            self._pending_install_deps = [] # Nettoie si échec démarrage
                            if self._last_execution_error is not None: # Si échec démarrage pendant correction
                                self.append_to_chat("System", "Stopping correction attempts because dependency installation failed to start.")
                                self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None
                    else: # Conditions non remplies
                        print(f"[Chaining] Skipping TASK_INSTALL_DEPS (no pending deps or project).")
                        self._pending_install_deps = []
                        if self._last_execution_error is not None: # Si on skippe pendant correction
                           self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None

                elif next_phase == TASK_RESOLVE_IMPORT_PACKAGE:
                    # ... (code existant pour resolve import, qui fonctionne) ...
                    print(f"[Chaining] Condition met for TASK_RESOLVE_IMPORT_PACKAGE.")
                    if self.llm_client and self.llm_client.is_available() and self._missing_module_name and self._last_execution_error:
                        self.log_to_status(f"-> Asking LLM for package name for module '{self._missing_module_name}'...")
                        print(f"[Chaining] Releasing busy flag temporarily to start TASK_RESOLVE_IMPORT_PACKAGE...")
                        self._is_busy = False
                        started = self.start_worker(
                            task_type=TASK_RESOLVE_IMPORT_PACKAGE,
                            task_callable=self.llm_client.resolve_package_name_from_import_error,
                            module_name=self._missing_module_name,
                            error_message=self._last_execution_error
                        )
                        if started:
                            print(f"[Chaining] start_worker for TASK_RESOLVE_IMPORT_PACKAGE returned True. Handler is BUSY again.")
                            chain_started = True
                        else:
                            print(f"[Chaining] start_worker for TASK_RESOLVE_IMPORT_PACKAGE returned False.")
                            self.log_to_status("! Error starting package resolution worker.")
                            self.append_to_chat("System", "Stopping correction attempts because package resolution failed to start.")
                            self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None # Nettoie si échec démarrage
                    else: # Conditions non remplies
                         print(f"[Chaining] Skipping TASK_RESOLVE_IMPORT_PACKAGE due to failed condition.")
                         self.log_to_status("! Skipping package resolution step.")
                         self.append_to_chat("System", "Stopping correction attempts because package resolution step was skipped.")
                         self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None # Nettoie si skip


                elif next_phase == TASK_RUN_SCRIPT:
                    # ... (code existant pour run script, qui fonctionne) ...
                    print(f"[Chaining] Condition met for TASK_RUN_SCRIPT.")
                    self.log_to_status("-> Automatically running script...")
                    print(f"[Chaining] Releasing busy flag temporarily to start TASK_RUN_SCRIPT...")
                    self._is_busy = False
                    self.run_current_project_script(called_from_chain=True) # run_current_project_script appelle start_worker
                    if self._current_task_phase == TASK_RUN_SCRIPT and self._is_busy:
                        print(f"[Chaining] TASK_RUN_SCRIPT worker started successfully. Handler is BUSY again.")
                        chain_started = True
                    else:
                        print(f"[Chaining] run_current_project_script did not start the worker. Handler busy state: {self._is_busy}")


            # --- Si pas d'enchaînement réussi ou pas d'enchaînement prévu ---
            if not chain_started:
                 if next_phase == TASK_IDLE and not was_cancelled:
                     print(f"[Chaining] next_phase was IDLE. No chaining needed.")
                 elif not was_cancelled:
                     print(f"[Chaining] Chaining condition for '{next_phase}' not met or worker start failed.")
                 # Nettoyage si on termine sans enchaîner (et si ce n'était pas une annulation)
                 if not was_cancelled:
                     if finished_task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST: self._deps_identified_for_next_step = []
                     if self._last_execution_error or self._code_to_correct or self._missing_module_name:
                         print("[Chaining] Cleaning up stale correction/import markers on non-chain/non-cancel finish.")
                         self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None

        except Exception as e:
            # Gestion d'erreur interne de la logique d'enchaînement
            print(f"!!!!!!!!!!!!!!!! ERROR in _on_thread_finished logic !!!!!!!!!!!!!!!!"); print(traceback.format_exc()); print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            self.log_to_status(f"! Internal error during task chaining/finish: {e}"); self.log_to_console(f"! Internal error finishing {finished_task_type}: {e}\n{traceback.format_exc()}")
            # Reset complet état par sécurité
            self._next_logical_phase_after_result = TASK_IDLE; self._deps_identified_for_next_step = []; self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None; self._pending_install_deps = []
            chain_started = False # Assure que le finally réactive l'UI

        finally:
            # --- Réinitialisation état et UI ---
            print(f"[_on_thread_finished] FINALLY block. chain_started={chain_started}")
            if not chain_started:
                print(f"[_on_thread_finished] No chain started or task cancelled/failed. Resetting state to IDLE and enabling UI.")
                self._is_busy = False
                self._current_task_phase = TASK_IDLE
                self._was_cancelled_by_user = False # Reset flag annulation
                self.set_ui_enabled(True) # Réactive l'UI
            else:
                 print(f"[_on_thread_finished] Chain was started for '{self._current_task_phase}'. UI remains disabled.")
            print(f"[_on_thread_finished] END. Busy state: {self._is_busy}")



    def handle_worker_result(self, task_type: str, result: Any):
        """Traite le résultat d'une tâche worker (si elle n'a pas été annulée)."""
        # Ignore le résultat si la tâche a été annulée entre temps ou si décalage
        if self._was_cancelled_by_user:
            print(f"Ignoring result for task '{task_type}' because it was cancelled by the user.")
            return
        if task_type != self._current_task_phase:
            print(f"WARNING: Stale result ignored for task '{task_type}' (current: '{self._current_task_phase}').")
            return

        print(f"[GUI handle] Task '{task_type}'. Result type: {type(result)}")
        error_occurred = isinstance(result, Exception)
        next_phase = TASK_IDLE
        is_in_correction_cycle = self._last_execution_error is not None # Était-on en correction AVANT ce résultat?

        try:
            # --- Traitement spécifique par type de tâche ---

            # Connexion LLM
            if task_type == TASK_ATTEMPT_CONNECTION:
                # (Logique inchangée)
                llm_connected = not error_occurred and result is True; status = "Unknown"; color = "orange"; backend_name = "N/A"
                if self.llm_client: backend_name = self.llm_client.get_backend_name()
                if llm_connected: status = f"Connected ({backend_name})"; color = "green"; self.log_to_status(f"LLM Connection Successful ({backend_name})")
                else:
                    self.log_to_status(f"LLM Connection Failed ({backend_name})")
                    if error_occurred: status = f"Error ({backend_name})"; color = "red"; self.log_to_console(f"LLM Connect Error ({backend_name}): {result}")
                    else: status = f"Failed ({backend_name})"; color = "red"
                    self.llm_client = None # Assure que le client est nul si échec
                self.main_window.llm_status_label.setText(f"LLM: {status}"); self.main_window.llm_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                next_phase = TASK_IDLE # La connexion ne déclenche pas d'autre tâche

            # Identification Dépendances
            elif task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST:
                 # (Logique inchangée)
                 if error_occurred: self.log_to_status(f"Error identifying dependencies: {result}"); self.append_to_chat("System", f"Error identifying dependencies: {result}"); self._deps_identified_for_next_step = []; next_phase = TASK_IDLE
                 elif isinstance(result, list):
                     identified_deps = [dep for dep in result if not dep.startswith("ERROR:")]; errors = [dep for dep in result if dep.startswith("ERROR:")]
                     if errors: self.append_to_chat("System", f"Warning/Error during dependency check: {'; '.join(errors)}")
                     self._deps_identified_for_next_step = sorted(list(set(identified_deps))); dep_msg = f"Identified potential dependencies: {self._deps_identified_for_next_step or 'None'}"
                     self.log_to_console(dep_msg); self.append_to_chat("System", dep_msg); next_phase = TASK_GENERATE_CODE_STREAM # Enchaîne vers la génération
                 else: self.log_to_status(f"Unexpected result type for dependency ID: {type(result)}"); self.append_to_chat("System", f"Unexpected result type from dependency check: {type(result)}"); self._deps_identified_for_next_step = []; next_phase = TASK_IDLE

            # Stream Génération Code
            elif task_type == TASK_GENERATE_CODE_STREAM:
                # (Logique inchangée pour traitement résultat stream)
                completion_msg = "(Correction stream finished, processing...)" if is_in_correction_cycle else "(Code stream finished, processing...)"
                self.append_to_chat("System", completion_msg)
                if error_occurred:
                    self.log_to_status(f"Error during code generation/correction stream: {result}"); self.append_to_chat("System", f"Error during stream: {result}"); next_phase = TASK_IDLE; self._deps_identified_for_next_step = []
                    if is_in_correction_cycle: self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None
                elif isinstance(result, str):
                    cleaned_code = self._cleanup_llm_code_output(result); self.main_window.code_editor_text.setPlainText(cleaned_code); self.log_to_console("Code updated in editor from stream."); self.append_to_chat("System", "(Code updated in editor)")
                    if is_in_correction_cycle:
                        self.log_to_status("Correction applied. -> Re-running script to verify..."); self.append_to_chat("System", "Correction stream applied. Re-running script..."); next_phase = TASK_RUN_SCRIPT # Retente après correction
                    else: # Génération normale -> Vérif deps
                        current_proj_deps_set = set(self._project_dependencies); needed_deps_set = set(self._deps_identified_for_next_step); self._deps_identified_for_next_step = []
                        new_deps_to_install = sorted(list(needed_deps_set - current_proj_deps_set))
                        if new_deps_to_install:
                            self.log_to_status(f"New dependencies require installation: {new_deps_to_install}"); self.append_to_chat("System", f"New dependencies identified and possibly needed: {new_deps_to_install}"); self._pending_install_deps = new_deps_to_install; self._project_dependencies = sorted(list(needed_deps_set.union(current_proj_deps_set))); self.update_project_metadata_deps(); next_phase = TASK_INSTALL_DEPS # Enchaîne vers install
                        else: self.log_to_status("Dependencies identified are already met or not needed."); self.append_to_chat("System", "No new dependencies seem required for installation."); next_phase = TASK_IDLE
                else:
                    self.log_to_status(f"Unexpected result type after stream: {type(result)}"); self.append_to_chat("System", f"Unexpected result type from LLM stream: {type(result)}"); next_phase = TASK_IDLE; self._deps_identified_for_next_step = []
                    if is_in_correction_cycle: self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None

            # Résolution Nom Package
            elif task_type == TASK_RESOLVE_IMPORT_PACKAGE:
                # (Logique inchangée)
                package_name, error_str = result if isinstance(result, tuple) and len(result) == 2 else (None, f"Unexpected result type: {type(result)}")
                if package_name:
                    self.log_to_status(f"LLM identified package '{package_name}' for module '{self._missing_module_name}'."); self.append_to_chat("System", f"LLM suggests installing package: '{package_name}'. Attempting installation..."); self._pending_install_deps = [package_name]; self._missing_module_name = None; next_phase = TASK_INSTALL_DEPS # Enchaîne vers install
                else:
                    self.log_to_status(f"Failed to resolve package for '{self._missing_module_name}': {error_str}"); self.append_to_chat("System", f"Could not automatically determine the package to install for module '{self._missing_module_name}'. {error_str}"); self.append_to_chat("System", "Stopping correction attempts. Please install the correct package manually or modify the code."); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None; next_phase = TASK_IDLE # Arrête le cycle

            # Installation Dépendances
            elif task_type == TASK_INSTALL_DEPS:
                # (Logique inchangée)
                install_successful = not error_occurred and result is True
                if install_successful:
                    self.log_to_status("Dependencies installed successfully."); self.log_to_console("--- Dependency installation successful ---"); installed_deps_log = self._pending_install_deps[:]; self._project_dependencies = sorted(list(set(self._project_dependencies).union(set(self._pending_install_deps)))); self.update_project_metadata_deps(); self._pending_install_deps = []; self.append_to_chat("System", f"Dependencies installed successfully: {installed_deps_log}")
                    if is_in_correction_cycle:
                        self.log_to_status("Dependency installed during correction cycle. -> Re-running script..."); self.append_to_chat("System", f"Installed dependencies. Re-running script to see if it fixes the error..."); next_phase = TASK_RUN_SCRIPT # Enchaîne vers run
                    else: next_phase = TASK_IDLE
                else:
                    failed_deps = self._pending_install_deps; self.log_to_status(f"Error installing dependencies: {failed_deps}. Check console log."); self.log_to_console(f"--- ERROR installing dependencies: {failed_deps} ---"); self.append_to_chat("System", f"Error installing dependencies: {failed_deps}. Check Execution Log for details.");
                    if error_occurred: self.log_to_console(f"Error details: {result}")
                    self._pending_install_deps = []
                    if is_in_correction_cycle: self.append_to_chat("System", "Stopping correction attempts because dependency installation failed."); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None
                    next_phase = TASK_IDLE # Arrête cycle si install échoue

            # Exécution Script
            elif task_type == TASK_RUN_SCRIPT:
                 # (Logique inchangée pour traitement résultat run, incluant auto-correction)
                self.log_to_console(f"--- Script execution task finished ---"); error_message_for_llm = ""; error_line_number = None
                if isinstance(result, subprocess.CompletedProcess):
                    if result.returncode == 0: # Succès
                        self.log_to_status("--- Script executed successfully! ---"); self.log_to_console("--- Script executed successfully! Process complete. ---");
                        if is_in_correction_cycle: self.append_to_chat("System", "Success! The script ran successfully after correction/installation.")
                        self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None; next_phase = TASK_IDLE # Fin du cycle
                    else: # Échec
                        max_attempts = self.main_window.max_attempts_spinbox.value(); auto_correct_enabled = self.main_window.auto_correct_checkbox.isChecked(); full_error_output = ""; stderr_clean = result.stderr.strip() if result.stderr else ""; stdout_clean = result.stdout.strip() if result.stdout else "";
                        if stderr_clean: full_error_output = stderr_clean
                        elif stdout_clean: full_error_output = stdout_clean
                        else: full_error_output = f"Script failed with exit code: {result.returncode}."
                        error_message_for_llm = full_error_output; match_line = re.search(r'File ".*?", line (\d+)', full_error_output);
                        if match_line: 
                            try: error_line_number = int(match_line.group(1)); print(f"[AutoCorrect] Extracted line number: {error_line_number}"); 
                            except ValueError: pass
                        print(f"[AutoCorrect] Error captured:\n---\n{error_message_for_llm}\n---")
                        module_match = re.search(r"ModuleNotFoundError: No module named '([^']*)'", error_message_for_llm); import_match = re.search(r"ImportError:.*'([^']*)'", error_message_for_llm); missing_module_name = None
                        if module_match: missing_module_name = module_match.group(1)
                        elif import_match: missing_module_name = import_match.group(1).split('.')[-1]
                        if auto_correct_enabled and missing_module_name and self._correction_attempts < max_attempts:
                            self.log_to_status(f"Script error: Missing module '{missing_module_name}'. Asking LLM for package name..."); self.log_to_console(f"--- Missing module detected: {missing_module_name}. Attempting resolution... ---"); self.append_to_chat("System", f"Script error seems to be a missing module: '{missing_module_name}'."); self.append_to_chat("System", f"Asking LLM for the correct package name..."); self._code_to_correct = self.main_window.code_editor_text.toPlainText(); self._last_execution_error = error_message_for_llm; self._last_error_line = error_line_number; self._missing_module_name = missing_module_name; next_phase = TASK_RESOLVE_IMPORT_PACKAGE # Enchaîne vers résolution
                        elif auto_correct_enabled and self._correction_attempts < max_attempts:
                            self._correction_attempts += 1; self.log_to_status(f"Script error. Preparing streaming auto-correction (Attempt {self._correction_attempts}/{max_attempts})..."); self.log_to_console(f"--- Script error detected. Attempting STREAM correction ({self._correction_attempts}/{max_attempts})... ---"); self.append_to_chat("System", f"Script error detected (Attempt {self._correction_attempts}/{max_attempts}). Attempting streaming auto-correction..."); self.append_to_chat("System", f"Error details:\n```text\n{error_message_for_llm}\n```"); self._code_to_correct = self.main_window.code_editor_text.toPlainText(); self._last_execution_error = error_message_for_llm; self._last_error_line = error_line_number; self._missing_module_name = None; next_phase = TASK_GENERATE_CODE_STREAM # Enchaîne vers correction stream
                        else:
                            status_end_msg = f"Script error. Max correction/install attempts ({max_attempts}) reached." if auto_correct_enabled else "Script error. Auto-correction disabled."; self.log_to_status(status_end_msg); self.log_to_console(f"--- Script failed after {self._correction_attempts} attempts or auto-correct disabled. ---"); self.append_to_chat("System", status_end_msg + " Stopping attempts."); self.append_to_chat("System", "You can try modifying the code in the editor or refine your request in the chat.");
                            if error_message_for_llm: self.append_to_chat("System", f"Final Error:\n```text\n{error_message_for_llm}\n```")
                            self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None; next_phase = TASK_IDLE # Fin du cycle
                elif error_occurred:
                    self.log_to_status(f"Error running script task: {result}. Check console log."); self.log_to_console(f"--- ERROR running script task: {result} ---"); self.append_to_chat("System", f"Internal error trying to run the script: {result}"); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None; next_phase = TASK_IDLE
                else:
                    self.log_to_status(f"Unknown result type for run_script: {type(result)}. Check console log."); self.log_to_console(f"--- Unknown result type for run_script: {type(result)} ---"); self.append_to_chat("System", f"Internal error: Unexpected result from script execution: {type(result)}"); self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None; self._last_error_line = None; self._missing_module_name = None; next_phase = TASK_IDLE

            # Export Projet
            elif task_type == TASK_EXPORT_PROJECT:
                 # (Logique inchangée)
                 if error_occurred: QMessageBox.critical(self.main_window, "Export Error", f"Failed executable export.\nError: {result}")
                 elif result is True: QMessageBox.information(self.main_window, "Export Successful", "Executable bundle exported successfully!")
                 else: QMessageBox.warning(self.main_window, "Export Failed", "Executable export process finished but reported failure.")
                 next_phase = TASK_IDLE
            # Export Source
            elif task_type == TASK_EXPORT_SOURCE:
                 # (Logique inchangée)
                 if error_occurred: QMessageBox.critical(self.main_window, "Export Error", f"Failed source distribution export.\nError: {result}")
                 elif result is True: QMessageBox.information(self.main_window, "Export Successful", "Source distribution exported successfully!")
                 else: QMessageBox.warning(self.main_window, "Export Failed", "Source export process finished but reported failure.")
                 next_phase = TASK_IDLE

            # Tâche Inconnue
            else:
                self.log_to_status(f"--- Unhandled task result for task: {task_type} ---"); self.log_to_console(f"--- Unhandled task result: {task_type}, Result: {result} ---"); next_phase = TASK_IDLE

        except Exception as handler_ex:
            # Gestion erreur interne (inchangée)
            print(f"!!!!!!!!!!!!!!!! EXCEPTION in handle_worker_result !!!!!!!!!!!!!!!!"); print(traceback.format_exc()); print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"); self.log_to_status(f"! Internal error handling result: {handler_ex}"); self.log_to_console(f"! Internal error handling result for {task_type}: {handler_ex}\n{traceback.format_exc()}"); self.append_to_chat("System", f"Critical Internal Error while handling task result: {handler_ex}")
            self._deps_identified_for_next_step = []; self._last_execution_error = None; self._code_to_correct = None; self._correction_attempts = 0; self._last_error_line = None; self._missing_module_name = None; self._pending_install_deps = []
            next_phase = TASK_IDLE

        finally:
            # Stocke la prochaine phase pour _on_thread_finished
            self._next_logical_phase_after_result = next_phase
            print(f"Handler finished processing result for '{task_type}'. Next logical phase stored as: '{next_phase}'")


    # ----------------------------------------------------------------------
    # --- Gestion de l'État de l'UI ---
    # ----------------------------------------------------------------------

    def set_ui_enabled(self, enabled: bool, current_task: Optional[str] = None):
        """Active ou désactive les widgets de l'UI en fonction de l'état."""
        mw = self.main_window
        llm_ok = self.llm_client is not None and self.llm_client.is_available()
        is_project_loaded = self.current_project is not None

        # --- Contrôles généraux ---
        mw.project_list_widget.setEnabled(enabled)
        mw.llm_reconnect_button.setEnabled(enabled)
        mw.llm_backend_selector.setEnabled(enabled)
        if hasattr(mw, 'dev_mode_button'): mw.dev_mode_button.setEnabled(enabled)

        # --- Groupes d'actions projet (activés/désactivés en bloc) ---
        mw.project_actions_group.setEnabled(enabled) # New/Delete
        # Les boutons à l'intérieur dépendent aussi de la sélection/projet chargé
        selected_item = mw.project_list_widget.currentItem()
        is_valid_selection = False
        if selected_item:
            is_placeholder = selected_item.text() in ["No projects found", "Error loading list"]
            is_valid_selection = bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable) and not is_placeholder

        mw.delete_project_button.setEnabled(enabled and is_project_loaded and is_valid_selection)

        # --- Manage Files Group & Buttons ---
        can_manage_project_files = enabled and is_project_loaded
        mw.manage_files_group.setEnabled(can_manage_project_files) # Active/désactive le groupe visuellement
        # <<< CORRECTION: Gère l'état des boutons explicitement >>>
        mw.add_file_button.setEnabled(can_manage_project_files)
        mw.add_folder_button.setEnabled(can_manage_project_files)
        # ---------------------------------------------------------

        # --- Export Group & Buttons ---
        can_export = enabled and is_project_loaded and is_valid_selection
        mw.export_group.setEnabled(can_export) # Active/désactive le groupe visuellement
        # (On pourrait aussi gérer les boutons export explicitement si nécessaire, mais le groupe suffit souvent)
        mw.export_button.setEnabled(can_export)
        mw.export_source_button.setEnabled(can_export)


        # --- Contrôles backend LLM ---
        selected_backend = mw.llm_backend_selector.currentText()
        can_edit_lmstudio = enabled and selected_backend == LLM_BACKEND_LMSTUDIO
        can_edit_gemini = enabled and selected_backend == LLM_BACKEND_GEMINI
        mw.lmstudio_group.setEnabled(can_edit_lmstudio)
        mw.gemini_group.setEnabled(can_edit_gemini)

        # --- Contrôles spécifiques projet (éditeur, run, dépendances manuelles) ---
        can_interact_with_project = enabled and is_project_loaded
        mw.run_script_button.setEnabled(can_interact_with_project)
        mw.auto_correct_checkbox.setEnabled(can_interact_with_project)
        mw.max_attempts_spinbox.setEnabled(can_interact_with_project)
        mw.save_code_button.setEnabled(can_interact_with_project)
        mw.code_editor_text.setReadOnly(not can_interact_with_project)

        if hasattr(mw, 'deps_group'):
             mw.deps_group.setEnabled(can_interact_with_project)
             # Les widgets internes (install_deps_input, install_deps_button)
             # sont automatiquement gérés par l'état du groupe parent ici.

        # --- Chat ---
        can_chat = enabled and is_project_loaded and llm_ok
        is_generating_stream = not enabled and current_task == TASK_GENERATE_CODE_STREAM

        mw.chat_input_text.setEnabled(can_chat)
        mw.chat_send_button.setEnabled(can_chat)
        mw.chat_send_button.setText("Send Request / Refine Code" if can_chat else "Processing...")

        mw.cancel_llm_button.setVisible(is_generating_stream)
        mw.cancel_llm_button.setEnabled(is_generating_stream)
        if is_generating_stream:
            mw.cancel_llm_button.setText("Cancel Generation")


        # --- Contrôles des logs (Save button) ---
        if hasattr(mw, 'save_logs_button'): mw.save_logs_button.setEnabled(enabled)

        # --- Curseur & Statut ---
        if not enabled:
            if QApplication.overrideCursor() is None: QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.log_to_status(f"Busy: {current_task or self._current_task_phase}...")
        else:
            if QApplication.overrideCursor() is not None: QApplication.restoreOverrideCursor()
            if self._current_task_phase == TASK_IDLE:
                backend_name = self.llm_client.get_backend_name() if llm_ok else "N/A"; conn_status = 'Connected' if llm_ok else 'Not Connected'
                if self.llm_client and not llm_ok and not isinstance(self.llm_client, Exception): conn_status = 'Connection Error'
                status_suffix = f"(LLM: {backend_name} - {conn_status})"
                proj_info = f"Project: {self.current_project}" if self.current_project else "No Project Loaded"
                self.log_to_status(f"--- Ready --- {proj_info} {status_suffix}")


    # ----------------------------------------------------------------------
    # --- Journalisation & Mises à jour UI (inchangé) ---
    # ----------------------------------------------------------------------
    def _handle_worker_log(self, message: str, source: str):
        if source == 'console': self.log_to_console(message)
        elif source == 'status': self.log_to_status(message)
        else: print(f"Unknown log source: {source} - Msg: {message}"); self.log_to_console(f"[Unknown Log: {source}] {message}")

    def log_to_console(self, message: str):
        mw = self.main_window; mw.execution_log_text.append(str(message)); mw.execution_log_text.verticalScrollBar().setValue(mw.execution_log_text.verticalScrollBar().maximum()); print(f"CONSOLE_LOG: {message}")

    def log_to_status(self, message: str):
        mw = self.main_window; mw.status_log_text.append(str(message)); mw.status_log_text.verticalScrollBar().setValue(mw.status_log_text.verticalScrollBar().maximum()); print(f"STATUS_LOG: {message}")

    # ----------------------------------------------------------------------
    # --- Slots pour config LLM & Dev Mode (inchangé) ---
    # ----------------------------------------------------------------------
    def on_llm_backend_changed(self, new_backend: str):
        print(f"LLM Backend selection changed to: {new_backend}"); self.main_window.update_llm_ui_for_backend()
        if self.llm_client and self.llm_client.get_backend_name() != new_backend: self.log_to_status(f"Backend changed to {new_backend}. Resetting connection status."); self.llm_client = None; self.main_window.llm_status_label.setText("LLM: Backend Changed"); self.main_window.llm_status_label.setStyleSheet("color: orange;"); self.set_ui_enabled(self._current_task_phase == TASK_IDLE)
        print("Attempting connection due to backend change..."); self.attempt_llm_connection()

    def on_llm_config_changed(self):
        sender_widget = self.main_window.sender(); config_value_changed = False
        if not sender_widget: print("Warning: on_llm_config_changed called without a specific sender widget."); return
        widget_name = sender_widget.objectName() if sender_widget.objectName() else type(sender_widget).__name__; print(f"LLM configuration parameter potentially changed (signal from: {widget_name}).")
        if sender_widget == self.main_window.gemini_api_key_input: current_key = self.main_window.gemini_api_key_input.text(); config_manager.set_api_key(current_key); self.log_to_status("API Key updated in config (if changed)."); config_value_changed = True
        elif sender_widget == self.main_window.gemini_model_selector: current_model = self.main_window.gemini_model_selector.currentText(); config_manager.set_last_used_gemini_model(current_model); self.log_to_status(f"Gemini model selection updated to {current_model} in config (if changed)."); config_value_changed = True
        elif sender_widget == self.main_window.llm_ip_input or sender_widget == self.main_window.llm_port_input: current_ip = self.main_window.llm_ip_input.text().strip(); current_port_str = self.main_window.llm_port_input.text().strip(); config_manager.set_last_used_lmstudio_details(current_ip, current_port_str); self.log_to_status(f"LM Studio details updated to {current_ip}:{current_port_str} in config (if changed)."); config_value_changed = True
        if config_value_changed: print("Attempting connection due to config parameter change..."); self.attempt_llm_connection()

    def toggle_dev_mode(self, checked: bool):
        print(f"Dev mode toggled: {'ON' if checked else 'OFF'}"); self.main_window.set_dev_elements_visibility(checked)

    # ----------------------------------------------------------------------
    # --- Interaction LLM (inchangé sauf ajout log annulation) ---
    # ----------------------------------------------------------------------
    def attempt_llm_connection(self):
        # (Logique inchangée)
        if self.thread is not None and self.thread.isRunning():
            if self._current_task_phase != TASK_ATTEMPT_CONNECTION: print(f"Skipping connection attempt: Task '{self._current_task_phase}' is already running."); return
            else: print("Skipping connection attempt: A connection attempt is already in progress."); return
        selected_backend = self.main_window.llm_backend_selector.currentText(); host_ip = self.main_window.llm_ip_input.text().strip(); port_str = self.main_window.llm_port_input.text().strip(); api_key = self.main_window.gemini_api_key_input.text(); model_name = self.main_window.gemini_model_selector.currentText(); connect_args: Dict[str, Any] = {}; client_instance: Optional[BaseLLMClient] = None; connect_callable: Optional[Callable] = None; status_msg = "LLM: Preparing..."; self.llm_client = None
        try:
            if selected_backend == LLM_BACKEND_LMSTUDIO: host_ip_eff = host_ip or DEFAULT_LM_STUDIO_IP; port_str_eff = port_str or str(DEFAULT_LM_STUDIO_PORT); port_val = int(port_str_eff); connect_args = {"host": host_ip_eff, "port": port_val}; client_instance = LMStudioClient(); connect_callable = client_instance.connect; status_msg = f"LLM: Connecting to LM Studio {host_ip_eff}:{port_val}..."
            elif selected_backend == LLM_BACKEND_GEMINI:
                if not GOOGLE_GENAI_AVAILABLE: raise ConnectionError("'google-generai' not installed.")
                if not api_key: raise ValueError("Gemini API Key missing.");
                if not model_name: raise ValueError("Gemini Model Name missing.")
                connect_args = {"api_key": api_key, "model_name": model_name}; client_instance = GeminiClient(); connect_callable = client_instance.connect; status_msg = f"LLM: Connecting to Gemini ({model_name})..."
            else: raise ValueError(f"Unknown LLM backend: {selected_backend}")
            self.main_window.llm_status_label.setText(status_msg); self.main_window.llm_status_label.setStyleSheet("color: orange;"); QApplication.processEvents(); self.llm_client = client_instance
        except (ValueError, ConnectionError, TypeError) as e: print(f"LLM Configuration error: {e}"); self.log_to_console(f"LLM Config Error: {e}"); self.llm_client = None; self.main_window.llm_status_label.setText(f"LLM: Config Error"); self.main_window.llm_status_label.setStyleSheet("color: red;"); self.set_ui_enabled(True); return
        if connect_callable and self.llm_client:
            print(f"Starting LLM connection worker for {selected_backend}..."); started = self.start_worker(task_type=TASK_ATTEMPT_CONNECTION, task_callable=connect_callable, **connect_args)
            if not started: print("Failed to start the connection worker (already busy?)."); self.llm_client = None; self.main_window.llm_status_label.setText(f"LLM: Failed (Busy?)"); self.main_window.llm_status_label.setStyleSheet("color: red;"); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True) # Reset si start échoue
        else: print("Internal error: connect_callable or client_instance missing."); self.llm_client = None; self.main_window.llm_status_label.setText(f"LLM: Internal Error"); self.main_window.llm_status_label.setStyleSheet("color: red;"); self.set_ui_enabled(True)

    # ----------------------------------------------------------------------
    # --- Interaction Chat (inchangé) ---
    # ----------------------------------------------------------------------
    def send_chat_message(self):
        # (Logique inchangée)
        if self._is_busy: QMessageBox.warning(self.main_window, "Busy", f"Cannot send request while task '{self._current_task_phase}' is running."); return
        user_request = self.main_window.chat_input_text.text().strip();
        if not self.current_project: QMessageBox.warning(self.main_window, "No Project Selected", "Select or create a project first."); return
        if not self.llm_client or not self.llm_client.is_available(): QMessageBox.warning(self.main_window, "LLM Not Ready", "LLM not connected or available. Check configuration and connection status."); return
        if not user_request: QMessageBox.warning(self.main_window, "Input Needed", "Describe your goal or the modification you want."); return
        self._last_user_chat_message = user_request; self.main_window.chat_input_text.clear(); self.main_window.chat_display_text.clear(); self.append_to_chat("User", user_request); self.append_to_chat("System", "(Analyzing request for dependencies...)"); QApplication.processEvents()
        project_structure_info = self._generate_project_structure_info(); self.log_to_status(f"--- Sending request to LLM for dependency identification... ---")
        started = self.start_worker(task_type=TASK_IDENTIFY_DEPS_FROM_REQUEST, task_callable=self.llm_client.identify_dependencies_from_request, user_prompt=user_request, project_name=self.current_project, project_structure_info=project_structure_info)
        if not started: self.append_to_chat("System", "Error: Could not start dependency identification task (Busy?)."); self.main_window.chat_input_text.setText(user_request)

    def append_to_chat(self, sender: str, message: str):
        # (Logique inchangée)
        chat_widget = self.main_window.chat_display_text; cursor = chat_widget.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End); chat_widget.setTextCursor(cursor);
        if not chat_widget.toPlainText().endswith('\n\n') and chat_widget.toPlainText().strip(): chat_widget.insertHtml("<br>")
        chat_widget.insertHtml(f"<b>{sender}:</b> "); chat_widget.insertPlainText(message.strip()); chat_widget.insertHtml("<br><br>"); chat_widget.ensureCursorVisible()

    def _buffer_chat_fragment(self, fragment: str): self._chat_fragment_buffer += fragment
    def _process_chat_buffer(self):
        if self._chat_fragment_buffer: chat_widget = self.main_window.chat_display_text; cursor = chat_widget.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End); chat_widget.setTextCursor(cursor); chat_widget.insertPlainText(self._chat_fragment_buffer); self._chat_fragment_buffer = ""; chat_widget.ensureCursorVisible()

    def _cleanup_llm_code_output(self, code_text: str) -> str:
        if not code_text:
            return "" # Retourne vide si l'entrée est vide

        code_text = code_text.strip()

        # <<< CORRECTION: Initialise les variables à None >>>
        python_match = None
        plain_match = None
        # --------------------------------------------------

        try:
            # Premier essai: bloc ```python ... ```
            python_match = re.search(r"```python\s*([\s\S]+?)\s*```", code_text, re.DOTALL)
            if python_match:
                print("Code extracted from ```python block.")
                return python_match.group(1).strip()

            # Deuxième essai: bloc ``` ... ```
            plain_match = re.search(r"```\s*([\s\S]+?)\s*```", code_text, re.DOTALL)
            if plain_match:
                print("Code extracted from plain ``` block.")
                return plain_match.group(1).strip()

            # Troisième essai: ressemble au début de code ?
            # Utilise re.match pour chercher UNIQUEMENT au début de la chaîne
            if re.match(r"^(import|from|def|class|#|\s)", code_text):
                print("Warning: No fences found, assuming raw code.")
                return code_text # Retourne le texte tel quel (après strip)

            # Fallback: si rien ne correspond, retourne le texte strippé
            print("Warning: Could not extract code using common patterns, returning original stripped text.")
            return code_text

        except Exception as e:
            # Gère les erreurs potentielles des regex ou .group()
            print(f"ERROR during code cleanup: {e}")
            traceback.print_exc()
            # Retourne le texte original en cas d'erreur de nettoyage
            return code_text.strip() # Retourne au moins le texte strippé

    # ----------------------------------------------------------------------
    # --- Actions Gestion Projet (inchangé sauf activation boutons) ---
    # ----------------------------------------------------------------------

    def load_project_list(self):
        """Charge et affiche la liste des projets."""
        # N'empêche le chargement que si une tâche AUTRE que la connexion est en cours.
        if self._current_task_phase not in [TASK_IDLE, TASK_ATTEMPT_CONNECTION]:
            print(f"Busy with task '{self._current_task_phase}', skipping project list load")
            return

        mw = self.main_window
        mw.project_list_widget.blockSignals(True)
        mw.project_list_widget.clear() # <<<=== DÉPLACÉ ICI

        try:
            projects = project_manager.list_projects()
            print(f"[Handler] Projects found by project_manager: {projects}")
            if projects:
                 print(f"[Handler] Adding items to QListWidget: {projects}")
                 mw.project_list_widget.addItems(projects)
                 mw.project_list_widget.setEnabled(True)
                 if self.current_project and self.current_project in projects:
                     items = mw.project_list_widget.findItems(self.current_project, Qt.MatchFlag.MatchExactly)
                     if items:
                         mw.project_list_widget.setCurrentItem(items[0])
            else:
                 print("[Handler] No projects found or list empty.")
                 item = QListWidgetItem("No projects found")
                 item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                 mw.project_list_widget.addItem(item)
                 mw.project_list_widget.setEnabled(True)
        except Exception as e:
            print(f"[Handler] Error loading project list: {e}")
            self.log_to_console(f"Error loading project list:\n{traceback.format_exc()}")
            # Ne pas ajouter l'item d'erreur si la liste est déjà vide
            if mw.project_list_widget.count() == 0:
                item = QListWidgetItem("Error loading list")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                mw.project_list_widget.addItem(item)
            mw.project_list_widget.setEnabled(True) # Widget actif même si erreur
        finally:
             mw.project_list_widget.blockSignals(False) # Réactive les signaux

    def load_selected_project(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        # (Logique inchangée pour sélection et gestion occupation)
        mw = self.main_window; project_name: Optional[str] = None; is_valid_selection = False
        if current_item is not None: item_is_selectable = bool(current_item.flags() & Qt.ItemFlag.ItemIsSelectable); is_placeholder = current_item.text() in ["No projects found", "Error loading list"]; is_valid_selection = item_is_selectable and not is_placeholder;
        if is_valid_selection: project_name = current_item.text()
        # Activation boutons (déplacé vers set_ui_enabled)
        if self._current_task_phase not in [TASK_IDLE, TASK_ATTEMPT_CONNECTION]:
            if is_valid_selection and self.current_project != project_name: print(f"Busy with task '{self._current_task_phase}', cannot switch project to {project_name}."); mw.project_list_widget.blockSignals(True); mw.project_list_widget.setCurrentItem(previous_item); mw.project_list_widget.blockSignals(False); QMessageBox.warning(mw, "Busy", f"Cannot switch project while task '{self._current_task_phase}' is running.")
            return
        if not is_valid_selection:
            if self.current_project: self.clear_project_view()
        elif self.current_project != project_name:
            self.current_project = project_name; mw.setWindowTitle(f"Pythautom - {project_name}"); print(f"Loading project: {project_name}"); self.clear_project_view_content(); self.log_to_status(f"--- Project '{project_name}' loaded ---"); self.reload_project_data(load_dependencies=True); self._last_user_chat_message = ""; self._pending_install_deps = []; self._deps_identified_for_next_step = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0
        self.set_ui_enabled(self._current_task_phase in [TASK_IDLE, TASK_ATTEMPT_CONNECTION]) # Met à jour état UI

    def reload_project_data(self, update_editor=True, load_dependencies=False):
        # (Logique inchangée)
        if not self.current_project: return; print(f"[GUI Handler] Reloading data for '{self.current_project}'. Editor={update_editor}, Deps={load_dependencies}")
        if update_editor:
            try: code = project_manager.get_project_script_content(self.current_project); self.main_window.code_editor_text.setPlainText(code if code is not None else f"# Failed to read {DEFAULT_MAIN_SCRIPT}")
            except Exception as e: err_msg = f"# Error loading script: {e}"; self.main_window.code_editor_text.setPlainText(err_msg); self.log_to_console(f"Error loading script: {e}")
        if load_dependencies:
            try: metadata = project_manager.load_project_metadata(self.current_project); self._project_dependencies = metadata.get("dependencies", []) ; self.log_to_console(f"Loaded dependencies from metadata: {self._project_dependencies}")
            except Exception as e: self._project_dependencies = []; self.log_to_console(f"Error loading dependencies from metadata for {self.current_project}: {e}")

    def clear_project_view_content(self):
        # (Logique inchangée)
        mw = self.main_window; print("Clearing project view content..."); mw.code_editor_text.clear(); mw.status_log_text.clear(); mw.execution_log_text.clear(); mw.chat_display_text.clear(); mw.chat_input_text.clear()

    def clear_project_view(self):
        # (Logique inchangée)
        mw = self.main_window; print("Clearing project view completely..."); self.current_project = None; mw.setWindowTitle("Pythautom - AI Python Project Builder"); self.clear_project_view_content(); self._current_task_phase = TASK_IDLE; self._last_user_chat_message = ""; self._project_dependencies = []; self._pending_install_deps = []; self._deps_identified_for_next_step = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0; self.set_ui_enabled(True)

    def create_new_project_dialog(self):
        # (Logique inchangée)
        if self._is_busy: QMessageBox.warning(self.main_window, "Busy", "Cannot create project while a task is running."); return
        dialog = QDialog(self.main_window); dialog.setWindowTitle("Create New Project"); layout = QVBoxLayout(dialog); label = QLabel("Enter project name (alphanumeric, _, -):"); name_input = QLineEdit(); layout.addWidget(label); layout.addWidget(name_input); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec():
            raw_name = name_input.text().strip(); safe_project_name = re.sub(r'[^a-zA-Z0-9_-]+', '_', raw_name).strip('_')
            if not safe_project_name: QMessageBox.warning(self.main_window, "Invalid Name", f"Project name cannot be empty after sanitization.\nOriginal name: '{raw_name}'"); return
            if safe_project_name != raw_name: QMessageBox.information(self.main_window, "Name Sanitized", f"Project name was sanitized to:\n'{safe_project_name}'")
            if safe_project_name in ['.', '..']: QMessageBox.warning(self.main_window, "Invalid Name", f"Project name cannot be '.' or '..'."); return
            print(f"Attempting to create project: '{safe_project_name}'")
            try:
                if project_manager.create_project(safe_project_name):
                    self.log_to_console(f"Project '{safe_project_name}' created."); self.load_project_list(); items = self.main_window.project_list_widget.findItems(safe_project_name, Qt.MatchFlag.MatchExactly)
                    if items: self.main_window.project_list_widget.setCurrentItem(items[0])
                    else: print(f"Warning: Could not find newly created project '{safe_project_name}' in list after refresh."); self.clear_project_view()
                else: QMessageBox.critical(self.main_window, "Error", f"Failed to create project '{safe_project_name}'. It might already exist or creation failed (check logs).")
            except Exception as e: QMessageBox.critical(self.main_window, "Creation Error", f"Error creating project '{safe_project_name}':\n{e}"); self.log_to_console(f"EXCEPTION during project creation:\n{traceback.format_exc()}")

    def confirm_delete_project(self):
        # (Logique inchangée)
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot delete project while a task is running."); return
        selected_item = mw.project_list_widget.currentItem(); project_name: Optional[str] = None
        if selected_item: is_placeholder = selected_item.text() in ["No projects found", "Error loading list"];
        if bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable) and not is_placeholder: project_name = selected_item.text()
        if not project_name: QMessageBox.warning(mw, "No Project Selected", "Select a valid project to delete."); return
        project_path_str = "N/A";
        try: project_path_str = project_manager.get_project_path(project_name)
        except ValueError as ve: QMessageBox.critical(mw, "Error", f"Cannot resolve path for project '{project_name}': {ve}"); return
        except Exception as e: print(f"Error resolving path for deletion: {e}"); project_path_str = f"Error resolving path: {e}"
        reply = QMessageBox.warning(mw, "Confirm Deletion", f"Permanently delete project '{project_name}'?\nLocation: {project_path_str}\n\nTHIS CANNOT BE UNDONE.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
                    print(f"Confirmed deletion for '{project_name}'.")
                    self.log_to_status(f"--- Deleting project '{project_name}'... ---")
                    self.set_ui_enabled(False, "Deleting project")
                    QApplication.processEvents()
                    deleted = False
                    error_msg = ""
                    try:
                        deleted = project_manager.delete_project(project_name)
                        if not deleted:
                            error_msg = f"Deletion failed for '{project_name}'. Project manager reported failure."
                            print(error_msg)
                    except Exception as e:
                        error_msg = f"Exception during deletion of '{project_name}': {e}"
                        print(f"EXCEPTION during delete project:\n{traceback.format_exc()}")
                    finally:
                        self._current_task_phase = TASK_IDLE
                        if deleted:
                            self.log_to_console(f"Project '{project_name}' deleted.")
                            self.log_to_status(f"--- Project '{project_name}' deleted. ---")
                        if self.current_project == project_name:
                            self.clear_project_view()
                            self.load_project_list()
                        else:
                            if not error_msg:
                                error_msg = f"Deletion failed for '{project_name}' (unknown reason)."
                            QMessageBox.critical(mw, "Deletion Error", error_msg)
                            self.log_to_console(error_msg)
                            self.log_to_status(f"--- ERROR deleting '{project_name}'. ---")
                            self.load_project_list()
                        self.set_ui_enabled(True)
        else:
            self.log_to_status("Project deletion cancelled.")

    def save_current_code(self):
        # (Logique inchangée)
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot save code while a task is running."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project Loaded", "Select a project to save code."); return
        code = mw.code_editor_text.toPlainText(); print(f"[GUI Handler] Attempting to save code for '{self.current_project}'. Length: {len(code)}")
        try:
            if project_manager.save_project_script_content(self.current_project, code): self.log_to_console(f"Code saved for project '{self.current_project}'."); self.log_to_status("Code saved.")
            else: QMessageBox.critical(mw, "Save Error", f"Failed to save code for '{self.current_project}'. Check logs.")
        except Exception as e: print(f"EXCEPTION during save: {e}"); self.log_to_console(traceback.format_exc()); QMessageBox.critical(mw, "Save Error", f"Error saving code:\n{e}")

    def run_current_project_script(self, called_from_chain: bool = False):
        # (Logique inchangée)
        mw = self.main_window;
        if not called_from_chain and self._is_busy: QMessageBox.warning(mw, "Busy", f"Cannot run script while task '{self._current_task_phase}' is running."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project", "Select project"); return
        script_name = DEFAULT_MAIN_SCRIPT;
        try: project_path = project_manager.get_project_path(self.current_project)
        except Exception as e: QMessageBox.critical(mw, "Error", f"Cannot run script: {e}"); return
        self.log_to_console(f"\n--- Running script: {self.current_project}/{script_name} ---"); self.log_to_status(f"Running {script_name}...")
        started = self.start_worker(task_type=TASK_RUN_SCRIPT, task_callable=utils.run_project_script, project_path=project_manager.get_project_path(self.current_project), script_name=script_name)
        if not started: self.log_to_console("--- Could not start script execution. Reverting. ---")

    # def start_correction_worker(self): # Remplacé par l'enchaînement direct vers STREAM
    #     pass

    # ----------------------------------------------------------------------
    # --- Exportation (inchangé) ---
    # ----------------------------------------------------------------------
    def prompt_export_project(self):
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot export now."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project", "Select project"); return
        current_os = platform.system(); reply = QMessageBox.question(mw, "Confirm Export", f"Export '{self.current_project}' as executable for {current_os}?\n(Uses PyInstaller, can take time)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No: self.log_to_status("Executable export cancelled."); return
        default_filename = f"{self.current_project}_{current_os.lower()}.zip"; output_zip_path, _ = QFileDialog.getSaveFileName(mw, "Save Executable Bundle As", default_filename, "Zip Files (*.zip)")
        if output_zip_path:
            if not output_zip_path.lower().endswith(".zip"): output_zip_path += ".zip"
            print(f"Starting export '{self.current_project}' to '{output_zip_path}'"); self.log_to_status(f"--- Starting executable export... ---"); self.log_to_console(f"--- Exporting '{self.current_project}' to '{output_zip_path}' ---"); self.start_export_worker(output_zip_path)
        else: self.log_to_status("Executable export cancelled.")

    def start_export_worker(self, output_zip_path: str):
        if not self.current_project: return
        started = self.start_worker(TASK_EXPORT_PROJECT, exporter.create_executable_bundle, project_name=self.current_project, output_zip_path=output_zip_path)
        if not started: self.log_to_status("! Error starting executable export (Busy?)."); QMessageBox.critical(self.main_window, "Export Error", "Could not start export."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

    def prompt_export_source_distribution(self):
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot export now."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project", "Select project"); return
        default_filename = f"{self.current_project}_source.zip"; output_zip_path, _ = QFileDialog.getSaveFileName(mw, "Save Source Distribution As", default_filename, "Zip Files (*.zip)")
        if output_zip_path:
            if not output_zip_path.lower().endswith(".zip"): output_zip_path += ".zip"
            print(f"Starting source export '{self.current_project}' to '{output_zip_path}'"); self.log_to_status(f"--- Starting source export... ---"); self.log_to_console(f"--- Exporting source '{self.current_project}' to '{output_zip_path}' ---"); self.start_source_export_worker(output_zip_path)
        else: self.log_to_status("Source export cancelled.")

    def start_source_export_worker(self, output_zip_path: str):
        if not self.current_project: return
        started = self.start_worker(TASK_EXPORT_SOURCE, exporter.create_source_distribution, project_name=self.current_project, output_zip_path=output_zip_path)
        if not started: self.log_to_status("! Error starting source export (Busy?)."); QMessageBox.critical(self.main_window, "Export Error", "Could not start source export."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

    # ----------------------------------------------------------------------
    # --- Installation Manuelle & Sauvegarde Logs (inchangé) ---
    # ----------------------------------------------------------------------
    def install_specific_dependencies(self):
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot install dependencies now."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project Selected", "Select project"); return
        deps_string = mw.install_deps_input.text().strip();
        if not deps_string: QMessageBox.information(mw, "Input Needed", "Enter package names"); return
        dependencies_to_install = [dep for dep in deps_string.split() if dep];
        if not dependencies_to_install: QMessageBox.information(mw, "Input Needed", "No valid package names"); return
        self.log_to_status(f"--- Starting manual install for: {dependencies_to_install} in '{self.current_project}'... ---"); self.log_to_console(f"--- Installing specific dependencies: {dependencies_to_install} ---")
        try:
            project_path = project_manager.get_project_path(self.current_project);
            if not os.path.isdir(project_path): raise FileNotFoundError(f"Project directory not found: {project_path}")
            started = self.start_worker(task_type=TASK_INSTALL_DEPS, task_callable=utils.install_project_dependencies, project_path=project_path, dependencies=dependencies_to_install)
            if started: mw.install_deps_input.clear()
            else: self.log_to_status("! Failed to start dependency installation worker.")
        except Exception as e: error_msg = f"Error preparing manual dependency install: {e}"; print(error_msg); self.log_to_console(f"--- ERROR preparing install: {error_msg} ---"); traceback.print_exc(); QMessageBox.critical(mw, "Install Error", error_msg)

    def save_logs_to_file(self):
        mw = self.main_window;
        if self._is_busy: QMessageBox.warning(mw, "Busy", "Cannot save logs now."); return
        ts = utils.get_timestamp().replace(":", "-").replace(".", "-"); default_filename = f"pythautom_logs_{ts}.log"; log_file_path, _ = QFileDialog.getSaveFileName(mw, "Save Logs As", default_filename, "Log Files (*.log);;Text Files (*.txt);;All Files (*)")
        if log_file_path:
            try:
                status_log_content = mw.status_log_text.toPlainText(); execution_log_content = mw.execution_log_text.toPlainText();
                full_log_content = f"=== STATUS ===\n{status_log_content}\n\n=== EXECUTION/OTHER ===\n{execution_log_content}\n=== END ==="
                with open(log_file_path, 'w', encoding='utf-8') as f: f.write(full_log_content)
                self.log_to_status(f"Logs saved successfully to '{os.path.basename(log_file_path)}'."); QMessageBox.information(mw, "Logs Saved", f"Logs successfully saved to:\n{log_file_path}")
            except Exception as e: error_msg = f"Error saving logs to '{log_file_path}': {e}"; print(error_msg); traceback.print_exc(); QMessageBox.critical(mw, "Save Error", error_msg); self.log_to_status(f"! Error saving logs: {e}")
        else: self.log_to_status("Log saving cancelled by user.")

    # ----------------------------------------------------------------------
    # --- Métadonnées & Structure Projet (inchangé) ---
    # ----------------------------------------------------------------------
    def update_project_metadata_deps(self):
        if not self.current_project: return
        try: metadata = project_manager.load_project_metadata(self.current_project); metadata["dependencies"] = sorted(list(set(self._project_dependencies))); project_manager.save_project_metadata(self.current_project, metadata); print(f"Updated metadata dependencies for {self.current_project}: {metadata['dependencies']}"); self.log_to_console(f"Project metadata updated with dependencies: {metadata['dependencies']}")
        except Exception as e: msg = f"Warning: Failed to update project metadata dependencies for '{self.current_project}': {e}"; print(msg); self.log_to_console(msg)

    def add_file_to_project(self):
        if self._is_busy: QMessageBox.warning(self.main_window, "Busy", "Cannot add file now."); return
        if not self.current_project: QMessageBox.warning(self.main_window, "No Project", "Select project"); return
        file_path, _ = QFileDialog.getOpenFileName(self.main_window, "Select File to Add", "", "All Files (*)")
        if file_path: self._copy_item_to_project(file_path, is_directory=False)

    def add_folder_to_project(self):
        if self._is_busy: QMessageBox.warning(self.main_window, "Busy", "Cannot add folder now."); return
        if not self.current_project: QMessageBox.warning(self.main_window, "No Project", "Select project"); return
        folder_path = QFileDialog.getExistingDirectory(self.main_window, "Select Folder to Add", "")
        if folder_path: self._copy_item_to_project(folder_path, is_directory=True)

    def _copy_item_to_project(self, source_path: str, is_directory: bool):
        # (Logique inchangée)
        if not self.current_project: return
        try:
            project_path = project_manager.get_project_path(self.current_project); item_name = os.path.basename(source_path); destination_path = os.path.join(project_path, item_name);
            if os.path.exists(destination_path):
                reply = QMessageBox.question(self.main_window, "Confirm Overwrite", f"'{item_name}' exists. Overwrite?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.No: self.log_to_status(f"Skipped adding '{item_name}'."); return
                else: 
                    try: (shutil.rmtree if os.path.isdir(destination_path) else os.remove)(destination_path); self.log_to_console(f"Overwriting existing: {item_name}") 
                    except Exception as rm_err: QMessageBox.critical(self.main_window, "Error", f"Could not remove existing '{item_name}':\n{rm_err}"); return
            import fnmatch; should_exclude = any(fnmatch.fnmatch(item_name, pattern) for pattern in project_manager.EXCLUDE_PATTERNS_FOR_LISTING);
            if should_exclude: QMessageBox.warning(self.main_window, "Cannot Add", f"'{item_name}' matches an exclusion pattern."); self.log_to_status(f"Skipped excluded item: {item_name}"); return
            self.log_to_status(f"Copying '{item_name}' to project '{self.current_project}'..."); QApplication.processEvents()
            if is_directory: shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
            else: shutil.copy2(source_path, destination_path)
            self.log_to_status(f"Successfully added '{item_name}' to the project."); self.log_to_console(f"Added item to project: {destination_path}")
        except ValueError as e: QMessageBox.critical(self.main_window, "Error", f"Cannot get project path: {e}")
        except Exception as e: QMessageBox.critical(self.main_window, "Copy Error", f"Failed copy '{os.path.basename(source_path)}':\n{e}"); self.log_to_status(f"Error adding '{os.path.basename(source_path)}'."); self.log_to_console(f"EXCEPTION during copy:\n{traceback.format_exc()}")

    def _generate_project_structure_info(self) -> Optional[str]:
        # (Logique inchangée)
        if not self.current_project: return None
        try:
            contents = project_manager.get_project_contents(self.current_project);
            if not contents: return "(Project appears empty besides the main script)"
            structure_lines = [];
            for rel_path, item_type in contents: indent_level = rel_path.count('/'); indent = "  " * indent_level; prefix = "[D] " if item_type == 'dir' else ("[F] " if item_type == 'file' else "    "); base_name = os.path.basename(rel_path) if item_type != 'info' else "..."; structure_lines.append(f"{indent}{prefix}{base_name}")
            full_info = "\n".join(structure_lines);
            if len(full_info) > MAX_STRUCTURE_INFO_LENGTH: print("Warning: Project structure info truncated for LLM context."); return full_info[:MAX_STRUCTURE_INFO_LENGTH] + "\n[... Structure truncated ...]"
            else: return full_info
        except Exception as e: self.log_to_console(f"Error generating project structure info: {e}"); traceback.print_exc(); return f"(Error retrieving project structure: {e})"

    # ----------------------------------------------------------------------
    # --- Gestion Fermeture (inchangé) ---
    # ----------------------------------------------------------------------
    def handle_close_event(self, event):
        # (Logique inchangée)
        confirm_needed = self._is_busy; reply = QMessageBox.StandardButton.Yes
        if confirm_needed: reply = QMessageBox.question(self.main_window, 'Confirm Exit', f"Task ({self._current_task_phase}) is running.\nExit now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            print("Closing application...")
            if self.thread and self.thread.isRunning() and self.worker: print("Attempting to cancel background task..."); self._was_cancelled_by_user = True; self.worker.cancel() # <<< Indique annulation à la fermeture
            event.accept()
        else: print("Application close cancelled."); event.ignore()

# --- Fin de la classe GuiActionsHandler ---