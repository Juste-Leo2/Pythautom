# src/llm_interaction.py
# VERSION FINALE : Utilise lms.Chat conformément à la documentation fournie.

import lmstudio as lms
from pydantic import BaseModel, Field
import traceback
import json # Pour parsing manuel fallback
import re   # Pour parsing manuel fallback
from typing import List, Callable, Optional, Generator, Any, Dict # Ajout de Dict

# --- Configuration ---
DEFAULT_MODEL: Optional[str] = None # Utilise le modèle chargé par défaut
DEFAULT_LM_STUDIO_IP = "127.0.0.1"  # Défaut IP (localhost)
DEFAULT_LM_STUDIO_PORT = 1234       # Défaut Port

# --- Pydantic Schema for Dependencies ---
class DependencyList(BaseModel):
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of NON-STANDARD Python libraries required (e.g., ['pygame', 'requests']). Exclude standard libs (os, sys, json, etc.). Empty list if none needed."
    )

# --- LLM Client Wrapper ---
class LLMClient:
    def __init__(self, model_identifier: Optional[str] = DEFAULT_MODEL):
        """Initialise le client mais ne se connecte pas immédiatement."""
        self.model_identifier = model_identifier
        self.model: Optional[lms.LLM] = None # Handle du modèle LLM
        self.connected_uri: Optional[str] = None # Garde une trace de l'URI connecté
        print(f"LLMClient initialized. Target model identifier: '{self.model_identifier or 'Any Loaded'}'.")
        # La connexion se fera via la méthode connect()

    def _connect(self, host: str, port: int) -> bool:
        """
        Tente de se connecter au serveur LM Studio à l'host/port spécifié
        et d'obtenir un handle pour le modèle.
        Met à jour self.model et self.connected_uri.
        Retourne True en cas de succès, False sinon.
        """
        self.model = None # Reset le modèle avant la tentative
        self.connected_uri = None
        server_uri = f"{host}:{port}"
        print(f"Attempting to connect to LM Studio server at: {server_uri}")
        try:
            # Utilise un context manager si possible pour gérer la fermeture du client
            # Mais ici on garde le client ouvert, donc création standard.
            client = lms.Client(server_uri)
            print(f"Client created. Attempting to get model handle (Identifier: '{self.model_identifier or 'Any Loaded'}')...")
            self.model = client.llm.model(self.model_identifier) # Peut être None si pas chargé
            if not self.model:
                # Tenter de récupérer le modèle chargé par défaut si aucun identifiant n'est donné
                if not self.model_identifier:
                    print("No specific model requested, attempting to get default loaded model again...")
                    self.model = client.llm.model() # Essaye sans argument
                if not self.model: # Toujours None ?
                    raise ConnectionError(f"Could not get model handle ('{self.model_identifier or 'Any Loaded'}') from server {server_uri}. Is a model loaded?")

            # Tentative simple pour vérifier que le modèle est opérationnel
            print("Verifying model responsiveness...")
            response = self.model.respond("Hi", config={"max_tokens": 5}) # Test rapide
            if not response or not response.content:
                 raise ConnectionError(f"Model handle obtained but failed basic 'Hi' test.")

            self.connected_uri = server_uri
            # Tente de récupérer le nom réel du modèle chargé
            loaded_name = "Currently Loaded Model" # Fallback
            try:
                # Tente d'accéder à un attribut potentiel (peut varier selon la version)
                if hasattr(self.model, 'model_identifier') and self.model.model_identifier:
                    loaded_name = self.model.model_identifier
                elif hasattr(self.model, '_model_identifier') and self.model._model_identifier: # Autre nom possible
                    loaded_name = self.model._model_identifier
                elif self.model_identifier: # Si on avait demandé un modèle spécifique
                    loaded_name = self.model_identifier
            except Exception: pass # Ignore les erreurs de récupération de nom
            print(f"Successfully connected to '{loaded_name}' at {server_uri}")
            return True

        except ConnectionRefusedError:
             print(f"ERROR: Connection refused by server at {server_uri}. Is LM Studio server running and accessible?")
             self.model = None; return False
        except ConnectionError as ce: # Attrape l'erreur levée si model est None
             print(f"ERROR: {ce}")
             self.model = None; return False
        except AttributeError as ae:
            print(f"AttributeError during connection: {ae}. lmstudio-python version issue?"); traceback.print_exc(); self.model = None; return False
        except Exception as e:
            print(f"ERROR connecting/getting model handle from '{server_uri}': {type(e).__name__}: {e}")
            # traceback.print_exc() # Décommenter pour plus de détails si nécessaire
            self.model = None; return False

    def connect(self, host: str, port: int) -> bool:
        """
        Méthode publique pour initier ou mettre à jour la connexion.
        Appelle _connect et retourne le statut de la connexion.
        """
        print(f"Connect request received for {host}:{port}")
        return self._connect(host, port)

    def is_available(self) -> bool:
        """Vérifie si un handle de modèle valide est actuellement détenu."""
        return self.model is not None

    def check_connection(self) -> bool:
        """
        Vérifie si le modèle actuellement connecté (s'il y en a un) répond.
        N'essaie PAS de se reconnecter si non connecté. Utiliser connect() pour cela.
        Retourne True si le modèle répond, False sinon (ou si non connecté).
        """
        if not self.is_available(): # Utilise is_available() qui vérifie self.model
            print("LLM check skipped: No active model connection.")
            return False

        model_id_for_log = "current model" # Fallback
        try: model_id_for_log = getattr(self.model, 'model_identifier', model_id_for_log)
        except: pass
        print(f"Checking responsiveness of currently connected model '{model_id_for_log}' at {self.connected_uri}...")
        try:
            response = self.model.respond("Hi", config={"max_tokens": 5})
            if response and isinstance(response.content, str):
                 print(f"LLM responsiveness OK.")
                 return True
            else:
                 print(f"LLM responsiveness check failed: Invalid/empty response.")
                 # Si le check échoue, on invalide la connexion actuelle
                 self.model = None; self.connected_uri = None
                 return False
        except Exception as e:
            print(f"LLM responsiveness check failed for '{model_id_for_log}': {type(e).__name__}: {e}")
            # Si le check échoue, on invalide la connexion actuelle
            self.model = None; self.connected_uri = None
            return False

    # --- Phase 1: Identify Dependencies (Utilise lms.Chat + response_format) ---
    def identify_dependencies(self, user_prompt: str, project_name: str) -> List[str]:
        """
        Identifies dependencies using lms.Chat for context management and structured output.
        """
        if not self.is_available():
            return ["ERROR: LLM not available"]

        system_prompt = (
            f"You are an expert Python dependency analyzer for a project named '{project_name}'. "
            "Your task is to analyze the user's request and list ONLY the external, non-standard Python libraries required. "
            "Exclude standard libraries (like os, sys, json, re, math). "
            "If no external libraries are needed, provide an empty list ['pygame', 'requests']. "
            "Respond ONLY with a JSON object matching the schema provided." # Instructions claires
        )

        print(f"[LLM ID_Deps] Requesting dependencies for prompt: '{user_prompt[:60]}...'")
        dependencies = []

        try:
            chat = lms.Chat(system_prompt)
            chat.add_user_message(user_prompt) # Ajoute seulement le prompt utilisateur
            print("[LLM ID_Deps] Sending chat context to LLM for structured response...")

            # Utilise response_format pour obtenir le JSON structuré
            prediction_stream: Generator[Any, Any, Any] = self.model.respond_stream(
                chat,
                response_format=DependencyList
            )

            print("[LLM ID_Deps] Consuming stream and waiting for parsed result...")
            final_content = "".join([chunk.content for chunk in prediction_stream if chunk and hasattr(chunk, 'content') and chunk.content])

            parsed_result: Optional[DependencyList] = None
            if hasattr(prediction_stream, 'result'):
                 result_obj = prediction_stream.result()
                 if isinstance(result_obj, DependencyList): parsed_result = result_obj
                 elif hasattr(result_obj, 'parsed') and isinstance(result_obj.parsed, DependencyList): parsed_result = result_obj.parsed
                 elif hasattr(result_obj, 'parsed') and isinstance(result_obj.parsed, dict):
                      try: parsed_result = DependencyList(**result_obj.parsed)
                      except Exception as pydantic_err: print(f"[LLM ID_Deps] WARN: Dict->Pydantic failed: {pydantic_err}")
                 else: print(f"[LLM ID_Deps] WARN: Unexpected result type: {type(result_obj)}")
            else:
                 print("[LLM ID_Deps] WARN: prediction_stream has no result attribute.")

            print(f"[LLM ID_Deps] Processing parsed result...")
            if parsed_result and isinstance(parsed_result, DependencyList):
                 raw_deps = parsed_result.dependencies
                 if isinstance(raw_deps, list) and all(isinstance(d, str) for d in raw_deps):
                     dependencies = [dep.strip() for dep in raw_deps if dep.strip()]
                     print(f"[LLM ID_Deps] Dependencies parsed successfully: {dependencies}")
                 else:
                     print(f"[LLM ID_Deps] WARN: Parsed 'dependencies' not list[str]: {raw_deps}. Assuming none.")
                     dependencies = []
            else:
                print(f"[LLM ID_Deps] WARN: Could not obtain parsed DependencyList object.")
                print(f"       Raw response received (first 250 chars): {final_content[:250]}...")
                dependencies = ["ERROR: Failed to parse dependencies from LLM response."]

        except Exception as e:
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print(f"EXCEPTION during dependency identification:")
            print(traceback.format_exc())
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            dependencies = [f"ERROR: {type(e).__name__}: {e}"]

        # Retourne la liste (peut contenir une erreur)
        return [dep for dep in dependencies if dep]


    # --- Phase 2: Generate or Correct Code (Utilise lms.Chat, SANS response_format) ---
    def generate_code_streaming(self,
                                user_prompt: str,
                                project_name: str,
                                current_code: str,
                                dependencies_identified: List[str],
                                fragment_callback: Callable[[str], None],
                                execution_error: Optional[str] = None):
        """
        Generates or corrects Python code using lms.Chat for context management.
        Streams the raw code output.
        """
        if not self.is_available():
            try: fragment_callback("\n\n# --- ERROR: LLM is not available. --- #\n")
            except Exception as cb_err: print(f"Error sending LLM unavailable msg: {cb_err}")
            return

        # --- Construction du System Prompt Détaillé ---
        log_prefix = "[LLM Generate]"
        task_description = "GENERATE Python code"
        error_context = ""
        code_context_label = "Current Code (modify or replace if needed):"
        # Instruction pour le format de sortie (crucial)
        instruction = "Output ONLY the complete Python code required in a single ```python ... ``` block. Do NOT add any explanation, commentary, or introductory/concluding text before or after the code block. Just provide the raw Python code inside the fences."

        if execution_error:
            log_prefix = "[LLM Correct]"
            task_description = "CORRECT the Python code provided below"
            error_context = f"The previous code execution failed with this error:\n```text\n{execution_error.strip()}\n```\nPlease fix the Python code based ONLY on this error and the original user request."
            code_context_label = "Code to Correct:"
            instruction = "Output ONLY the complete, corrected Python code in a single ```python ... ``` block. Do NOT include explanations, apologies, or comments about the changes made outside the code itself. Ensure the corrected code directly addresses the reported error." # Instruction spécifique correction
        elif current_code:
            task_description = "MODIFY/REFACTOR the Python code provided below based on the user request."
            code_context_label = "Current Code (to be modified/refactored):"

        deps_list_str = ', '.join(d for d in dependencies_identified if not d.startswith("ERROR:"))
        deps_info = f"Assumed available non-standard libraries: {deps_list_str if deps_list_str else 'Standard Python libraries only'}."

        # Assembler le system prompt complet pour l'objet Chat
        system_prompt_lines = [
            f"You are Pythautom, an AI assistant that writes Python code for a project named '{project_name}'.",
            f"Your current task: {task_description}.",
            deps_info,
        ]
        if error_context: system_prompt_lines.append(error_context)
        system_prompt_lines.extend([
            f"\n{code_context_label}",
            "```python",
            current_code if current_code else '# Start writing Python code here.',
            "```",
            f"\n{instruction}", # Instruction sur le format de sortie
            # "\nAssistant Response:" # Pas forcément nécessaire avec lms.Chat
        ])
        system_prompt = "\n".join(system_prompt_lines)
        # --- Fin Construction System Prompt ---

        print(f"{log_prefix} Requesting code for: '{user_prompt[:50]}...'")
        if execution_error: print(f"{log_prefix} Providing error context: {execution_error[:100]}...")

        try:
            # 1. Créer l'objet Chat avec le system prompt détaillé
            chat = lms.Chat(system_prompt)
            # 2. Ajouter la requête utilisateur simple au chat
            chat.add_user_message(user_prompt)
            print(f"{log_prefix} Sending chat context to LLM for streaming response...")

            # 3. Appeler respond_stream SANS response_format pour obtenir le code brut
            prediction_stream = self.model.respond_stream(
                chat
                # config={...} # Ajouter config si besoin (e.g., temperature)
            )

            # 4. Itérer sur les fragments et appeler le callback
            print(f"{log_prefix} Streaming code fragments...")
            fragment_count = 0
            for fragment in prediction_stream:
                # Vérifier si le fragment est valide et contient du texte
                if fragment and hasattr(fragment, 'content') and isinstance(fragment.content, str):
                    try:
                        fragment_callback(fragment.content)
                        fragment_count += 1
                    except Exception as cb_err:
                        print(f"Error calling fragment_callback: {cb_err}") # Non-fatal
            print(f"{log_prefix} Streaming finished. Received {fragment_count} fragments.")

        except Exception as e:
            error_msg = f"\n\n# --- LLM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs.\n# --- END LLM ERROR --- #"
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"); print(f"EXCEPTION during LLM {log_prefix}:"); print(traceback.format_exc()); print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            try: fragment_callback(error_msg)
            except Exception as cb_err: print(f"Error sending LLM error via callback: {cb_err}")