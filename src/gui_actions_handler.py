# src/gui_actions_handler.py

import sys
import platform
import functools
import os
import subprocess
import re
import traceback
import ast # Pour l'analyse des listes de dépendances depuis le LLM
from typing import List, Any, Optional, Dict, Callable, Type, Tuple
import typing # Pour la vérification de type et éviter les imports circulaires

from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox,
    QApplication, QListWidgetItem, QFileDialog, QCheckBox, QSpinBox # Ajout QCheckBox/SpinBox car utilisés dans set_ui_enabled
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer, QObject # QObject ré-ajouté car utilisé par Worker
from PyQt6.QtGui import QTextCursor, QFont, QIntValidator # Ajout des imports nécessaires pour les widgets utilisés par set_ui_enabled

# Import des composants nécessaires depuis les autres modules
from . import project_manager
from . import utils
from . import exporter
from .llm_interaction import (
    BaseLLMClient, LMStudioClient, GeminiClient,
    DEFAULT_LM_STUDIO_IP, DEFAULT_LM_STUDIO_PORT, DEFAULT_GEMINI_MODEL,
    AVAILABLE_GEMINI_MODELS, GOOGLE_GENAI_AVAILABLE
)
from .project_manager import DEFAULT_MAIN_SCRIPT

# Import de MainWindow uniquement pour la vérification de type afin d'éviter l'import circulaire
if typing.TYPE_CHECKING:
    from .gui_main_window import MainWindow

# --- CONSTANTES ---
TASK_IDLE = "idle"
TASK_INSTALL_DEPS = "install_deps"
TASK_GENERATE_CODE = "generate_code" # Utilisé SEULEMENT pour l'auto-correction (non-streaming)
TASK_RUN_SCRIPT = "run_script"
TASK_ATTEMPT_CONNECTION = "attempt_connection"
TASK_EXPORT_PROJECT = "export_project"
# Workflow: ID_DEPS_REQ -> GENERATE_CODE_STREAM -> INSTALL_DEPS (si nécessaire)
TASK_IDENTIFY_DEPS_FROM_REQUEST = "identify_deps_from_request" # Nouvelle Étape 1
TASK_GENERATE_CODE_STREAM = "generate_code_stream_with_deps" # Nouvelle Étape 2 (Streaming)


LLM_BACKEND_LMSTUDIO = "LM Studio"
LLM_BACKEND_GEMINI = "Google Gemini"

DEFAULT_MAX_CORRECTION_ATTEMPTS = 2
STREAM_UPDATE_INTERVAL_MS = 50

# --- Worker Thread ---
class Worker(QObject):
    finished = pyqtSignal()
    log_message = pyqtSignal(str, str) # message, source ('status', 'console')
    chat_fragment_received = pyqtSignal(str) # Pour generate_code_stream_with_deps
    result = pyqtSignal(str, object) # task_type, actual_result

    def __init__(self, task_type: str, task_callable: Callable, *args, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.task_callable = task_callable
        self.args = args
        self.kwargs = kwargs
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        self.log_message.emit(f"Task '{self.task_type}' cancellation requested...", 'status')
        print(f"[Worker {id(self)}] Cancellation flag set.")

    def _emit_log(self, message: str, source: str = 'status'):
        self.log_message.emit(message, source)

    def run(self):
        print(f"[Worker {id(self)}] STARTING task type: '{self.task_type}', callable: {self.task_callable.__name__}")
        self._emit_log(f"Starting: {self.task_type}...", 'status')
        self._is_cancelled = False
        task_result: Any = None
        msg = ""
        try:
            if self._is_cancelled: raise InterruptedError("Cancelled before execution")

            actual_kwargs = self.kwargs.copy()
            console_logger = functools.partial(self._emit_log, source='console')
            status_logger = functools.partial(self._emit_log, source='status')

            # Injecte le callback de progression pour les logs console
            if self.task_type in [TASK_INSTALL_DEPS, TASK_EXPORT_PROJECT, TASK_RUN_SCRIPT]:
                 actual_kwargs['progress_callback'] = console_logger

            # Injecte le callback de fragment pour le streaming de chat
            if self.task_type == TASK_GENERATE_CODE_STREAM:
                def _fragment_emitter(fragment: str):
                    if not self._is_cancelled:
                        self.chat_fragment_received.emit(fragment)
                actual_kwargs['fragment_callback'] = _fragment_emitter

            # --- Exécute la Tâche ---
            task_result = self.task_callable(*self.args, **actual_kwargs)

            # --- Définit le Message de Complétion ---
            if self.task_type == TASK_INSTALL_DEPS:
                msg = f"Dependency Install {'OK' if task_result else 'failed'}."
            elif self.task_type == TASK_GENERATE_CODE: # Génération de code pour Auto-Correction
                 msg = "Auto-correction code generation finished."
            elif self.task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST:
                 msg = "Dependency identification (from request) finished."
            elif self.task_type == TASK_GENERATE_CODE_STREAM:
                 msg = "Code generation stream finished."
            elif self.task_type == TASK_RUN_SCRIPT:
                msg = "Script execution finished."
            elif self.task_type == TASK_ATTEMPT_CONNECTION:
                msg = f"LLM Connection attempt finished ({'Success' if task_result else 'Failed'})."
            elif self.task_type == TASK_EXPORT_PROJECT:
                msg = f"Export process finished ({'Success' if task_result else 'Failed'})."
            else:
                msg = f"Task '{self.task_type}' finished (unknown type)."


            # --- Gère l'Annulation & Émet le Résultat ---
            if self._is_cancelled:
                print(f"Task '{self.task_type}' finished but was cancelled.")
                status_logger(f"Task '{self.task_type}' cancelled.")
            else:
                status_logger(msg)
                self.result.emit(self.task_type, task_result)

        except InterruptedError as ie:
            print(f"Task '{self.task_type}' interrupted: {ie}")
            status_logger(f"Task '{self.task_type}' cancelled.")
        except Exception as e:
            if not self._is_cancelled:
                error_msg = f"Error in worker task '{self.task_type}': {e}"
                print(f"EXCEPTION:\n{traceback.format_exc()}")
                console_logger(f"--- Worker Error ---")
                console_logger(f"Task: {self.task_type}")
                console_logger(traceback.format_exc())
                console_logger(f"--- End Worker Error ---")
                status_logger(f"Error: {self.task_type} failed ({type(e).__name__}). See console log.")
                self.result.emit(self.task_type, e) # Émet l'erreur comme résultat
            else:
                print(f"Exception ({e}) occurred but task was cancelled.")
        finally:
            print(f"[Worker {id(self)}] FINISHED task '{self.task_type}'. Emitting finished (Cancelled={self._is_cancelled}).")
            self.finished.emit()


# --- Classe de Gestion des Actions ---
class GuiActionsHandler:
    # --- Attributs d'État ---
    _current_task_phase: str = TASK_IDLE
    _last_user_chat_message: str = ""
    _project_dependencies: List[str] = [] # Dépendances connues pour le projet chargé
    _deps_identified_for_next_step: List[str] = [] # Stockage temporaire des deps identifiées
    _pending_install_deps: List[str] = [] # Dépendances nécessitant une installation
    _code_to_correct: Optional[str] = None
    _last_execution_error: Optional[str] = None
    _correction_attempts: int = 0
    _chat_fragment_buffer: str = ""
    _chat_update_timer: QTimer
    _next_logical_phase_after_result: str = TASK_IDLE

    # --- Client & Threading ---
    current_project: Optional[str] = None
    llm_client: Optional[BaseLLMClient] = None
    thread: Optional[QThread] = None
    worker: Optional[Worker] = None

    # Ajout des constantes TASK comme attributs de classe
    TASK_IDLE = TASK_IDLE
    TASK_INSTALL_DEPS = TASK_INSTALL_DEPS
    TASK_GENERATE_CODE = TASK_GENERATE_CODE
    TASK_RUN_SCRIPT = TASK_RUN_SCRIPT
    TASK_ATTEMPT_CONNECTION = TASK_ATTEMPT_CONNECTION
    TASK_EXPORT_PROJECT = TASK_EXPORT_PROJECT
    TASK_IDENTIFY_DEPS_FROM_REQUEST = TASK_IDENTIFY_DEPS_FROM_REQUEST
    TASK_GENERATE_CODE_STREAM = TASK_GENERATE_CODE_STREAM

    def __init__(self, main_window: 'MainWindow'):
        """Initialise le gestionnaire avec une référence à la fenêtre principale."""
        self.main_window = main_window # Référence à l'instance de la fenêtre principale

        # Initialisation des attributs
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

        # Timer pour les mises à jour bufferisées du chat
        self._chat_update_timer = QTimer()
        self._chat_update_timer.setInterval(STREAM_UPDATE_INTERVAL_MS)
        self._chat_update_timer.timeout.connect(self._process_chat_buffer)

    # --- Gestion du Worker ---
    def start_worker(self, task_type: str, task_callable: Callable, *args, **kwargs) -> bool:
        """Démarre une tâche en arrière-plan dans un QThread."""
        if self.thread is not None and self.thread.isRunning():
            msg = f"Warning: Task '{task_type}' requested, but previous task '{self._current_task_phase}' is still active."
            print(msg)
            self.log_to_status(msg)
            QMessageBox.warning(self.main_window, "Busy", "Another task is already running. Please wait.")
            return False

        self._current_task_phase = task_type
        self.set_ui_enabled(False, task_type) # Désactive l'UI

        self.thread = QThread()
        self.thread.setObjectName(f"WorkerThread_{task_type}_{id(self.thread)}")
        self.worker = Worker(task_type, task_callable, *args, **kwargs)
        self.worker.moveToThread(self.thread)

        # Connexion des signaux
        self.worker.log_message.connect(self._handle_worker_log)
        self.worker.result.connect(self.handle_worker_result)
        self.worker.chat_fragment_received.connect(self._buffer_chat_fragment)
        self.worker.finished.connect(self.thread.quit)
        # Utilise lambda pour éviter les problèmes d'arguments si deleteLater est appelé directement
        self.worker.finished.connect(lambda: self.worker.deleteLater() if self.worker else None)
        self.thread.finished.connect(lambda: self.thread.deleteLater() if self.thread else None)

        # Utilise functools.partial pour passer le type de tâche terminé au gestionnaire
        on_finished_with_task = functools.partial(self._on_thread_finished, finished_task_type=task_type)
        self.thread.finished.connect(on_finished_with_task)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

        # Démarre le timer de mise à jour du chat uniquement pour la tâche de streaming de code
        if task_type == TASK_GENERATE_CODE_STREAM:
            self._chat_fragment_buffer = "" # Vide le buffer avant de commencer
            self._chat_update_timer.start()

        print(f"Worker started for task: {task_type} on thread {self.thread.objectName()}")
        return True

    def _on_thread_finished(self, finished_task_type: str):
        """Nettoie les références thread/worker et déclenche la tâche suivante si nécessaire."""
        sender_obj = QObject().sender() # Obtient l'objet QThread expéditeur
        thread_name = sender_obj.objectName() if sender_obj and isinstance(sender_obj, QThread) else "N/A"
        next_phase = self._next_logical_phase_after_result # Obtient la prochaine étape planifiée

        print(f"Thread '{thread_name}' finished. Task: '{finished_task_type}'. Next planned phase: '{next_phase}'. Cleaning refs.")

        # Arrête le timer de chat si c'était la tâche de streaming de code
        if finished_task_type == TASK_GENERATE_CODE_STREAM:
             self._process_chat_buffer() # Traite tout buffer restant
             self._chat_update_timer.stop()
             print("Chat update timer stopped.")

        self.thread = None
        self.worker = None
        print("GUI refs to worker/thread cleaned.")

        # Réinitialise l'indicateur de phase suivante *avant* de potentiellement démarrer la tâche suivante
        self._next_logical_phase_after_result = TASK_IDLE

        try:
            # --- Logique d'Enchaînement des Tâches ---
            if next_phase == TASK_GENERATE_CODE_STREAM:
                # Déclenché après TASK_IDENTIFY_DEPS_FROM_REQUEST
                if self.current_project and self.llm_client and self.llm_client.is_available():
                    self.log_to_status(f"-> Generating code using identified dependencies: {self._deps_identified_for_next_step}...")
                    current_code = self.main_window.code_editor_text.toPlainText() # Obtient le code actuel pour contexte
                    if not self.start_worker(
                        task_type=TASK_GENERATE_CODE_STREAM,
                        task_callable=self.llm_client.generate_code_stream_with_deps,
                        user_request=self._last_user_chat_message, # Utilise la requête stockée
                        project_name=self.current_project,
                        current_code=current_code,
                        dependencies_to_use=self._deps_identified_for_next_step # Utilise les deps stockées
                        # fragment_callback injecté par start_worker
                    ):
                        self.log_to_status("! Error starting code generation worker.")
                        self._current_task_phase = TASK_IDLE
                        self.set_ui_enabled(True)
                        # Vide les deps temporaires si le démarrage du worker échoue
                        self._deps_identified_for_next_step = [] # Vide ici en cas d'échec
                else:
                    self.log_to_status("! Skipping code generation (missing project/LLM).")
                    self._current_task_phase = TASK_IDLE
                    self.set_ui_enabled(True)
                    # Vide la liste temporaire des deps si on saute l'étape
                    self._deps_identified_for_next_step = [] # Vide ici aussi
                # NOTE: Ne PAS vider self._deps_identified_for_next_step ici si démarré avec succès

            elif next_phase == TASK_INSTALL_DEPS:
                # Déclenché après TASK_GENERATE_CODE_STREAM si nécessaire
                if self._pending_install_deps and self.current_project:
                    self.log_to_status(f"-> Installing dependencies: {self._pending_install_deps}...")
                    self.log_to_console(f"--- Auto-starting installation for: {self._pending_install_deps} ---")
                    project_path = project_manager.get_project_path(self.current_project)
                    if not self.start_worker(
                        task_type=TASK_INSTALL_DEPS,
                        task_callable=utils.install_project_dependencies,
                        project_path=project_path,
                        dependencies=self._pending_install_deps):
                        self.log_to_console("! Error starting install worker.")
                        self.log_to_status("! Error starting dependency installation worker.")
                        self._current_task_phase = TASK_IDLE
                        self.set_ui_enabled(True)
                else:
                    self.log_to_status("-> Skipping install (no pending deps or project).")
                    self.log_to_console("-> Skipping install (no pending deps or project).")
                    self._current_task_phase = TASK_IDLE
                    self.set_ui_enabled(True)

            elif next_phase == TASK_GENERATE_CODE: # Déclencheur d'auto-correction
                if not self.start_correction_worker():
                    self.log_to_status("! Error starting correction worker.")
                    self.log_to_console("! Error starting correction worker.")
                    self._current_task_phase = TASK_IDLE
                    self.set_ui_enabled(True)

            elif next_phase == TASK_RUN_SCRIPT: # Exécution après auto-correction
                 self.log_to_status("-> Automatically running script after correction.")
                 self.run_current_project_script(called_from_chain=True)

            # Gère le cas où l'identification des deps s'exécute mais aucune génération de code n'est nécessaire (ex: erreur)
            elif finished_task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST and next_phase == TASK_IDLE:
                print(f"Finished task '{finished_task_type}'. Next phase is IDLE. Cleaning up temp deps.")
                self._deps_identified_for_next_step = [] # Nettoie les deps temporaires
                self._current_task_phase = TASK_IDLE
                self.set_ui_enabled(True) # Réactive l'UI

            else: # TASK_IDLE ou inattendu
                if next_phase != TASK_IDLE:
                     print(f"Warning: Unexpected next phase '{next_phase}' after task '{finished_task_type}'. Setting IDLE.")
                print(f"Finished task '{finished_task_type}'. No further chaining or unknown next phase. Setting state to IDLE.")
                # Nettoie les deps temporaires si on arrive ici de manière inattendue après l'étape d'ID Deps
                if finished_task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST:
                     self._deps_identified_for_next_step = []
                self._current_task_phase = TASK_IDLE
                self.set_ui_enabled(True) # Réactive l'UI

        except Exception as e:
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print(f"ERROR in _on_thread_finished chaining logic for '{finished_task_type}' -> '{next_phase}':")
            print(traceback.format_exc())
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            self.log_to_status(f"! Internal error during task chaining: {e}")
            self.log_to_console(f"! Internal error during task chaining: {e}\n{traceback.format_exc()}")
            # Assure la réinitialisation de l'état en cas d'erreur
            self._current_task_phase = TASK_IDLE
            self._next_logical_phase_after_result = TASK_IDLE
            self._deps_identified_for_next_step = [] # Vide l'état temporaire
            self.set_ui_enabled(True)


    def handle_worker_result(self, task_type: str, result: Any):
        """Traite les résultats des tâches en arrière-plan."""
        # Assure que ce résultat correspond à la phase de tâche actuellement active
        if task_type != self._current_task_phase:
            print(f"WARNING: Result received for task '{task_type}' but current phase is '{self._current_task_phase}'. Stale result ignored.")
            return

        print(f"[GUI handle] Task '{task_type}'. Phase: '{self._current_task_phase}'. Result type: {type(result)}")
        error_occurred = isinstance(result, Exception)
        next_phase = TASK_IDLE # État suivant par défaut, sauf modification par la logique ci-dessous

        try:
            # --- Connexion LLM ---
            if task_type == TASK_ATTEMPT_CONNECTION:
                llm_connected = not error_occurred and result is True
                status = "Unknown"; color = "orange"; backend_name = "N/A"
                if self.llm_client: backend_name = self.llm_client.get_backend_name()

                if llm_connected:
                    status = f"Connected to {backend_name}"; color = "green"
                    self.log_to_status(f"LLM Connection Successful ({backend_name})")
                else:
                    self.log_to_status(f"LLM Connection Failed ({backend_name})")
                    if error_occurred:
                        status = f"Error ({backend_name})"; color = "red"
                        self.log_to_console(f"LLM Connection Error ({backend_name}): {result}")
                    else: status = f"Failed ({backend_name})"; color = "red"
                    self.llm_client = None # Vide le client en cas d'échec

                self.main_window.llm_status_label.setText(f"LLM Status: {status}")
                self.main_window.llm_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                next_phase = TASK_IDLE

            # --- Étape 1: Identification des Dépendances (Depuis la Requête) ---
            elif task_type == TASK_IDENTIFY_DEPS_FROM_REQUEST:
                if error_occurred:
                    self.log_to_status(f"Error identifying dependencies from request: {result}")
                    self.log_to_console(f"LLM Dependency ID (Request) Error:\n{result}")
                    self.append_to_chat("System", f"Error identifying dependencies: {result}")
                    self._deps_identified_for_next_step = [] # Vide l'état temporaire en cas d'erreur
                    next_phase = TASK_IDLE # Arrête le workflow
                elif isinstance(result, list):
                    self.log_to_status("Dependencies identified from request. Proceeding...")
                    # Le résultat doit être la liste de chaînes (ou une liste contenant des messages d'erreur)
                    identified_deps = [dep for dep in result if not dep.startswith("ERROR:")]
                    errors = [dep for dep in result if dep.startswith("ERROR:")]

                    if errors:
                         error_str = "; ".join(errors)
                         self.log_to_console(f"Dependency ID Warning/Error: {error_str}")
                         self.append_to_chat("System", f"Warning/Error during dependency check: {error_str}")
                         # Continue seulement si des deps valides ont été trouvées malgré les erreurs

                    # Stocke ces deps pour être utilisées dans la prochaine étape (génération de code)
                    self._deps_identified_for_next_step = sorted(list(set(identified_deps)))
                    dep_msg = f"Identified required dependencies: {self._deps_identified_for_next_step or 'None'}"
                    self.log_to_console(dep_msg)
                    self.append_to_chat("System", dep_msg)

                    # Déclenche la génération de code maintenant
                    next_phase = TASK_GENERATE_CODE_STREAM # Enchaîne vers la génération de code
                else:
                    self.log_to_status(f"Unexpected result type for dependency ID (request): {type(result)}")
                    self.append_to_chat("System", f"Unexpected result type from dependency check: {type(result)}")
                    self._deps_identified_for_next_step = [] # Vide l'état temporaire
                    next_phase = TASK_IDLE

            # --- Étape 2: Stream de Génération de Code ---
            elif task_type == TASK_GENERATE_CODE_STREAM:
                self.append_to_chat("System", "(Code stream finished, processing result...)")
                if error_occurred:
                    self.log_to_status(f"Error during code generation stream: {result}")
                    self.log_to_console(f"LLM Code Generation Stream Error:\n{result}") # Worker a loggé la traceback
                    self.append_to_chat("System", f"Error during code generation process: {result}")
                    next_phase = TASK_IDLE
                    # Vide les deps temporaires en cas d'erreur
                    self._deps_identified_for_next_step = [] # <-- Vide ici
                elif isinstance(result, str):
                    self.log_to_status("Code stream finished. Cleaning and updating editor...")
                    # Utilise la fonction de nettoyage améliorée
                    cleaned_code = self._cleanup_llm_code_output(result)
                    self.main_window.code_editor_text.setPlainText(cleaned_code)
                    self.log_to_console(f"Code updated in editor from chat generation.")
                    self.append_to_chat("System", "(Code updated in editor)")

                    # Vérifie maintenant si les dépendances PRÉCÉDEMMENT identifiées nécessitent une installation
                    current_proj_deps_set = set(self._project_dependencies)
                    # Utilise les deps stockées de l'Étape 1
                    needed_deps_set = set(self._deps_identified_for_next_step) # <-- LIT la valeur stockée

                    # --- VIDE LA LISTE TEMP ICI ---
                    # Vide la liste temporaire *après* l'avoir utilisée pour la vérification
                    print(f"Clearing temporary deps list: {self._deps_identified_for_next_step}")
                    self._deps_identified_for_next_step = []
                    # ------------------------

                    new_deps_to_install = sorted(list(needed_deps_set - current_proj_deps_set))

                    if new_deps_to_install:
                        self.log_to_status(f"Dependencies require installation: {new_deps_to_install}")
                        self._pending_install_deps = new_deps_to_install # Définit la liste en attente
                        # Met à jour la liste principale des deps du projet de manière optimiste *avant* l'installation
                        self._project_dependencies = sorted(list(needed_deps_set))
                        self.update_project_metadata_deps() # Sauvegarde dans les métadonnées
                        next_phase = TASK_INSTALL_DEPS # Déclenche l'installation
                    else:
                        self.log_to_status("Dependencies identified are already met or not needed.")
                        # Assure que les deps du projet reflètent celles identifiées pour cette requête
                        if set(self._project_dependencies) != needed_deps_set:
                             self._project_dependencies = sorted(list(needed_deps_set))
                             self.update_project_metadata_deps()
                        next_phase = TASK_IDLE # Aucune installation nécessaire
                else:
                    self.log_to_status(f"Unexpected result type after code generation stream: {type(result)}")
                    self.append_to_chat("System", f"Unexpected result type from LLM: {type(result)}")
                    next_phase = TASK_IDLE
                    # Vide les deps temporaires en cas de type de résultat inattendu
                    self._deps_identified_for_next_step = [] # <-- Vide ici aussi


            # --- Étape 3: Installation des Dépendances ---
            elif task_type == TASK_INSTALL_DEPS:
                install_successful = not error_occurred and result is True
                if install_successful:
                    self.log_to_status("Dependencies installed successfully.")
                    self.log_to_console("--- Dependency installation successful ---")
                    # La liste des dépendances du projet (_project_dependencies) et les métadonnées
                    # ont déjà été mises à jour de manière optimiste avant le début de l'installation.
                    # Il suffit de vider la liste en attente.
                    self._pending_install_deps = []
                    next_phase = TASK_IDLE
                else:
                    failed_deps = self._pending_install_deps # Se souvient de celles qui ont échoué
                    self.log_to_status(f"Error installing dependencies: {failed_deps}. Check console log.")
                    self.log_to_console(f"--- ERROR installing dependencies: {failed_deps} ---")
                    if error_occurred: self.log_to_console(f"Error details: {result}")
                    # Que faire avec _project_dependencies ? Revenir en arrière ? Difficile.
                    # Pour l'instant, laissons tel quel, l'utilisateur devra peut-être corriger manuellement le venv ou les métadonnées.
                    self._pending_install_deps = [] # Vide la liste en attente pour éviter les boucles
                    next_phase = TASK_IDLE

            # --- Génération de Code pour Auto-Correction ---
            elif task_type == TASK_GENERATE_CODE:
                 if error_occurred:
                     self.log_to_status(f"Error generating correction code: {result}")
                     self.log_to_console(f"Auto-Correction LLM Error:\n{result}")
                     self.main_window.code_editor_text.setPlainText(f"# LLM Correction Error:\n# {result}")
                     self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None
                     next_phase = TASK_IDLE
                 elif isinstance(result, str):
                     self.log_to_status("Correction code generated. Cleaning...")
                     cleaned_code = self._cleanup_llm_code_output(result)
                     self.main_window.code_editor_text.setPlainText(cleaned_code)
                     self.log_to_console("--- Code corrected by LLM. Updated in editor. ---")
                     self.log_to_status("Correction applied. -> Next: Re-run script to verify.")
                     self._code_to_correct = None
                     next_phase = TASK_RUN_SCRIPT # Déclenche une nouvelle exécution
                 else:
                     self.log_to_status(f"Unexpected result type for correction code gen: {type(result)}")
                     self.main_window.code_editor_text.setPlainText(f"# Unexpected LLM correction result type:\n# {type(result)}")
                     next_phase = TASK_IDLE

            # --- Exécution du Script ---
            elif task_type == TASK_RUN_SCRIPT:
                self.log_to_console(f"--- Script execution task finished ---")
                execution_successful = False
                if isinstance(result, subprocess.CompletedProcess):
                    if result.returncode == 0:
                        execution_successful = True
                        self.log_to_status("--- Script executed successfully! ---")
                        self.log_to_console("--- Script executed successfully! Process complete. ---")
                        self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None
                        next_phase = TASK_IDLE
                    else:
                        max_attempts = self.main_window.max_attempts_spinbox.value()
                        auto_correct_enabled = self.main_window.auto_correct_checkbox.isChecked()
                        if auto_correct_enabled and self._correction_attempts < max_attempts:
                            self._correction_attempts += 1
                            self.log_to_status(f"Script error. Auto-correcting (Attempt {self._correction_attempts}/{max_attempts})...")
                            self.log_to_console(f"--- Script error detected. Attempting correction ({self._correction_attempts}/{max_attempts})... ---")
                            self._code_to_correct = self.main_window.code_editor_text.toPlainText()
                            stderr_clean = result.stderr.strip() if result.stderr else ""
                            self._last_execution_error = stderr_clean if stderr_clean else f"Script failed with exit code: {result.returncode}"
                            next_phase = TASK_GENERATE_CODE # Déclenche la correction
                        else:
                            if auto_correct_enabled: self.log_to_status(f"Script error. Max correction attempts ({max_attempts}) reached.")
                            else: self.log_to_status("Script error. Auto-correction disabled.")
                            self.log_to_console(f"--- Script failed after {self._correction_attempts} attempts or auto-correct disabled. ---")
                            self._correction_attempts = 0; self._last_execution_error = None; self._code_to_correct = None
                            next_phase = TASK_IDLE
                elif error_occurred:
                    self.log_to_status("Error running script task. Check console log.")
                    self.log_to_console(f"--- ERROR running script task: {result} ---")
                    next_phase = TASK_IDLE
                else:
                    self.log_to_status("Unknown result type for run_script. Check console log.")
                    self.log_to_console(f"--- Unknown result type for run_script: {type(result)} ---")
                    next_phase = TASK_IDLE

            # --- Exportation du Projet ---
            elif task_type == TASK_EXPORT_PROJECT:
                 if error_occurred:
                     self.log_to_status(f"Export failed: {result}")
                     QMessageBox.critical(self.main_window, "Export Error", f"Failed to create executable bundle.\nError: {result}\nCheck console logs for details.")
                 elif result is True:
                     self.log_to_status("--- Project exported successfully. ---")
                     QMessageBox.information(self.main_window, "Export Successful", "Project exported successfully!")
                 else:
                     self.log_to_status("--- Project export failed. See console logs. ---")
                     QMessageBox.warning(self.main_window, "Export Warning", "Export process finished but reported failure. Check console logs.")
                 next_phase = TASK_IDLE

            else:
                self.log_to_status(f"--- Unhandled task result for task: {task_type} ---")
                self.log_to_console(f"--- Unhandled task result: {task_type}, Result: {result} ---")
                next_phase = TASK_IDLE

        except Exception as handler_ex:
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print(f"EXCEPTION in handle_worker_result for task '{task_type}':")
            print(traceback.format_exc())
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            self.log_to_status(f"! Internal error handling result: {handler_ex}")
            self.log_to_console(f"! Internal error handling result for {task_type}: {handler_ex}\n{traceback.format_exc()}")
            # Assure la réinitialisation de l'état en cas d'erreur de gestionnaire inattendue
            self._deps_identified_for_next_step = []
            next_phase = TASK_IDLE
        finally:
            # Stocke la prochaine phase déterminée pour _on_thread_finished
            self._next_logical_phase_after_result = next_phase
            print(f"Handler finished for '{task_type}'. Next logical phase stored as: '{next_phase}'")

    # --- Gestion de l'État de l'UI ---
    def set_ui_enabled(self, enabled: bool, current_task: Optional[str] = None):
        """Active/désactive les éléments de l'UI selon si une tâche est en cours."""
        mw = self.main_window
        llm_ok = self.llm_client is not None and self.llm_client.is_available()
        is_project_loaded = self.current_project is not None

        # Contrôles généraux
        mw.new_project_button.setEnabled(enabled)
        mw.project_list_widget.setEnabled(enabled)
        mw.llm_reconnect_button.setEnabled(enabled)
        mw.llm_backend_selector.setEnabled(enabled)

        # Contrôles spécifiques au backend
        selected_backend = mw.llm_backend_selector.currentText()
        can_edit_lmstudio = enabled and selected_backend == LLM_BACKEND_LMSTUDIO
        can_edit_gemini = enabled and selected_backend == LLM_BACKEND_GEMINI
        mw.llm_ip_input.setEnabled(can_edit_lmstudio)
        mw.llm_port_input.setEnabled(can_edit_lmstudio)
        mw.gemini_api_key_input.setEnabled(can_edit_gemini)
        mw.gemini_model_selector.setEnabled(can_edit_gemini)

        # Boutons d'action
        mw.run_script_button.setEnabled(enabled and is_project_loaded)
        mw.auto_correct_checkbox.setEnabled(enabled and is_project_loaded)
        mw.max_attempts_spinbox.setEnabled(enabled and is_project_loaded)
        mw.save_code_button.setEnabled(enabled and is_project_loaded)
        mw.code_editor_text.setReadOnly(not enabled or not is_project_loaded)

        # Contrôles du panneau de Chat
        can_chat = enabled and is_project_loaded and llm_ok
        mw.chat_input_text.setEnabled(can_chat)
        mw.chat_send_button.setEnabled(can_chat)
        mw.chat_send_button.setText("Send Request / Refine Code" if can_chat else "Processing...")

        # Boutons d'action du projet
        selected_item = mw.project_list_widget.currentItem()
        is_valid_selection = False
        if selected_item:
            item_is_selectable = bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable)
            is_placeholder = selected_item.text() in ["No projects found", "Error loading list"]
            is_valid_selection = item_is_selectable and not is_placeholder

        mw.delete_project_button.setEnabled(enabled and is_project_loaded and is_valid_selection)
        mw.export_button.setEnabled(enabled and is_project_loaded and is_valid_selection)

        # Curseur et message de statut
        if not enabled:
            if QApplication.overrideCursor() is None:
                 QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.log_to_status(f"Busy: {current_task or self._current_task_phase}...")
        else:
            if QApplication.overrideCursor() is not None:
                 QApplication.restoreOverrideCursor()
            if self._current_task_phase == TASK_IDLE:
                backend_name = self.llm_client.get_backend_name() if llm_ok else "N/A"
                conn_status = 'Connected' if llm_ok else 'Disconnected'
                if self.llm_client and not llm_ok: conn_status = 'Connection Error'
                status_suffix = f"(Backend: {backend_name}, Status: {conn_status})"
                proj_info = f"Project: {self.current_project}" if self.current_project else "No Project Loaded"
                self.log_to_status(f"--- Ready --- {proj_info} {status_suffix}")


    # --- Journalisation & Mises à jour UI ---
    def _handle_worker_log(self, message: str, source: str):
        """Route les logs du worker vers la zone de texte appropriée."""
        if source == 'console':
            self.log_to_console(message)
        elif source == 'status':
            self.log_to_status(message)
        else:
            print(f"Unknown log source: {source} - Msg: {message}")
            self.log_to_console(f"[Unknown Log: {source}] {message}")

    def log_to_console(self, message: str):
        """Ajoute un message au journal principal d'exécution/console."""
        self.main_window.execution_log_text.append(str(message))
        self.main_window.execution_log_text.verticalScrollBar().setValue(
            self.main_window.execution_log_text.verticalScrollBar().maximum()
        )
        print(f"CONSOLE_LOG: {message}") # Affiche aussi dans le terminal

    def log_to_status(self, message: str):
        """Ajoute un message à la zone de journal de statut."""
        self.main_window.status_log_text.append(str(message))
        self.main_window.status_log_text.verticalScrollBar().setValue(
            self.main_window.status_log_text.verticalScrollBar().maximum()
        )
        print(f"STATUS_LOG: {message}") # Affiche aussi dans le terminal


    # --- Interaction LLM ---
    def attempt_llm_connection(self):
        """Tente de se connecter au backend LLM sélectionné."""
        if self._current_task_phase != TASK_IDLE:
            QMessageBox.warning(self.main_window, "Busy", f"Cannot connect while task '{self._current_task_phase}' is running.")
            return

        selected_backend = self.main_window.llm_backend_selector.currentText()
        connect_args: Dict[str, Any] = {}
        connect_callable: Optional[Callable] = None
        self.llm_client = None # Réinitialise le client avant la tentative de connexion

        try:
            if selected_backend == LLM_BACKEND_LMSTUDIO:
                host_ip = self.main_window.llm_ip_input.text().strip()
                port_str = self.main_window.llm_port_input.text().strip()
                if not host_ip: raise ValueError("LM Studio IP missing.")
                if not port_str: raise ValueError("LM Studio Port missing.") # Ajout d'une vérification pour chaîne vide

                # --- CORRECTION: Convertit port_str en int ICI ---
                try:
                    port = int(port_str)
                except ValueError:
                     raise ValueError("LM Studio Port must be a number.")
                # --- FIN CORRECTION ---

                if not (1 <= port <= 65535): raise ValueError("LM Studio Port invalid (must be 1-65535).")
                connect_args = {"host": host_ip, "port": port}
                # Crée l'instance client juste avant d'appeler connect
                client_instance = LMStudioClient()
                connect_callable = client_instance.connect
                status_msg = f"LLM: Connecting to LM Studio {host_ip}:{port}..."

            elif selected_backend == LLM_BACKEND_GEMINI:
                if not GOOGLE_GENAI_AVAILABLE: raise ConnectionError("'google-generai' not installed.")
                api_key = self.main_window.gemini_api_key_input.text()
                if not api_key: raise ValueError("Gemini API Key missing.")
                model_name = self.main_window.gemini_model_selector.currentText()
                if not model_name: raise ValueError("Gemini Model Name missing.")
                connect_args = {"api_key": api_key, "model_name": model_name}
                client_instance = GeminiClient()
                connect_callable = client_instance.connect
                status_msg = f"LLM: Connecting to Gemini ({model_name})..."
            else:
                raise ValueError(f"Unknown LLM backend: {selected_backend}")

            self.llm_client = client_instance # Stocke l'instance maintenant
            self.main_window.llm_status_label.setText(status_msg)
            self.main_window.llm_status_label.setStyleSheet("color: orange;")
            QApplication.processEvents() # Affiche "Connecting..."

        except (ValueError, ConnectionError, TypeError) as e:
            QMessageBox.warning(self.main_window, "Config Error", str(e))
            self.llm_client = None # Assure que le client est None en cas d'erreur de config
            self.main_window.llm_status_label.setText(f"LLM Status: Config Error")
            self.main_window.llm_status_label.setStyleSheet("color: red;")
            self.set_ui_enabled(True) # Réactive l'UI après l'erreur de config
            return

        # Démarre le worker seulement si callable et client sont définis
        if connect_callable and self.llm_client:
            started = self.start_worker(
                task_type=TASK_ATTEMPT_CONNECTION,
                task_callable=connect_callable,
                **connect_args
            )
            if not started:
                 # Si le worker n'a pas pu démarrer, réinitialise l'état
                 self.llm_client = None
                 self.main_window.llm_status_label.setText(f"LLM: Connection Failed (Busy?)")
                 self.main_window.llm_status_label.setStyleSheet("color: red;")
                 if self._current_task_phase == TASK_ATTEMPT_CONNECTION: # Vérifie si la phase a été définie
                     self._current_task_phase = TASK_IDLE
                 self.set_ui_enabled(True)
        else:
             # Ne devrait pas arriver si la vérification de config a réussi, mais gère défensivement
             self.llm_client = None
             self.main_window.llm_status_label.setText(f"LLM: Internal Error")
             self.main_window.llm_status_label.setStyleSheet("color: red;")
             self.set_ui_enabled(True)


    # --- Interaction Chat ---
    def send_chat_message(self):
        """Démarre le nouveau workflow: Identify Deps -> Generate Code -> Install."""
        if self._current_task_phase != TASK_IDLE:
            QMessageBox.warning(self.main_window, "Busy", f"Cannot send request while task '{self._current_task_phase}' is running.")
            return

        user_request = self.main_window.chat_input_text.text().strip()
        if not self.current_project:
            QMessageBox.warning(self.main_window, "No Project Selected", "Select or create a project first.")
            return
        if not self.llm_client or not self.llm_client.is_available():
            QMessageBox.warning(self.main_window, "LLM Not Ready", "LLM not connected or available.")
            return
        if not user_request:
            QMessageBox.warning(self.main_window, "Input Needed", "Describe your goal or modification.")
            return

        self._last_user_chat_message = user_request # Stocke pour utilisation dans l'étape de génération de code
        self.main_window.chat_input_text.clear()

        # Vide le chat précédent et ajoute le prompt Utilisateur
        self.main_window.chat_display_text.clear()
        self.append_to_chat("User", user_request)
        # Ajoute un placeholder pour le processus multi-étapes
        self.append_to_chat("System", "(Identifying dependencies...)")
        QApplication.processEvents() # Met à jour l'affichage immédiatement

        self.log_to_status(f"--- Sending request to LLM for dependency identification... ---")
        # Démarre l'Étape 1: Identification des Dépendances depuis la Requête
        started = self.start_worker(
            task_type=TASK_IDENTIFY_DEPS_FROM_REQUEST,
            task_callable=self.llm_client.identify_dependencies_from_request,
            user_prompt=user_request,
            project_name=self.current_project
        )
        if not started:
            # Si le worker n'a pas pu démarrer, annule les changements UI
            self.append_to_chat("System", "Error: Could not start dependency identification (Busy?).")
            self.main_window.chat_input_text.setText(user_request) # Restaure l'input
            self.set_ui_enabled(True)

    # --- Assistants Affichage Chat ---
    def append_to_chat(self, sender: str, message: str):
        """Ajoute un message formaté (User/System) à l'affichage du chat."""
        chat_widget = self.main_window.chat_display_text
        cursor = chat_widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        chat_widget.setTextCursor(cursor)

        # Utilise HTML pour le formatage de base (expéditeur en gras)
        # Assure la séparation entre les messages
        if not chat_widget.toPlainText().endswith('\n\n'): # Ajoute un saut de ligne si nécessaire
            if chat_widget.toPlainText().strip(): # N'ajoute pas d'espace supplémentaire si vide
                chat_widget.insertHtml("<br>")

        chat_widget.insertHtml(f"<b>{sender}:</b> ") # Expéditeur en gras
        # Insère le texte brut pour le message pour éviter l'injection HTML accidentelle
        chat_widget.insertPlainText(message.strip())
        chat_widget.insertHtml("<br><br>") # Saut de ligne après le message pour espacer

        chat_widget.ensureCursorVisible() # Fait défiler vers le bas

    def _buffer_chat_fragment(self, fragment: str):
        """Ajoute le fragment de stream entrant à un buffer."""
        self._chat_fragment_buffer += fragment

    def _process_chat_buffer(self):
        """Ajoute les fragments bufferisés à l'affichage du chat pendant le streaming."""
        if self._chat_fragment_buffer:
            # Ne devrait être appelé que pendant TASK_GENERATE_CODE_STREAM
            chat_widget = self.main_window.chat_display_text
            cursor = chat_widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            chat_widget.setTextCursor(cursor)

            # Ajoute le texte bufferisé (texte brut)
            chat_widget.insertPlainText(self._chat_fragment_buffer)
            self._chat_fragment_buffer = "" # Vide le buffer
            chat_widget.ensureCursorVisible() # Garde le défilement vers le bas


    # --- Assistant Nettoyage Code ---
    def _cleanup_llm_code_output(self, code_text: str) -> str:
        """
        Extrait le code du *dernier* bloc de code markdown (```python ... ``` ou ``` ... ```).
        Revient à supprimer les espaces si aucun bloc n'est trouvé.
        """
        if not code_text:
            return ""

        code_text = code_text.rstrip() # Supprime d'abord les espaces de fin

        # Trouve le début du dernier bloc de code ```python ou ```
        last_start_tag_python = code_text.rfind("```python")
        last_start_tag_plain = code_text.rfind("\n```\n") # Cherche ``` sur sa propre ligne
        # Ajuste l'index de la balise simple pour être le début du contenu, en supposant un saut de ligne après ```
        if last_start_tag_plain != -1:
            last_start_tag_plain += len("\n```\n") -1 # Pointe vers la fin de ```

        # Détermine l'index de début réel du dernier bloc
        last_start_index = -1
        start_offset = 0
        if last_start_tag_python > last_start_tag_plain:
             last_start_index = last_start_tag_python
             start_offset = len("```python")
        elif last_start_tag_plain != -1 :
             last_start_index = last_start_tag_plain # Déjà ajusté
             start_offset = 0 # Le contenu commence après \n```
        else:
             # Peut-être que le fichier *commence* par ```python ?
             if code_text.lower().startswith("```python"):
                 last_start_index = 0
                 start_offset = len("```python")
             elif code_text.startswith("```"):
                 last_start_index = 0
                 start_offset = len("```")


        # Si une balise de début a été trouvée, cherche la balise de fin ``` APRÈS elle
        if last_start_index != -1:
            last_end_index = code_text.rfind("```", last_start_index + start_offset)

            if last_end_index != -1:
                # Extrait le contenu entre la balise de début (après la balise elle-même) et la balise de fin
                start_content = last_start_index + start_offset
                code_block = code_text[start_content:last_end_index].strip()
                # Ajoute une vérification supplémentaire : si le résultat est vide, peut-être que les clôtures étaient adjacentes ?
                # Dans ce cas, reviens à supprimer les espaces de toute la chaîne.
                if code_block:
                    print("Code extracted from last ``` block.")
                    return code_block
                else:
                    print("Warning: Found code fences but content between was empty. Falling back.")

        # Fallback: Aucun bloc valide trouvé, supprime juste les espaces de l'entrée entière
        print("Warning: Could not find clear ```python...``` block. Stripping whitespace only.")
        return code_text.strip()


    # --- Assistant Analyse Dépendances ---
    def _parse_dependency_response(self, deps_str: str) -> Tuple[List[str], Optional[str]]:
        """Analyse la réponse chaîne du LLM attendue comme une chaîne de liste Python."""
        deps_str = deps_str.strip();
        if not deps_str: return [], "Empty dependency list string received."
        try:
            parsed_list = ast.literal_eval(deps_str)
            if isinstance(parsed_list, list) and all(isinstance(item, str) for item in parsed_list): return [dep.strip() for dep in parsed_list if dep.strip()], None # Succès
            else: raise ValueError("Parsed result is not a list of strings.")
        except (ValueError, SyntaxError, TypeError) as e:
            match = re.search(r"(\[.*?\])", deps_str, re.DOTALL) # Essaye le fallback regex
            if match:
                 try:
                     parsed_list_fb = ast.literal_eval(match.group(1))
                     if isinstance(parsed_list_fb, list) and all(isinstance(item, str) for item in parsed_list_fb): return [dep.strip() for dep in parsed_list_fb if dep.strip()], f"Warning: Parsed using fallback regex after error: {e}"
                     else: raise ValueError("Fallback regex content not a list of strings")
                 except Exception as e_fb: err_msg = f"Could not parse dependency list string: '{deps_str}'. Initial Error: {e}. Fallback Error: {e_fb}"; return [], err_msg
            else: err_msg = f"Could not parse dependency list string: '{deps_str}'. Error: {e}"; return [], err_msg


    # --- Actions de Gestion de Projet ---
    def load_project_list(self):
        """Charge la liste des projets dans le QListWidget."""
        if self._current_task_phase != TASK_IDLE: print("Busy, skipping project list load"); return
        mw = self.main_window; mw.project_list_widget.clear()
        try:
            projects = project_manager.list_projects()
            if projects: mw.project_list_widget.addItems(projects); mw.project_list_widget.setEnabled(True)
            else: item = QListWidgetItem("No projects found"); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable); mw.project_list_widget.addItem(item); mw.project_list_widget.setEnabled(False)
        except Exception as e: print(f"Error loading project list: {e}"); self.log_to_console(f"Error loading project list:\n{traceback.format_exc()}"); item = QListWidgetItem("Error loading list"); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable); mw.project_list_widget.addItem(item); mw.project_list_widget.setEnabled(False)

    def load_selected_project(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        """Gère les changements de sélection dans la liste de projets et charge les données du projet."""
        mw = self.main_window; project_name = None; is_valid_selection = False
        if current_item is not None:
            item_is_selectable = bool(current_item.flags() & Qt.ItemFlag.ItemIsSelectable); is_placeholder = current_item.text() in ["No projects found", "Error loading list"]; is_valid_selection = item_is_selectable and not is_placeholder
            if is_valid_selection: project_name = current_item.text()
        can_act_on_project = is_valid_selection and self._current_task_phase == TASK_IDLE; mw.delete_project_button.setEnabled(can_act_on_project); mw.export_button.setEnabled(can_act_on_project)
        if not is_valid_selection:
             if self.current_project: self.clear_project_view()
             self.set_ui_enabled(self._current_task_phase == TASK_IDLE); return
        if self._current_task_phase != TASK_IDLE:
            print(f"Busy ({self._current_task_phase}), cannot switch project."); mw.project_list_widget.blockSignals(True); mw.project_list_widget.setCurrentItem(previous_item); mw.project_list_widget.blockSignals(False); QMessageBox.warning(mw, "Busy", f"Cannot switch project while task '{self._current_task_phase}' is running."); return
        if self.current_project != project_name and project_name is not None:
            self.current_project = project_name; mw.setWindowTitle(f"Pythautom - {project_name}"); print(f"Loading project: {project_name}"); self.clear_project_view_content(); self.log_to_status(f"--- Project '{project_name}' loaded ---")
            self.reload_project_data(load_dependencies=True); self._last_user_chat_message = ""; self._pending_install_deps = []; self._deps_identified_for_next_step = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0
        self.set_ui_enabled(True)

    def reload_project_data(self, update_editor=True, load_dependencies=False):
        """Recharge le code et éventuellement les dépendances pour le projet actuel."""
        if not self.current_project: return
        mw = self.main_window; print(f"[GUI Handler] Reloading data for '{self.current_project}'. Editor={update_editor}, Deps={load_dependencies}")
        if update_editor:
            try: code = project_manager.get_project_script_content(self.current_project); mw.code_editor_text.setPlainText(code if code is not None else f"# Failed to read {DEFAULT_MAIN_SCRIPT}")
            except Exception as e: err_msg = f"# Error loading script: {e}"; mw.code_editor_text.setPlainText(err_msg); self.log_to_console(err_msg)
        if load_dependencies:
            try: metadata = project_manager.load_project_metadata(self.current_project); self._project_dependencies = metadata.get("dependencies", []); self.log_to_console(f"Loaded dependencies from metadata: {self._project_dependencies}")
            except Exception as e: self._project_dependencies = []; self.log_to_console(f"Error loading dependencies from metadata for {self.current_project}: {e}")

    def clear_project_view_content(self):
         """Vide les éléments UI liés au contenu du projet."""
         mw = self.main_window; print("Clearing project view content..."); mw.code_editor_text.clear(); mw.status_log_text.clear(); mw.execution_log_text.clear(); mw.chat_display_text.clear(); mw.chat_input_text.clear()

    def clear_project_view(self):
        """Vide les éléments UI et réinitialise l'état lorsqu'aucun projet n'est sélectionné."""
        mw = self.main_window; print("Clearing project view completely..."); self.current_project = None; mw.setWindowTitle("Pythautom - AI Python Project Builder"); self.clear_project_view_content(); self._current_task_phase = TASK_IDLE; self._last_user_chat_message = ""; self._project_dependencies = []; self._pending_install_deps = []; self._deps_identified_for_next_step = []; self._code_to_correct = None; self._last_execution_error = None; self._correction_attempts = 0; self.set_ui_enabled(True)

    def create_new_project_dialog(self):
        """Affiche une boîte de dialogue pour créer un nouveau projet."""
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(self.main_window, "Busy", "Cannot create project while task running."); return
        dialog = QDialog(self.main_window); dialog.setWindowTitle("Create New Project"); layout = QVBoxLayout(dialog); label = QLabel("Enter project name (alphanumeric, _, -):"); name_input = QLineEdit(); layout.addWidget(label); layout.addWidget(name_input); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec():
            raw_name = name_input.text().strip(); project_name = raw_name
            if not raw_name or not re.match(r'^[\w-]+$', raw_name): QMessageBox.warning(self.main_window, "Invalid Name", "Project name can only contain letters, numbers, underscores, and hyphens."); return
            print(f"Attempting to create project: '{project_name}'")
            try:
                if project_manager.create_project(project_name):
                    sanitized_name = project_manager.get_project_path(project_name).split(os.sep)[-1]; self.log_to_console(f"Project '{sanitized_name}' created."); self.load_project_list(); items = self.main_window.project_list_widget.findItems(sanitized_name, Qt.MatchFlag.MatchExactly)
                    if items: self.main_window.project_list_widget.setCurrentItem(items[0])
                    else: print(f"Warning: Could not find newly created project '{sanitized_name}' in list after refresh.")
                else: QMessageBox.critical(self.main_window, "Error", f"Failed to create project '{project_name}'. It might already exist or creation failed (check logs).")
            except Exception as e: QMessageBox.critical(self.main_window, "Creation Error", f"Error creating project '{project_name}':\n{e}"); self.log_to_console(f"EXCEPTION during project creation:\n{traceback.format_exc()}")

    def confirm_delete_project(self):
        """Demande confirmation et supprime le projet sélectionné."""
        mw = self.main_window;
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(mw, "Busy", "Cannot delete project while task running."); return
        selected_item = mw.project_list_widget.currentItem(); project_name = None
        if selected_item:
             item_is_selectable = bool(selected_item.flags() & Qt.ItemFlag.ItemIsSelectable); is_placeholder = selected_item.text() in ["No projects found", "Error loading list"]
             if item_is_selectable and not is_placeholder: project_name = selected_item.text()
        if not project_name: QMessageBox.warning(mw, "No Project Selected", "Select a valid project to delete."); return
        project_path_str = "N/A"
        try: project_path_str = project_manager.get_project_path(project_name)
        except ValueError as ve: QMessageBox.critical(mw, "Error", f"Cannot resolve path for project '{project_name}': {ve}"); return
        except Exception as e: print(f"Error resolving path for deletion: {e}"); project_path_str = f"Error resolving path: {e}"
        reply = QMessageBox.warning(mw, "Confirm Deletion", f"Permanently delete project '{project_name}'?\nLocation: {project_path_str}\n\nTHIS CANNOT BE UNDONE.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            print(f"Confirmed deletion for '{project_name}'."); self.log_to_status(f"--- Deleting project '{project_name}'... ---"); self.set_ui_enabled(False, "Deleting project"); QApplication.processEvents()
            deleted = False; error_msg = ""
            try:
                deleted = project_manager.delete_project(project_name)
                if not deleted: error_msg = f"Deletion failed for '{project_name}'. Project manager reported failure."; print(error_msg)
            except Exception as e: error_msg = f"Exception during deletion of '{project_name}': {e}"; print(f"EXCEPTION during delete project:\n{traceback.format_exc()}")
            finally:
                self._current_task_phase = TASK_IDLE
                if deleted:
                    self.log_to_console(f"Project '{project_name}' deleted."); self.log_to_status(f"--- Project '{project_name}' deleted. ---")
                    if self.current_project == project_name: self.clear_project_view()
                    self.load_project_list()
                else:
                    if not error_msg: error_msg = f"Deletion failed for '{project_name}' (unknown reason)."
                    QMessageBox.critical(mw, "Deletion Error", error_msg); self.log_to_console(error_msg); self.log_to_status(f"--- ERROR deleting '{project_name}'. ---"); self.load_project_list()
                self.set_ui_enabled(True)
        else: self.log_to_status("Project deletion cancelled.")

    def save_current_code(self):
        """Sauvegarde le contenu de l'éditeur de code et vide les dépendances associées."""
        mw = self.main_window
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(mw, "Busy", "Cannot save code while task running."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project Loaded", "Select a project to save code."); return
        code = mw.code_editor_text.toPlainText(); print(f"[GUI Handler] Attempting to save code for '{self.current_project}'. Length: {len(code)}")
        try:
            if project_manager.save_project_script_content(self.current_project, code):
                self.log_to_console(f"Code saved for project '{self.current_project}'."); self.log_to_status("Code saved.")
                # --- IMPORTANT: Vide les dépendances lors de la sauvegarde manuelle ---
                self._project_dependencies = []
                self.update_project_metadata_deps(); self.log_to_console("Project dependencies cleared due to manual code save. They will be re-identified on next AI interaction.")
                # -----------------------------------------------------
            else: QMessageBox.critical(mw, "Save Error", f"Failed to save code for '{self.current_project}'. Check logs.")
        except Exception as e: print(f"EXCEPTION during save: {e}"); self.log_to_console(traceback.format_exc()); QMessageBox.critical(mw, "Save Error", f"Error saving code:\n{e}")

    def run_current_project_script(self, called_from_chain: bool = False):
        """Exécute le script principal du projet actuel."""
        mw = self.main_window;
        if not called_from_chain and self._current_task_phase != TASK_IDLE: QMessageBox.warning(mw, "Busy", "Cannot run script while task running."); return
        if not self.current_project:
            if not called_from_chain: QMessageBox.warning(mw, "No Project", "Select a project to run.")
            else: print("Error: run_script called from chain without project."); self.log_to_status("Error: Cannot run script - no project loaded."); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
            return
        script_name = DEFAULT_MAIN_SCRIPT
        try:
            project_path = project_manager.get_project_path(self.current_project); script_file = os.path.join(project_path, script_name)
            if not os.path.isdir(project_path): raise FileNotFoundError(f"Project directory not found: {project_path}")
            if not os.path.exists(script_file): raise FileNotFoundError(f"Script '{script_name}' not found in {project_path}")
            self.log_to_status(f"Checking venv for {self.current_project}..."); QApplication.processEvents()
            venv_ok = utils.ensure_project_venv(project_path, progress_callback=self.log_to_console)
            if not venv_ok: raise RuntimeError("Failed to ensure project virtual environment. Check console log.")
        except Exception as e:
            msg = f"Error preparing to run script: {e}"; print(msg); self.log_to_console(f"--- Run Error (Prep) ---\n{msg}\n{traceback.format_exc()}\n---")
            if not called_from_chain: QMessageBox.critical(mw, "Run Error", msg)
            if called_from_chain: self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
            return
        self.log_to_console(f"\n--- Running script: {self.current_project}/{script_name} ---"); self.log_to_status(f"Running {script_name}...")
        started = self.start_worker(task_type=TASK_RUN_SCRIPT, task_callable=utils.run_project_script, project_path=project_path, script_name=script_name)
        if not started: self.log_to_console("--- Could not start script execution (Busy?). Reverting. ---"); self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

    def start_correction_worker(self) -> bool:
        """Démarre le worker LLM pour corriger le code basé sur la dernière erreur."""
        if not self.current_project or not self.llm_client or not self.llm_client.is_available(): self.log_to_status("Error: Cannot start correction. Project/LLM invalid."); self.log_to_console("Error: Preconditions for starting correction worker not met (Project/LLM)."); return False
        if self._code_to_correct is None or self._last_execution_error is None: self.log_to_status("Error: Missing code or error context for correction."); self.log_to_console("Error: _code_to_correct or _last_execution_error is missing."); return False
        self.log_to_status(f"--- Starting code correction generation (Attempt {self._correction_attempts})... ---")
        started = self.start_worker(task_type=TASK_GENERATE_CODE, task_callable=self.llm_client.generate_or_correct_code, user_prompt=self._last_user_chat_message, project_name=self.current_project, current_code=self._code_to_correct, dependencies_to_use=self._project_dependencies, execution_error=self._last_execution_error)
        if not started: self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)
        return started

    def prompt_export_project(self):
        """Affiche la confirmation et la boîte de dialogue de fichier pour l'exportation du projet."""
        mw = self.main_window;
        if self._current_task_phase != TASK_IDLE: QMessageBox.warning(mw, "Busy", "Cannot export while another task is running."); return
        if not self.current_project: QMessageBox.warning(mw, "No Project Selected", "Please select a project to export."); return
        current_os = platform.system(); reply = QMessageBox.question(mw, "Confirm Export", f"Export project '{self.current_project}' as executable for {current_os}?\n(This uses PyInstaller and may take some time)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No: self.log_to_status("Export cancelled by user."); return
        default_filename = f"{self.current_project}_{current_os.lower()}.zip"; output_zip_path, _ = QFileDialog.getSaveFileName(mw, "Save Executable Bundle As", default_filename, "Zip Files (*.zip)")
        if output_zip_path:
            if not output_zip_path.lower().endswith(".zip"): output_zip_path += ".zip"
            print(f"Starting export for '{self.current_project}' to '{output_zip_path}'"); self.log_to_status(f"--- Starting export to {os.path.basename(output_zip_path)}... ---"); self.log_to_console(f"--- Starting export of '{self.current_project}' to '{output_zip_path}' ---"); self.start_export_worker(output_zip_path)
        else: self.log_to_status("Export cancelled by user (file dialog).")

    def start_export_worker(self, output_zip_path: str):
        """Démarre le worker en arrière-plan pour le processus d'exportation."""
        if not self.current_project: return
        started = self.start_worker(task_type=TASK_EXPORT_PROJECT, task_callable=exporter.create_executable_bundle, project_name=self.current_project, output_zip_path=output_zip_path)
        if not started: self.log_to_status("! Error starting export worker (Busy?)."); self.log_to_console("! Error starting export worker (Busy?)."); QMessageBox.critical(self.main_window, "Export Error", "Could not start export process.");
        if self._current_task_phase == TASK_EXPORT_PROJECT: self._current_task_phase = TASK_IDLE; self.set_ui_enabled(True)

    # --- Mise à Jour des Métadonnées ---
    def update_project_metadata_deps(self):
        """Met à jour silencieusement la liste des dépendances dans le fichier de métadonnées du projet."""
        if not self.current_project: return
        try:
            metadata = project_manager.load_project_metadata(self.current_project); metadata["dependencies"] = sorted(list(set(self._project_dependencies))) # Utilise l'état du gestionnaire
            project_manager.save_project_metadata(self.current_project, metadata); print(f"Updated metadata dependencies for {self.current_project}: {metadata['dependencies']}")
        except Exception as e: msg = f"Warning: Failed to update project metadata dependencies for '{self.current_project}': {e}"; print(msg); self.log_to_console(msg)

    # --- Gestion Événement Fermeture ---
    def handle_close_event(self, event):
        """Gère la confirmation de l'événement de fermeture de l'application et l'annulation de la tâche."""
        confirm_needed = self._current_task_phase != TASK_IDLE; reply = QMessageBox.StandardButton.Yes
        if confirm_needed: reply = QMessageBox.question(self.main_window, 'Confirm Exit', f"Task ({self._current_task_phase}) is running.\nExit now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            print("Closing application...");
            if self.thread and self.thread.isRunning() and self.worker: print("Attempting to cancel background task..."); self.worker.cancel()
            event.accept() # Autorise la fermeture de la fenêtre
        else: print("Application close cancelled."); event.ignore() # Empêche la fermeture de la fenêtre