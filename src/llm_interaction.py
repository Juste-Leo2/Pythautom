# src/llm_interaction.py

import lmstudio as lms
import traceback
import json
import re
import ast
import abc
import sys
from typing import List, Callable, Optional, Generator, Any, Dict, Tuple

# --- Imports Pydantic, google.generativeai ---
# (Ces blocs restent inchangés par rapport à la version précédente corrigée)
try:
    from pydantic import BaseModel, Field, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    print("WARNING: pydantic library not found...")
    PYDANTIC_AVAILABLE = False
    class BaseModel: pass
    def Field(*args, **kwargs): return None
    class ValidationError(Exception): pass

try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("WARNING: google-generativeai library not found...")
    GOOGLE_GENAI_AVAILABLE = False
    class genai:
        class GenerativeModel: pass
        class types: 
            class GenerationConfig: pass
    class HarmCategory: HARM_CATEGORY_HARASSMENT = None; HARM_CATEGORY_HATE_SPEECH = None; HARM_CATEGORY_SEXUALLY_EXPLICIT = None; HARM_CATEGORY_DANGEROUS_CONTENT = None
    class HarmBlockThreshold: BLOCK_NONE = None; BLOCK_ONLY_HIGH = None
# --- Fin Imports ---

# Import du module créé pour la configuration persistante
from . import config_manager

# --- Configuration ---
# Utilise les valeurs sauvegardées comme défauts
DEFAULT_LM_STUDIO_IP = config_manager.get_last_used_lmstudio_ip() or "127.0.0.1"
DEFAULT_LM_STUDIO_PORT = config_manager.get_last_used_lmstudio_port() or 1234

AVAILABLE_GEMINI_MODELS = [
    "gemma-3-27b-it",
    "gemini-2.0-flash-exp",
    "gemini-2.0-flash-lite",
    "gemini-2.5-pro-preview-03-25", 
]
DEFAULT_GEMINI_MODEL = config_manager.get_last_used_gemini_model() or AVAILABLE_GEMINI_MODELS[0]

# --- Schéma Pydantic (inchangé) ---
class DependencyList(BaseModel):
    dependencies: List[str] = Field(default_factory=list, description="...")


# --- Classe de Base Abstraite (inchangée) ---
class BaseLLMClient(abc.ABC):
    @abc.abstractmethod
    def connect(self, **kwargs) -> bool: pass

    @abc.abstractmethod
    def is_available(self) -> bool: pass

    @abc.abstractmethod
    def identify_dependencies_from_request(self, user_prompt: str, project_name: str, project_structure_info: Optional[str] = None) -> List[str]: pass

    @abc.abstractmethod
    def generate_or_correct_code(self, user_prompt: str, project_name: str, current_code: str, dependencies_to_use: List[str], project_structure_info: Optional[str] = None, execution_error: Optional[str] = None) -> str: pass

    @abc.abstractmethod
    def generate_code_stream_with_deps(self, user_request: str, project_name: str, current_code: str, dependencies_to_use: List[str], fragment_callback: Callable[[str], None], project_structure_info: Optional[str] = None ) -> str: pass

    @abc.abstractmethod
    def get_backend_name(self) -> str: pass


# ======================================================================
# --- Implémentation LM Studio ---
# ======================================================================
class LMStudioClient(BaseLLMClient):
    def __init__(self, model_identifier: Optional[str] = None):
        self.model_identifier = model_identifier
        self.model: Optional[lms.LLM] = None
        self.connected_uri: Optional[str] = None
        print(f"LMStudioClient initialized. Target: '{self.model_identifier or 'Any Loaded'}'.")

    def connect(self, host: str = DEFAULT_LM_STUDIO_IP, port: int = DEFAULT_LM_STUDIO_PORT, **kwargs) -> bool:
        self.model = None
        self.connected_uri = None
        server_uri = f"{host}:{port}"
        print(f"Attempting LM Studio connection: {server_uri}")
        try:
            client = lms.Client(server_uri)
            print(f"Getting model handle ('{self.model_identifier or 'Any Loaded'}')...")
            loaded_model = client.llm.model(self.model_identifier) if self.model_identifier else client.llm.model()
            if not loaded_model:
                 raise ConnectionError(f"Could not get ANY model handle from {server_uri}. Is a model loaded & served?")
            self.model = loaded_model

            print("Verifying LM Studio model responsiveness...")
            response = self.model.respond("Hi", config={"max_tokens": 5})
            if not response or not response.content:
                 raise ConnectionError("LM Studio model handle obtained but failed basic 'Hi' test.")

            self.connected_uri = server_uri
            loaded_name = getattr(self.model, 'model_identifier', self.model_identifier or "Currently Loaded")
            print(f"Successfully connected to LM Studio model '{loaded_name}' at {server_uri}")
            # Sauvegarde les détails de connexion réussie
            config_manager.set_last_used_lmstudio_details(host, port)
            return True

        except ConnectionRefusedError:
            print(f"ERROR: Connection refused by LM Studio at {server_uri}.")
        except lms.LMStudioWebsocketError as ws_err:
            print(f"ERROR connecting/verifying LM Studio '{server_uri}': {type(ws_err).__name__}: {ws_err}")
        except ConnectionError as ce:
            print(f"ERROR: {ce}")
        except Exception as e:
            print(f"ERROR connecting/verifying LM Studio '{server_uri}': {type(e).__name__}: {e}\n{traceback.format_exc()}")

        self.model = None
        return False

    def is_available(self) -> bool:
        return self.model is not None

    def identify_dependencies_from_request(self, user_prompt: str, project_name: str, project_structure_info: Optional[str] = None) -> List[str]:
        if not self.is_available(): return ["ERROR: LLM not available"]
        if not PYDANTIC_AVAILABLE: return ["ERROR: Pydantic library is required for structured dependency parsing with LM Studio."]

        log_prefix = "[LMStudio ID_Deps_Req_Pydantic]"
        structure_context = ""
        if project_structure_info:
            structure_context = (
                f"\n**Project File Structure Context:**\n"
                f"The project currently contains these files/folders (relative to the main script):\n"
                f"```\n{project_structure_info}\n```\n"
                f"Consider this structure when inferring dependencies (e.g., image files might suggest 'Pillow' or 'pygame')."
            )

        system_prompt = (
            f"You are an expert Python dependency analyzer for project '{project_name}'.\n"
            f"**ROLE:** Analyze the user's request to understand the **type** of application being built (e.g., GUI game, web scraper, command-line tool, data analysis script, etc.).{structure_context}\n"
            f"**TASK:** Based on the inferred application type, user's request, and potentially the project structure, list ONLY the essential external, non-standard Python libraries needed for a typical implementation.\n"
            f"**INFERENCE:** You MUST infer common libraries even if not explicitly mentioned. For example:\n"
            f"  - If the request describes a graphical game (like snake, pong, space invaders), you MUST include 'pygame' unless another GUI library is specified.\n"
            f"  - If the request involves fetching data from a web URL, you MUST include 'requests'.\n"
            f"  - If the request involves parsing HTML, you likely need 'beautifulsoup4'.\n"
            f"  - If it involves data manipulation or numerical tasks, consider 'pandas' or 'numpy'.\n"
            f"  - If image files are present or requested, consider 'Pillow' (PIL fork).\n"
            f"**CONSTRAINTS:**\n"
            f"1. List ONLY the package names as strings (e.g., `['pygame', 'requests']`).\n"
            f"2. EXCLUDE Python standard libraries (like `os`, `sys`, `json`, `re`, `math`, `random`, `time`, `tkinter`, `collections`, `datetime`).\n"
            f"3. If the request describes a simple script requiring ONLY standard libraries, provide an empty list `[]`.\n"
            f"4. Your entire output MUST be ONLY the JSON object matching the required schema. No explanations or other text."
        )

        print(f"{log_prefix} Requesting dependencies for prompt: '{user_prompt[:60]}...' using Pydantic format.")
        dependencies = []

        try:
            chat = lms.Chat(system_prompt)
            chat.add_user_message(user_prompt)
            print(f"{log_prefix} Sending chat context to LLM for structured response...")

            prediction_stream: Generator[Any, Any, Any] = self.model.respond_stream(
                chat,
                response_format=DependencyList
            )

            print(f"{log_prefix} Consuming stream and waiting for parsed result...")
            final_raw_content = "".join([chunk.content for chunk in prediction_stream if chunk and hasattr(chunk, 'content') and chunk.content])

            parsed_result: Optional[DependencyList] = None
            stream_result_obj = None
            try:
                 if hasattr(prediction_stream, 'result'):
                      stream_result_obj = prediction_stream.result()
                 if hasattr(stream_result_obj, 'parsed') and isinstance(stream_result_obj.parsed, DependencyList):
                      parsed_result = stream_result_obj
                 elif isinstance(stream_result_obj, DependencyList):
                      parsed_result = stream_result_obj
            except Exception as res_err:
                 print(f"{log_prefix} WARN: Error accessing stream result: {res_err}")

            print(f"{log_prefix} Processing parsed result...")
            if parsed_result and isinstance(parsed_result, DependencyList):
                 raw_deps = parsed_result.dependencies
                 if isinstance(raw_deps, list) and all(isinstance(d, str) for d in raw_deps):
                     dependencies = [dep.strip() for dep in raw_deps if dep.strip()]
                     print(f"{log_prefix} Dependencies parsed successfully via Pydantic: {dependencies}")
                 else:
                     print(f"{log_prefix} WARN: Parsed 'dependencies' field not a list of strings: {raw_deps}. Assuming none.")
                     dependencies = []
            else:
                # Fallback Regex/AST si Pydantic échoue
                print(f"{log_prefix} WARN: Could not obtain parsed DependencyList object.")
                print(f"       Raw response received (first 250 chars): {final_raw_content[:250]}...")
                match = re.search(r"(\[.*?\])", final_raw_content, re.DOTALL)
                if match:
                    try:
                        parsed_list_fb = ast.literal_eval(match.group(1))
                        if isinstance(parsed_list_fb, list) and all(isinstance(item, str) for item in parsed_list_fb):
                            dependencies = [dep.strip() for dep in parsed_list_fb if dep.strip()]
                            print(f"{log_prefix} Dependencies parsed via fallback regex/ast: {dependencies}")
                        else: raise ValueError("Fallback content not list[str]")
                    except Exception as e_fb:
                        dependencies = [f"ERROR: Failed to parse Pydantic & fallback failed ({e_fb}): {final_raw_content[:100]}..."]
                else:
                     dependencies = ["ERROR: Failed to parse dependencies (Pydantic failed, no list found in raw text)."]

        except lms.LMStudioWebsocketError as ws_err:
             print(f"{log_prefix} EXCEPTION (WebSocket): {ws_err}")
             dependencies = [f"ERROR: LMStudio Connection Error: {ws_err}"]
        except Exception as e:
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            dependencies = [f"ERROR: {type(e).__name__}: {e}"]

        # Filtrage final
        final_deps = [dep for dep in dependencies if not dep.startswith("ERROR:")]
        errors = [dep for dep in dependencies if dep.startswith("ERROR:")]
        if errors and not final_deps: return errors # Retourne seulement les erreurs si aucune dépendance trouvée
        elif errors and final_deps: print(f"{log_prefix} Warning: Found dependencies but also errors: {errors}")
        return final_deps

    def generate_or_correct_code(self, user_prompt: str, project_name: str, current_code: str, dependencies_to_use: List[str], project_structure_info: Optional[str] = None, execution_error: Optional[str] = None) -> str:
        # ... (vérification is_available inchangée) ...

        log_prefix = "[LMStudio Correct]" if execution_error else "[LMStudio GenInit]"
        task_desc = "CORRECT the Python code below" if execution_error else "GENERATE Python code"
        error_info = ""
        # Instruction légèrement renforcée
        instruction = "Output ONLY the complete, runnable Python code using the specified dependencies. Wrap the ENTIRE code output in a single ```python ... ``` markdown block. Do NOT include any explanation or commentary outside the code block."

        if execution_error:
            # <<< PROMPT AJUSTÉ ICI >>>
            error_info = (
                f"The previous code execution failed. CRITICAL: You MUST fix the following specific error:\n"
                f"```text\n{execution_error.strip()}\n```\n"
                f"Base the correction ONLY on this error and the original user request, using the specified dependencies."
            )
            instruction = "Output ONLY the complete, corrected Python code in a single ```python ... ``` block, using the specified dependencies. Do NOT explain the changes outside the code itself (comments inside the code are acceptable)."
            # <<< FIN AJUSTEMENT >>>
        elif not current_code:
             instruction = "Output ONLY the complete Python code for the user request in a single ```python ... ``` block, using the specified dependencies. Do NOT add any explanation or commentary outside the code block."

        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))
        deps_info = f"You MUST use the following external libraries (if needed by the request): {deps_list_str if deps_list_str else 'Only standard Python libraries'}."
        structure_context = ""
        if project_structure_info: structure_context = f"\n**Project File Structure Context:**...\n```\n{project_structure_info}\n```..." # (comme avant)
        code_block_header = 'Code to Correct/Generate' if current_code else 'User Request (for initial code)'
        if current_code: code_or_request_formatted = f"```python\n{current_code}\n```"
        else: code_or_request_formatted = f"User Request: {user_prompt}"

        system_prompt = (
            f"You are Pythautom, an AI assistant for project '{project_name}'.\n"
            f"Task: {task_desc}.\n{deps_info}\n{structure_context}\n{error_info}\n\n" # error_info est vide si pas d'erreur
            f"{code_block_header}:\n{code_or_request_formatted}\n\n"
            f"{instruction}"
        ).strip()
        if execution_error: system_prompt += f"\n\nOriginal User Request Context (for guidance): {user_prompt}"

        # ... (reste de la fonction : appel LLM, gestion erreur - inchangé) ...
        print(f"{log_prefix} Requesting code (only) for: '{user_prompt[:50]}...' using deps: {deps_list_str}")
        try:
            chat = lms.Chat(system_prompt)
            response = self.model.respond(chat)
            full_response_content = response.content if response else ""
            print(f"{log_prefix} Full response received.")
            return full_response_content
        except Exception as e:
            error_msg = f"\n\n# --- LLM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs.\n# --- END LLM ERROR --- #"
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            return error_msg

    def generate_code_stream_with_deps(
        self,
        user_request: str,
        project_name: str,
        current_code: str,
        dependencies_to_use: List[str],
        fragment_callback: Callable[[str], None],
        project_structure_info: Optional[str] = None,
        cancellation_check: Optional[Callable[[], bool]] = None # <<< AJOUT DU PARAMÈTRE
    ) -> str:
        if not self.is_available():
            err_msg = "# --- ERROR: LM Studio model not loaded. --- #"
            try: fragment_callback(f"\nSTREAM ERROR: {err_msg}\n")
            except Exception as cb_err: print(f"Error sending LLM unavailable msg via callback: {cb_err}")
            return err_msg

        log_prefix = "[LMStudio Stream]"
        is_initial = not bool(current_code.strip())
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))

        # --- Construction du Prompt SIMPLIFIÉ (inchangé) ---
        prompt_lines = [
            f"You are Pythautom, an AI assistant writing Python code for project '{project_name}'.",
            f"{'Generate Python code based on this request:' if is_initial else 'Refine the following Python code based on the request below:'}",
            f"\nRequest: {user_request}"
        ]
        if not is_initial:
            prompt_lines.append(f"\nCurrent Code to Refine:\n```python\n{current_code}\n```")
        prompt_lines.append(f"\nRequired Dependencies: {deps_list_str or 'Standard libraries only'}.")
        if project_structure_info:
            prompt_lines.append(f"\nProject Files Context (for relative paths):\n```\n{project_structure_info}\n```")
        prompt_lines.append(f"\nInstructions: Output ONLY the complete, runnable Python code wrapped in a single ```python ... ``` block. No extra explanations.")
        system_prompt = "\n".join(line for line in prompt_lines if line)
        # --- Fin du Prompt ---

        print(f"{log_prefix} Requesting code stream for: '{user_request[:50]}...' using deps: {deps_list_str}")
        full_response_content = ""
        try:
            chat = lms.Chat(system_prompt)
            # LM Studio peut nécessiter un ajustement des kwargs ici si des options spécifiques sont nécessaires
            prediction_stream = self.model.respond_stream(chat)
            fragment_count = 0
            print(f"{log_prefix} Starting to stream fragments...")

            for fragment in prediction_stream:
                 # --- VÉRIFICATION ANNULATION (AVANT TRAITEMENT CHUNK) ---
                 if cancellation_check and cancellation_check():
                     print(f"{log_prefix} Cancellation detected inside stream loop. Breaking.")
                     break # Sort de la boucle for
                 # ---------------------------------------------------------

                 # Vérifie si le fragment est valide avant de continuer
                 if fragment and hasattr(fragment, 'content') and isinstance(fragment.content, str):
                    content_piece = fragment.content
                    full_response_content += content_piece
                    try:
                        fragment_callback(content_piece) # Envoie à l'UI
                    except Exception as cb_err:
                        print(f"Error in fragment_callback: {cb_err}")
                        # Optionnel: sortir de la boucle si callback échoue ?
                        # break
                    fragment_count += 1
                 # Optionnel: else: print(f"{log_prefix} Received invalid fragment: {fragment}")

            print(f"{log_prefix} Finished streaming loop ({fragment_count} fragments processed). Returning accumulated response.")
            if cancellation_check and cancellation_check():
                 full_response_content += "\n# --- STREAM MANUALLY CANCELLED ---"
            return full_response_content

        except Exception as e:
            # Vérifie si l'annulation était déjà demandée
            if cancellation_check and cancellation_check():
                 print(f"{log_prefix} Exception occurred ({type(e).__name__}), but cancellation was already requested. Ignoring error reporting.")
                 return full_response_content + "\n# --- STREAM CANCELLED DURING EXCEPTION ---"

            # Gère les vraies erreurs
            error_msg = f"# --- LLM STREAM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs."
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            try: fragment_callback(f"\nSTREAM ERROR: {e}\n")
            except Exception as cb_err_exc: print(f"Error sending exception via callback: {cb_err_exc}")
            return error_msg



    def resolve_package_name_from_import_error(self, module_name: str, error_message: str) -> Tuple[Optional[str], Optional[str]]:
        if not self.is_available(): return None, "ERROR: LLM not available"
        log_prefix = "[LMStudio ResolveImport]"

        system_prompt = (
            f"You are a Python package expert. A user encountered the following import error:\n"
            f"```text\n{error_message}\n```\n"
            f"The error indicates that the module '{module_name}' could not be found.\n"
            f"**TASK:** Determine the correct **pip package name** that typically provides this module '{module_name}'.\n"
            f"**Examples:**\n"
            f" - If module is 'cv2', package is 'opencv-python'.\n"
            f" - If module is 'bs4', package is 'beautifulsoup4'.\n"
            f" - If module is 'yaml', package is 'PyYAML'.\n"
            f" - If module is 'sklearn', package is 'scikit-learn'.\n"
            f" - If module is 'requests', package is 'requests'.\n"
            f"**Output:** Respond with ONLY the correct pip package name (e.g., `opencv-python`). If you are unsure or the module doesn't correspond to a common package, respond with `UNKNOWN`."
        )
        print(f"{log_prefix} Requesting package name for module '{module_name}'")
        try:
            # Utilise un chat simple, pas de format structuré nécessaire ici
            chat = lms.Chat(system_prompt)
            response = self.model.respond(chat, config={"temperature": 0.1}) # Basse température pour réponse directe
            package_name = response.content.strip() if response else ""

            if package_name and package_name.upper() != "UNKNOWN" and not ' ' in package_name: # Vérification simple
                print(f"{log_prefix} Resolved package name: {package_name}")
                return package_name, None
            elif package_name.upper() == "UNKNOWN":
                 print(f"{log_prefix} LLM indicated UNKNOWN package name.")
                 return None, f"LLM could not determine package for module '{module_name}'."
            else:
                 print(f"{log_prefix} LLM returned potentially invalid package name: '{package_name}'")
                 return None, f"LLM returned potentially invalid name: '{package_name}'"

        except Exception as e:
            error_msg = f"LLM Error during package resolution: {e}"
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            return None, error_msg


    def get_backend_name(self) -> str:
        return "LM Studio"


# ======================================================================
# --- Implémentation Google Gemini ---
# ======================================================================
class GeminiClient(BaseLLMClient):
    def __init__(self):
        self.model_client: Optional[genai.GenerativeModel] = None
        self.api_key: Optional[str] = None
        self.model_name: Optional[str] = None
        print("GeminiClient initialized.")
        if not GOOGLE_GENAI_AVAILABLE:
            print("ERROR: Gemini backend requires 'google-generativeai'.")

    # --- Fonctions helper (inchangées) ---
    def _extract_text_from_gemini_response(self, response: Any) -> str:
        try: return response.text
        except ValueError:
             try: return response.parts[0].text
             except Exception: return ""
        except Exception: return ""

    def _get_gemini_block_reason(self, response: Any) -> str:
        try:
            reason = response.prompt_feedback.block_reason
            if reason: return f" (Block Reason: {reason})"
        except Exception: pass
        return ""
    # --- Fin Fonctions helper ---

    # --- connect (simplifié pour n'utiliser que GenerativeModel) ---
    def connect(self, api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, **kwargs) -> bool:
        if not GOOGLE_GENAI_AVAILABLE:
            print("ERROR: Cannot connect, 'google-generativeai' not installed.")
            return False

        self.model_client = None
        self.api_key = None
        self.model_name = None
        print(f"Configuring Gemini with model: {model_name}")
        if not api_key: print("ERROR: Gemini API Key missing."); return False
        if not model_name: print("ERROR: Gemini model name missing."); return False

        try:
            genai.configure(api_key=api_key)
            print(f"Using genai.GenerativeModel for model '{model_name}'...")
            model = genai.GenerativeModel(model_name)

            print("Verifying Gemini model responsiveness...")
            response = model.generate_content(
                "Hi",
                generation_config=genai.types.GenerationConfig(max_output_tokens=5),
                safety_settings=None
            )
            response_text = self._extract_text_from_gemini_response(response)
            block_reason = self._get_gemini_block_reason(response)

            if not response_text:
                 raise ConnectionError(f"Gemini test failed (model: {model_name}). No response text.{block_reason}")

            self.model_client = model
            self.api_key = api_key
            self.model_name = model_name
            print(f"Successfully configured Gemini with model '{model_name}'.")
            config_manager.set_last_used_gemini_model(model_name)
            return True
        except Exception as e:
            print(f"ERROR configuring/connecting Gemini: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            self.model_client = None
            self.api_key = None
            self.model_name = None
            return False

    def is_available(self) -> bool:
        return self.model_client is not None

    # --- identify_dependencies (simplifié) ---
    def identify_dependencies_from_request(self, user_prompt: str, project_name: str, project_structure_info: Optional[str] = None) -> List[str]:
        if not self.model_client: return ["ERROR: Gemini client not loaded"]

        log_prefix = "[Gemini ID_Deps_Req]"
        structure_context = ""
        if project_structure_info:
            structure_context = f"\n**Project File Structure Context:**\n```\n{project_structure_info}\n```..."

        system_prompt = (
            f"You are an expert Python dependency analyzer for project '{project_name}'.\n"
            f"**ROLE:** Analyze the user's request to understand the **type** of application being built (e.g., GUI game, web scraper, command-line tool, data analysis script, etc.).{structure_context}\n"
            f"**TASK:** Based on the inferred application type, user's request, and potentially the project structure, list ONLY the essential external, non-standard Python libraries needed for a typical implementation.\n"
            f"**INFERENCE:** You MUST infer common libraries even if not explicitly mentioned. For example:\n"
            f"  - If the request describes a graphical game (like snake, pong, space invaders), you MUST include 'pygame' unless another GUI library is specified.\n"
            f"  - If the request involves fetching data from a web URL, you MUST include 'requests'.\n"
            f"  - If the request involves parsing HTML, you likely need 'beautifulsoup4'.\n"
            f"  - If it involves data manipulation or numerical tasks, consider 'pandas' or 'numpy'.\n"
            f"  - If image files are present or requested, consider 'Pillow' (PIL fork).\n"
            f"**CONSTRAINTS:**\n"
            f"1. List ONLY the package names as strings (e.g., `['pygame', 'requests']`).\n"
            f"2. EXCLUDE Python standard libraries (like `os`, `sys`, `json`, `re`, `math`, `random`, `time`, `tkinter`, `collections`, `datetime`).\n"
            f"3. If the request describes a simple script requiring ONLY standard libraries, provide an empty list `[]`.\n"
            f"4. Your entire output MUST be ONLY the JSON object matching the required schema. No explanations or other text."
        )
        
        full_prompt = f"{system_prompt}\n\nUser Request: {user_prompt}"
        dependencies = []
        print(f"{log_prefix} Requesting dependencies for: '{user_prompt[:60]}...'")

        try:
            response = self.model_client.generate_content(full_prompt, safety_settings=None)
            raw_response_text = self._extract_text_from_gemini_response(response).strip()
            block_reason = self._get_gemini_block_reason(response)
            print(f"{log_prefix} Raw response: '{raw_response_text}' {block_reason}")

            if not raw_response_text and not block_reason:
                dependencies = ["ERROR: No dependency list received."]
            elif block_reason:
                dependencies = [f"ERROR: Response blocked.{block_reason}"]
            else:
                # Parsing (inchangé)
                try:
                    parsed_list = ast.literal_eval(raw_response_text)
                    if isinstance(parsed_list, list) and all(isinstance(item, str) for item in parsed_list):
                        dependencies = [dep.strip() for dep in parsed_list if dep.strip()]
                    else: raise ValueError("Not list[str]")
                except (ValueError, SyntaxError, TypeError) as parse_err:
                     match = re.search(r"(\[.*?\])", raw_response_text, re.DOTALL)
                     if match:
                         try:
                             parsed_list_fb = ast.literal_eval(match.group(1))
                             dependencies = [d.strip() for d in parsed_list_fb if isinstance(d,str) and d.strip()]
                         except Exception as e_fb: dependencies = [f"ERROR: Fallback failed ({e_fb}): {raw_response_text}"]
                     else: dependencies = [f"ERROR: Could not parse deps (initial failed: {parse_err}): {raw_response_text}"]

        except Exception as e:
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            dependencies = [f"ERROR: {type(e).__name__}: {e}"]

        # Filtrage (inchangé)
        final_deps = [dep for dep in dependencies if not dep.startswith("ERROR:")]
        errors = [dep for dep in dependencies if dep.startswith("ERROR:")]
        if errors and not final_deps: return errors
        elif errors and final_deps: print(f"{log_prefix} Warning: Found dependencies but also errors: {errors}")
        return final_deps

    # --- generate_or_correct_code (simplifié) ---

    def generate_or_correct_code(self, user_prompt: str, project_name: str, current_code: str, dependencies_to_use: List[str], project_structure_info: Optional[str] = None, execution_error: Optional[str] = None) -> str:
        # ... (vérification model_client inchangée) ...

        log_prefix = "[Gemini Correct]" if execution_error else "[Gemini GenInit]"
        task_desc = "CORRECT the Python code below" if execution_error else "GENERATE Python code"
        error_info = ""
        instruction = "Output ONLY the complete, runnable Python code... ```python ... ``` block..." # (comme avant)

        if execution_error:
             # <<< PROMPT AJUSTÉ ICI >>>
            error_info = (
                f"The previous code execution failed. CRITICAL: You MUST fix the following specific error:\n"
                f"```text\n{execution_error.strip()}\n```\n"
                f"Base the correction ONLY on this error and the original user request, using the specified dependencies."
            )
            instruction = "Output ONLY the complete, corrected code in a single ```python ... ``` block. NO explanations outside."
            # <<< FIN AJUSTEMENT >>>
        elif not current_code:
            instruction = "Output ONLY the complete code..."

        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))
        deps_info = f"MUST use libraries: {deps_list_str if deps_list_str else 'Only standard libs'}."
        structure_context = ""
        if project_structure_info: structure_context = f"\n**Project File Structure Context:**...\n```\n{project_structure_info}\n```..." # (comme avant)
        code_block_header = 'Code to Correct/Generate' if current_code else 'User Request (for initial code)'
        if current_code: code_or_request_formatted = f"```python\n{current_code}\n```"
        else: code_or_request_formatted = f"User Request: {user_prompt}"

        prompt_lines = [
            f"You are Pythautom AI for project '{project_name}'.", f"Task: {task_desc}.",
            deps_info, structure_context, error_info if error_info else "",
            f"\n{code_block_header}:\n{code_or_request_formatted}",
            f"\n{instruction}",
        ]
        if execution_error: prompt_lines.append(f"\n\nOriginal User Request Context (for guidance): {user_prompt}")
        full_prompt = "\n".join(line for line in prompt_lines if line) # Filtre lignes vides

        # ... (reste de la fonction : appel LLM, gestion erreur - inchangé) ...
        print(f"{log_prefix} Requesting code for: '{user_prompt[:50]}...' deps: {deps_list_str}")
        try:
            response = self.model_client.generate_content(full_prompt, safety_settings=None) # Utilise les safety settings par défaut ou ceux configurés globalement
            full_response_content = self._extract_text_from_gemini_response(response)
            block_reason = self._get_gemini_block_reason(response)
            if block_reason: full_response_content += f"\n# --- GEMINI ERROR: {block_reason} --- #"
            print(f"{log_prefix} Full response received.")
            return full_response_content
        except Exception as e:
            error_msg = f"# --- LLM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs."
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            return error_msg


    # --- generate_code_stream_with_deps (simplifié) ---

    def generate_code_stream_with_deps(
        self,
        user_request: str,
        project_name: str,
        current_code: str,
        dependencies_to_use: List[str],
        fragment_callback: Callable[[str], None],
        project_structure_info: Optional[str] = None,
        cancellation_check: Optional[Callable[[], bool]] = None # <<< NOUVEAU PARAMÈTRE
    ) -> str:
        if not self.model_client:
            err_msg = "# --- ERROR: Gemini client not loaded. --- #"
            try: fragment_callback(f"\nSTREAM ERROR: {err_msg}\n")
            except Exception as cb_err: print(f"Error sending Gemini unavailable msg via callback: {cb_err}")
            return err_msg

        log_prefix = "[Gemini Stream]"
        is_initial = not bool(current_code.strip())
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))

        # --- Construction du Prompt SIMPLIFIÉ (inchangé) ---
        prompt_lines = [
            f"You are Pythautom, an AI assistant writing Python code for project '{project_name}'.",
            f"{'Generate Python code based on this request:' if is_initial else 'Refine the following Python code based on the request below:'}",
            f"\nRequest: {user_request}"
        ]
        if not is_initial:
            prompt_lines.append(f"\nCurrent Code to Refine:\n```python\n{current_code}\n```")
        prompt_lines.append(f"\nRequired Dependencies: {deps_list_str or 'Standard libraries only'}.")
        if project_structure_info:
            prompt_lines.append(f"\nProject Files Context (for relative paths):\n```\n{project_structure_info}\n```")
        prompt_lines.append(f"\nInstructions: Output ONLY the complete, runnable Python code wrapped in a single ```python ... ``` block. No extra explanations.")
        full_prompt = "\n".join(line for line in prompt_lines if line)
        # --- Fin du Prompt ---

        # Safety settings (inchangé)
        less_strict_safety_settings = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE, }

        print(f"{log_prefix} Requesting stream for: '{user_request[:50]}...' deps: {deps_list_str}")
        full_response_content = ""; fragment_count = 0

        try:
            prediction_stream = self.model_client.generate_content(
                full_prompt,
                stream=True,
                safety_settings=less_strict_safety_settings
            )

            print(f"{log_prefix} Starting to stream fragments...")
            for chunk in prediction_stream:
                 # --- VÉRIFICATION ANNULATION (AVANT TRAITEMENT CHUNK) ---
                 if cancellation_check and cancellation_check():
                     print(f"{log_prefix} Cancellation detected inside stream loop. Breaking.")
                     # Optionnel: envoyer un message indiquant l'annulation ?
                     # try: fragment_callback("\n--- Stream Cancelled ---\n")
                     # except Exception: pass
                     break # Sort de la boucle for
                 # ---------------------------------------------------------

                 block_reason = self._get_gemini_block_reason(chunk)
                 if block_reason:
                     error_msg_block = f"# --- GEMINI STREAM ERROR: Blocked{block_reason} --- #"
                     print(f"{log_prefix} Stream blocked: {block_reason}")
                     full_response_content += error_msg_block
                     try: fragment_callback(f"\nSTREAM ERROR: Blocked - {block_reason}\n")
                     except Exception as cb_err_block: print(f"Error sending block reason via callback: {cb_err_block}")
                     break # Sort aussi si bloqué

                 chunk_text = self._extract_text_from_gemini_response(chunk)
                 if chunk_text:
                     full_response_content += chunk_text
                     try: fragment_callback(chunk_text) # Envoie le fragment à l'UI
                     except Exception as cb_err: print(f"Error in fragment_callback: {cb_err}")
                     fragment_count += 1

                 # Optionnel: petit délai pour laisser l'event loop respirer et vérifier l'annulation plus souvent
                 # time.sleep(0.01) # Peut ralentir un peu le stream

            print(f"{log_prefix} Finished streaming loop ({fragment_count} fragments processed). Returning accumulated response.")
            # Le message final dépend si on est sorti par break ou normalement
            if cancellation_check and cancellation_check():
                 # Si on sort par break à cause de l'annulation, on peut ajouter un marqueur
                 full_response_content += "\n# --- STREAM MANUALLY CANCELLED ---"

            return full_response_content

        except Exception as e:
            # Vérifie si l'exception est due à une annulation déjà en cours
            # (Moins fiable, mais peut éviter des logs d'erreur inutiles)
            if cancellation_check and cancellation_check():
                 print(f"{log_prefix} Exception occurred ({type(e).__name__}), but cancellation was already requested. Ignoring error reporting.")
                 return full_response_content + "\n# --- STREAM CANCELLED DURING EXCEPTION ---"

            # Gère les vraies erreurs
            error_msg_exc = f"# --- LLM STREAM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs."
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}") # Log complet de l'erreur
            try: fragment_callback(f"\nSTREAM ERROR: {e}\n")
            except Exception as cb_err_exc: print(f"Error sending exception via callback: {cb_err_exc}")
            return error_msg_exc



    def resolve_package_name_from_import_error(self, module_name: str, error_message: str) -> Tuple[Optional[str], Optional[str]]:
        if not self.model_client: return None, "ERROR: Gemini client not loaded"
        log_prefix = "[Gemini ResolveImport]"

        prompt = (
             f"You are a Python package expert. A user encountered the following import error:\n"
            f"```text\n{error_message}\n```\n"
            f"The error indicates that the module '{module_name}' could not be found.\n"
            f"**TASK:** Determine the correct **pip package name** that typically provides this module '{module_name}'.\n"
            f"**Examples:**\n"
            f" - If module is 'cv2', package is 'opencv-python'.\n"
            f" - If module is 'bs4', package is 'beautifulsoup4'.\n"
            f" - If module is 'yaml', package is 'PyYAML'.\n"
            f" - If module is 'sklearn', package is 'scikit-learn'.\n"
            f" - If module is 'requests', package is 'requests'.\n"
            f"**Output:** Respond with ONLY the correct pip package name (e.g., `opencv-python`). If you are unsure or the module doesn't correspond to a common package, respond with `UNKNOWN`."
        )
        print(f"{log_prefix} Requesting package name for module '{module_name}'")
        try:
            response = self.model_client.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.1),
                safety_settings=None # Utilise défauts
            )
            package_name = self._extract_text_from_gemini_response(response).strip()
            block_reason = self._get_gemini_block_reason(response)

            if block_reason:
                return None, f"LLM response blocked: {block_reason}"
            elif package_name and package_name.upper() != "UNKNOWN" and not ' ' in package_name:
                print(f"{log_prefix} Resolved package name: {package_name}")
                return package_name, None
            elif package_name.upper() == "UNKNOWN":
                 print(f"{log_prefix} LLM indicated UNKNOWN package name.")
                 return None, f"LLM could not determine package for module '{module_name}'."
            else:
                 print(f"{log_prefix} LLM returned potentially invalid package name: '{package_name}'")
                 return None, f"LLM returned potentially invalid name: '{package_name}'"

        except Exception as e:
            error_msg = f"LLM Error during package resolution: {e}"
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            return None, error_msg



    def get_backend_name(self) -> str:
        return "Google Gemini"