# src/llm_interaction.py

import lmstudio as lms
import traceback
import json
import re
import ast # Pour l'analyse des listes de dépendances
import abc # Pour la classe de base abstraite
from typing import List, Callable, Optional, Generator, Any, Dict, Tuple

# --- Import Pydantic (optionnel mais utilisé pour LM Studio) ---
try:
    from pydantic import BaseModel, Field, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    print("WARNING: pydantic library not found. Structured output parsing might be less reliable.")
    PYDANTIC_AVAILABLE = False
    # Définition de classes factices si pydantic n'est pas disponible pour éviter les NameErrors
    class BaseModel: pass
    def Field(*args, **kwargs): return None
    class ValidationError(Exception): pass
# --- FIN Pydantic ---


# Essaye d'importer google.generativeai
try:
    import google.generativeai as genai
    # --- AJOUTER CES IMPORTS ICI ---
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    # ------------------------------
    # Configure les paramètres de sécurité globalement ou par requête si nécessaire
    safety_settings = None # Utilise les valeurs par défaut ou définissez selon les besoins
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("WARNING: google-generativeai library not found. Gemini backend will not be available.")
    GOOGLE_GENAI_AVAILABLE = False
    safety_settings = None # Définit à None si la bibliothèque n'est pas disponible
    # Définir des dummies si l'import échoue pour éviter NameError plus tard
    class HarmCategory:
        HARM_CATEGORY_HARASSMENT = None
        HARM_CATEGORY_HATE_SPEECH = None
        HARM_CATEGORY_SEXUALLY_EXPLICIT = None
        HARM_CATEGORY_DANGEROUS_CONTENT = None
    class HarmBlockThreshold:
        BLOCK_NONE = None
        BLOCK_ONLY_HIGH = None
# --- FIN Import google.generativeai ---

# --- Configuration ---
DEFAULT_LM_STUDIO_IP = "127.0.0.1"
DEFAULT_LM_STUDIO_PORT = 1234
AVAILABLE_GEMINI_MODELS = ["gemma-3-27b-it", "gemini-2.0-flash-exp-image-generation", "gemini-2.0-flash-thinking-exp-01-21"]
DEFAULT_GEMINI_MODEL = AVAILABLE_GEMINI_MODELS[0]

# --- Schéma Pydantic pour les Dépendances ---
class DependencyList(BaseModel):
    # Utilise default_factory pour assurer qu'une liste vide est créée si la clé est manquante
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of NON-STANDARD Python libraries required (e.g., ['pygame', 'requests']). Exclude standard libs (os, sys, json, etc.). Empty list if none needed."
    )

# --- Classe de Base Abstraite pour les Clients LLM ---
class BaseLLMClient(abc.ABC):
    @abc.abstractmethod
    def connect(self, **kwargs) -> bool:
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        pass

    # NOUVEAU: Identifie les deps basé sur le texte de la requête utilisateur
    @abc.abstractmethod
    def identify_dependencies_from_request(self, user_prompt: str, project_name: str) -> List[str]:
        """
        Analyse le prompt texte de l'utilisateur pour prédire les dépendances externes nécessaires.
        Retourne une liste de chaînes de dépendances. Non-streaming.
        """
        pass

    # MODIFIÉ: Prend les dépendances comme entrée explicite pour la génération/correction
    @abc.abstractmethod
    def generate_or_correct_code(self,
                                user_prompt: str,
                                project_name: str,
                                current_code: str, # Peut être vide pour la génération initiale
                                dependencies_to_use: List[str], # Dépendances explicites
                                execution_error: Optional[str] = None) -> str: # Retourne SEULEMENT la chaîne de code
        """
        Génère le code initial ou corrige le code existant basé sur le prompt/erreur utilisateur,
        en utilisant la liste de dépendances fournie. Non-streaming. Retourne la chaîne de code complète.
        """
        pass

    # MODIFIÉ: Prend les dépendances comme entrée explicite pour la génération en streaming
    @abc.abstractmethod
    def generate_code_stream_with_deps(self,
                                      user_request: str,
                                      project_name: str,
                                      current_code: str, # Utilisé pour le contexte d'affinage
                                      dependencies_to_use: List[str], # Dépendances explicites
                                      fragment_callback: Callable[[str], None]) -> str: # Retourne la chaîne de code COMPLÈTE à la fin
        """
        Génère ou affine le code basé sur la requête utilisateur en utilisant les dépendances fournies.
        Streame les fragments de code via callback, retourne la chaîne de code complète après la fin du stream.
        """
        pass

    @abc.abstractmethod
    def get_backend_name(self) -> str:
        pass

# --- Implémentation LM Studio ---
class LMStudioClient(BaseLLMClient):
    def __init__(self, model_identifier: Optional[str] = None):
        self.model_identifier = model_identifier
        self.model: Optional[lms.LLM] = None
        self.connected_uri: Optional[str] = None
        print(f"LMStudioClient initialized. Target: '{self.model_identifier or 'Any Loaded'}'.")

    def connect(self, host: str = DEFAULT_LM_STUDIO_IP, port: int = DEFAULT_LM_STUDIO_PORT, **kwargs) -> bool:
        self.model = None; self.connected_uri = None
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
            return True

        except ConnectionRefusedError: print(f"ERROR: Connection refused by LM Studio at {server_uri}.")
        except lms.LMStudioWebsocketError as ws_err:
            print(f"ERROR connecting/verifying LM Studio '{server_uri}': {type(ws_err).__name__}: {ws_err}")
        except ConnectionError as ce: print(f"ERROR: {ce}")
        except Exception as e: print(f"ERROR connecting/verifying LM Studio '{server_uri}': {type(e).__name__}: {e}\n{traceback.format_exc()}")
        self.model = None
        return False

    def is_available(self) -> bool:
        return self.model is not None

    # --- UTILISE LE PROMPT AMÉLIORÉ POUR L'IDENTIFICATION DES DÉPENDANCES ---
    def identify_dependencies_from_request(self, user_prompt: str, project_name: str) -> List[str]:
        """
        Identifie les dépendances en utilisant lms.Chat + response_format avec un prompt amélioré.
        """
        if not self.is_available(): return ["ERROR: LLM not available"]
        if not PYDANTIC_AVAILABLE: return ["ERROR: Pydantic library is required for structured dependency parsing with LM Studio."]

        log_prefix = "[LMStudio ID_Deps_Req_Pydantic]"
        # --- PROMPT AMÉLIORÉ ---
        system_prompt = (
            f"You are an expert Python dependency analyzer for project '{project_name}'.\n"
            f"**ROLE:** Analyze the user's request to understand the **type** of application being built (e.g., GUI game, web scraper, command-line tool, data analysis script, etc.).\n"
            f"**TASK:** Based on the inferred application type and the user's request, list ONLY the essential external, non-standard Python libraries needed for a typical implementation.\n"
            f"**INFERENCE:** You MUST infer common libraries even if not explicitly mentioned. For example:\n"
            f"  - If the request describes a graphical game (like snake, pong, space invaders), you MUST include 'pygame' unless another GUI library is specified.\n"
            f"  - If the request involves fetching data from a web URL, you MUST include 'requests'.\n"
            f"  - If the request involves parsing HTML, you likely need 'beautifulsoup4'.\n"
            f"  - If it involves data manipulation or numerical tasks, consider 'pandas' or 'numpy'.\n"
            f"**CONSTRAINTS:**\n"
            f"1. List ONLY the package names as strings (e.g., `['pygame', 'requests']`).\n"
            f"2. EXCLUDE Python standard libraries (like `os`, `sys`, `json`, `re`, `math`, `random`, `time`, `tkinter`, `collections`, `datetime`).\n"
            f"3. If the request describes a simple script requiring ONLY standard libraries, provide an empty list `[]`.\n"
            f"4. Your entire output MUST be ONLY the JSON object matching the required schema. No explanations or other text."
        )
        # --- FIN PROMPT AMÉLIORÉ ---

        print(f"{log_prefix} Requesting dependencies for prompt: '{user_prompt[:60]}...' using Pydantic format.")
        dependencies = []

        try:
            chat = lms.Chat(system_prompt)
            chat.add_user_message(user_prompt)
            print(f"{log_prefix} Sending chat context to LLM for structured response...")

            prediction_stream: Generator[Any, Any, Any] = self.model.respond_stream(
                chat,
                response_format=DependencyList # Utilise la classe Pydantic
            )

            print(f"{log_prefix} Consuming stream and waiting for parsed result...")
            final_content_list = []
            for chunk in prediction_stream:
                 if chunk and hasattr(chunk, 'content') and chunk.content:
                     final_content_list.append(chunk.content)
            final_raw_content = "".join(final_content_list)

            parsed_result: Optional[DependencyList] = None
            stream_result_obj = None
            try:
                 if hasattr(prediction_stream, 'result'):
                      stream_result_obj = prediction_stream.result()
                 if hasattr(stream_result_obj, 'parsed') and isinstance(stream_result_obj.parsed, DependencyList):
                      parsed_result = stream_result_obj.parsed
                 elif isinstance(stream_result_obj, DependencyList):
                      parsed_result = stream_result_obj
                 elif hasattr(stream_result_obj, 'parsed') and isinstance(stream_result_obj.parsed, dict):
                     try: parsed_result = DependencyList(**stream_result_obj.parsed)
                     except ValidationError as pydantic_err: print(f"{log_prefix} WARN: Dict->Pydantic validation failed: {pydantic_err}")
                     except Exception as conv_err: print(f"{log_prefix} WARN: Dict->Pydantic conversion failed: {conv_err}")
            except Exception as res_err: print(f"{log_prefix} WARN: Error accessing stream result: {res_err}")

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

        # Filtrage des erreurs
        final_deps = [dep for dep in dependencies if not dep.startswith("ERROR:")]
        errors = [dep for dep in dependencies if dep.startswith("ERROR:")]
        if errors and not final_deps: return errors
        elif errors and final_deps: print(f"{log_prefix} Warning: Found dependencies but also errors: {errors}")
        return final_deps

    # --- Assure que les autres méthodes LMStudio utilisent lms.Chat correctement ---
    def generate_or_correct_code(self, user_prompt: str, project_name: str, current_code: str, dependencies_to_use: List[str], execution_error: Optional[str] = None) -> str:
        """Génère ou corrige le code (non-streaming) en utilisant les dépendances spécifiées."""
        if not self.is_available(): return "# --- ERROR: LM Studio model not loaded. --- #"
        log_prefix = "[LMStudio Correct]" if execution_error else "[LMStudio GenInit]"
        task_desc = "CORRECT the Python code below" if execution_error else "GENERATE Python code"
        error_info = ""
        instruction = "Output ONLY the complete, runnable Python code using the specified dependencies. Wrap the code in a single ```python ... ``` block. Do NOT include any explanation or commentary outside the code block."
        if execution_error:
            error_info = f"The previous code failed with this error:\n```text\n{execution_error.strip()}\n```\nPlease fix the Python code based ONLY on this error and the original user request, using the specified dependencies."
            instruction = "Output ONLY the complete, corrected Python code in a single ```python ... ``` block, using the specified dependencies. Do NOT explain the changes outside the code itself."
        elif not current_code:
             instruction = "Output ONLY the complete Python code for the user request in a single ```python ... ``` block, using the specified dependencies. Do NOT add any explanation or commentary outside the code block."
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))
        deps_info = f"You MUST use the following external libraries (if needed by the request): {deps_list_str if deps_list_str else 'Only standard Python libraries'}."
        system_prompt = "\n".join([
            f"You are Pythautom, an AI assistant for project '{project_name}'.",
            f"Task: {task_desc}.", deps_info, error_info if error_info else "",
            f"\n{'Code to Correct/Generate' if current_code else 'User Request (for initial code)'}:",
            f"```python\n{current_code}\n```" if current_code else f"User Request: {user_prompt}",
            f"\n{instruction}",
        ]).strip()
        if execution_error: system_prompt += f"\n\nOriginal User Request Context (for guidance): {user_prompt}"

        print(f"{log_prefix} Requesting code (only) for: '{user_prompt[:50]}...' using deps: {deps_list_str}")
        try:
            chat = lms.Chat(system_prompt)
            response = self.model.respond(chat)
            full_response_content = response.content if response else ""
            print(f"{log_prefix} Full response received.")
            return full_response_content # Laisse le GUI gérer le nettoyage

        except Exception as e:
            error_msg = f"\n\n# --- LLM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs.\n# --- END LLM ERROR --- #"
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            return error_msg

    def generate_code_stream_with_deps(self, user_request: str, project_name: str, current_code: str, dependencies_to_use: List[str], fragment_callback: Callable[[str], None]) -> str:
        """Génère/affine le code via streaming, en utilisant les dépendances spécifiées."""
        if not self.is_available():
            # --- BLOC CORRIGÉ ---
            err_msg = "# --- ERROR: LM Studio model not loaded. --- #"
            try:
                fragment_callback(f"\nSTREAM ERROR: {err_msg}\n")
            except Exception as cb_err:
                 print(f"Error sending LLM unavailable msg via callback: {cb_err}")
            return err_msg
            # --- FIN BLOC CORRIGÉ ---

        log_prefix = "[LMStudio RefineStream]"
        is_initial = not bool(current_code.strip())
        task_desc = "GENERATE initial Python code" if is_initial else "REFINE the Python code below"
        code_context_header = "User Request (for initial code):" if is_initial else "Current Code to Refine:"
        code_context = user_request if is_initial else f"```python\n{current_code}\n```"
        refinement_header = "" if is_initial else "\nUser Refinement Request:"
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:"))
        deps_info = f"You MUST use the following external libraries (if needed by the request): {deps_list_str if deps_list_str else 'Only standard Python libraries'}."
        system_prompt = "\n".join([
            f"You are Pythautom, an AI assistant writing/refining Python code for project '{project_name}'.",
            f"Task: {task_desc} based on the user request.", deps_info,
            f"\n{code_context_header}\n{code_context}",
            f"{refinement_header}" if refinement_header else "",
            f"{user_request if not is_initial else ''}",
            "\nInstructions:", "1. Analyze the request and the current code (if provided).", f"2. {'Generate' if is_initial else 'Modify'} the Python code to fulfill the request, using ONLY the specified external dependencies if needed.", "3. Output ONLY the complete, runnable Python code required.", "4. Wrap the ENTIRE code output in a single ```python ... ``` markdown block.", "5. Do NOT include any explanations, comments, or introductory text outside the code block.",
        ]).strip()

        print(f"{log_prefix} Requesting code stream for: '{user_request[:50]}...' using deps: {deps_list_str}")
        full_response_content = ""
        try:
            chat = lms.Chat(system_prompt)
            prediction_stream = self.model.respond_stream(chat)
            fragment_count = 0
            print(f"{log_prefix} Starting to stream fragments...")
            for fragment in prediction_stream:
                 if fragment and hasattr(fragment, 'content') and isinstance(fragment.content, str):
                    content_piece = fragment.content; full_response_content += content_piece
                    try: fragment_callback(content_piece)
                    except Exception as cb_err: print(f"Error in fragment_callback: {cb_err}")
                    fragment_count += 1

            print(f"{log_prefix} Finished streaming ({fragment_count} fragments). Returning accumulated code response.")
            return full_response_content

        except Exception as e:
            error_msg = f"# --- LLM STREAM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs."
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            try:
                # Tente d'envoyer l'erreur via callback
                fragment_callback(f"\nSTREAM ERROR: {e}\n")
            except Exception as cb_err_exc:
                 # Log si le callback lui-même échoue
                 print(f"Error sending exception via callback: {cb_err_exc}")
            # Retourne l'erreur pour que le handler puisse la traiter
            return error_msg

    def get_backend_name(self) -> str:
        return "LM Studio"

# --- Implémentation Google Gemini ---
class GeminiClient(BaseLLMClient):
    def __init__(self):
        self.client: Optional[genai.GenerativeModel] = None
        self.api_key: Optional[str] = None
        self.model_name: Optional[str] = None
        print("GeminiClient initialized.")
        if not GOOGLE_GENAI_AVAILABLE:
            print("ERROR: Gemini backend requires 'google-generativeai'.")

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

    def connect(self, api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, **kwargs) -> bool:
        if not GOOGLE_GENAI_AVAILABLE: print("ERROR: Cannot connect, 'google-generativeai' not installed."); return False
        self.client = None; self.api_key = None; self.model_name = None
        print(f"Configuring Gemini with model: {model_name}")
        if not api_key: print("ERROR: Gemini API Key missing."); return False
        if not model_name: print("ERROR: Gemini model name missing."); return False
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            print("Verifying Gemini model responsiveness...")
            response = model.generate_content("Hi",
                                              generation_config=genai.types.GenerationConfig(max_output_tokens=5),
                                              safety_settings=safety_settings)
            response_text = self._extract_text_from_gemini_response(response)
            if not response_text:
                 block_reason = self._get_gemini_block_reason(response)
                 raise ConnectionError(f"Gemini test failed (model: {model_name}).{block_reason}")
            self.client = model
            self.api_key = api_key
            self.model_name = model_name
            print(f"Successfully configured Gemini with model '{model_name}'.")
            return True
        except Exception as e:
            print(f"ERROR configuring/connecting Gemini: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            self.client = None; self.api_key = None; self.model_name = None
            return False

    def is_available(self) -> bool:
        return self.client is not None

    # --- UTILISE LE PROMPT AMÉLIORÉ POUR GEMINI, MAIS DEMANDE UNE LISTE STRING ---
    def identify_dependencies_from_request(self, user_prompt: str, project_name: str) -> List[str]:
        """Analyse le texte de la requête utilisateur pour les dépendances (non-streaming, sortie liste string)."""
        if not self.client: return ["ERROR: Gemini client not loaded"]
        log_prefix = "[Gemini ID_Deps_Req]"

        # --- PROMPT AMÉLIORÉ (adapté pour sortie liste string) ---
        system_prompt = (
            f"You are an expert Python dependency analyzer for project '{project_name}'.\n"
            f"**ROLE:** Analyze the user's request to understand the **type** of application being built (e.g., GUI game, web scraper, command-line tool, data analysis script, etc.).\n"
            f"**TASK:** Based on the inferred application type and the user's request, list ONLY the essential external, non-standard Python libraries needed for a typical implementation.\n"
            f"**INFERENCE:** You MUST infer common libraries even if not explicitly mentioned. For example:\n"
            f"  - If the request describes a graphical game (like snake, pong, space invaders), you MUST include 'pygame' unless another GUI library is specified.\n"
            f"  - If the request involves fetching data from a web URL, you MUST include 'requests'.\n"
            f"  - If the request involves parsing HTML, you likely need 'beautifulsoup4'.\n"
            f"  - If it involves data manipulation or numerical tasks, consider 'pandas' or 'numpy'.\n"
            f"**CONSTRAINTS:**\n"
            f"1. List ONLY the package names as strings.\n"
            f"2. EXCLUDE Python standard libraries (like `os`, `sys`, `json`, `re`, `math`, `random`, `time`, `tkinter`, `collections`, `datetime`).\n"
            f"3. If the request describes a simple script requiring ONLY standard libraries, provide an empty list `[]`.\n"
            f"4. Your entire output MUST be ONLY a valid Python list string representation (e.g., `['pygame', 'requests']` or `[]`). No explanations or other text."
        )
        # --- FIN PROMPT AMÉLIORÉ ---

        full_prompt = f"{system_prompt}\n\nUser Request: {user_prompt}"
        dependencies = []
        print(f"{log_prefix} Requesting dependencies based on request: '{user_prompt[:60]}...'")

        try:
            response = self.client.generate_content(full_prompt, safety_settings=safety_settings)
            raw_response_text = self._extract_text_from_gemini_response(response).strip()
            block_reason = self._get_gemini_block_reason(response)
            print(f"{log_prefix} Raw response: '{raw_response_text}' {block_reason}")

            # Logique d'analyse (attend une liste string)
            if not raw_response_text and not block_reason: dependencies = ["ERROR: No dependency list received from LLM."]
            elif block_reason: dependencies = [f"ERROR: LLM response blocked.{block_reason}"]
            else:
                try:
                    parsed_list = ast.literal_eval(raw_response_text)
                    if isinstance(parsed_list, list) and all(isinstance(item, str) for item in parsed_list):
                        dependencies = [dep.strip() for dep in parsed_list if dep.strip()]
                    else: raise ValueError("Not a list of strings")
                except (ValueError, SyntaxError, TypeError) as parse_err:
                    match = re.search(r"(\[.*?\])", raw_response_text, re.DOTALL)
                    if match:
                        try:
                            parsed_list_fb = ast.literal_eval(match.group(1))
                            if isinstance(parsed_list_fb, list) and all(isinstance(item, str) for item in parsed_list_fb):
                                dependencies = [dep.strip() for dep in parsed_list_fb if dep.strip()]
                            else: raise ValueError("Fallback regex content not a list of strings")
                        except Exception as e_fb: dependencies = [f"ERROR: Could not parse deps (fallback failed: {e_fb}): {raw_response_text}"]
                    else: dependencies = [f"ERROR: Could not parse deps (initial parse failed: {parse_err}): {raw_response_text}"]

        except Exception as e:
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}"); dependencies = [f"ERROR: {type(e).__name__}: {e}"]

        # Filtrage des erreurs
        final_deps = [dep for dep in dependencies if not dep.startswith("ERROR:")]; errors = [dep for dep in dependencies if dep.startswith("ERROR:")]
        if errors and not final_deps: return errors
        elif errors and final_deps: print(f"{log_prefix} Warning: Found dependencies but also errors: {errors}")
        return final_deps

    # --- Autres méthodes Gemini restent les mêmes ---
    def generate_or_correct_code(self, user_prompt: str, project_name: str, current_code: str, dependencies_to_use: List[str], execution_error: Optional[str] = None) -> str:
        if not self.client: return "# --- ERROR: Gemini client not loaded. --- #"
        log_prefix = "[Gemini Correct]" if execution_error else "[Gemini GenInit]"; task_desc = "CORRECT the Python code below" if execution_error else "GENERATE Python code"; error_info = ""; instruction = "Output ONLY the complete, runnable Python code using the specified dependencies. Wrap the code in a single ```python ... ``` block. NO explanation or commentary outside the code block."
        if execution_error: error_info = f"The previous code failed:\n```text\n{execution_error.strip()}\n```\nFix the Python code based ONLY on this error and the original user request, using the specified dependencies."; instruction = "Output ONLY the complete, corrected Python code in a single ```python ... ``` block, using the specified dependencies. NO explanation outside the code."
        elif not current_code: instruction = "Output ONLY the complete Python code for the user request in a single ```python ... ``` block, using the specified dependencies. NO explanation outside the code block."
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:")); deps_info = f"You MUST use the following external libraries (if needed by the request): {deps_list_str if deps_list_str else 'Only standard Python libraries'}."
        prompt_lines = [f"You are Pythautom AI for project '{project_name}'.", f"Task: {task_desc}.", deps_info, error_info if error_info else "", f"\n{'Code to Correct/Generate' if current_code else 'User Request (for initial code)'}:", f"```python\n{current_code}\n```" if current_code else f"User Request: {user_prompt}", f"\n{instruction}",]
        if execution_error: prompt_lines.append(f"\n\nOriginal User Request Context (for guidance): {user_prompt}"); full_prompt = "\n".join(prompt_lines)
        print(f"{log_prefix} Requesting code (only) for: '{user_prompt[:50]}...' using deps: {deps_list_str}")
        try:
            response = self.client.generate_content(full_prompt, safety_settings=safety_settings); full_response_content = self._extract_text_from_gemini_response(response); block_reason = self._get_gemini_block_reason(response)
            if block_reason: full_response_content += f"\n# --- GEMINI ERROR: {block_reason} --- #"
            print(f"{log_prefix} Full response received."); return full_response_content
        except Exception as e: error_msg = f"\n\n# --- LLM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs.\n# --- END LLM ERROR --- #"; print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}"); return error_msg


    def generate_code_stream_with_deps(self, user_request: str, project_name: str, current_code: str, dependencies_to_use: List[str], fragment_callback: Callable[[str], None]) -> str:
        """Génère/affine le code via streaming, en utilisant les dépendances spécifiées."""
        if not self.client:
            # --- BLOC CORRIGÉ ---
            err_msg = "# --- ERROR: Gemini client not loaded. --- #"
            try:
                fragment_callback(f"\nSTREAM ERROR: {err_msg}\n")
            except Exception as cb_err:
                 print(f"Error sending Gemini unavailable msg via callback: {cb_err}")
            return err_msg
            # --- FIN BLOC CORRIGÉ ---

        log_prefix = "[Gemini RefineStream]"
        is_initial = not bool(current_code.strip()); task_desc = "GENERATE initial Python code" if is_initial else "REFINE the Python code below"; code_context_header = "User Request (for initial code):" if is_initial else "Current Code to Refine:"; code_context = user_request if is_initial else f"```python\n{current_code}\n```"; refinement_header = "" if is_initial else "\nUser Refinement Request:"
        deps_list_str = ', '.join(d for d in dependencies_to_use if not d.startswith("ERROR:")); deps_info = f"You MUST use the following external libraries (if needed by the request): {deps_list_str if deps_list_str else 'Only standard Python libraries'}."
        prompt_lines = [f"You are Pythautom AI writing/refining Python code for project '{project_name}'.", f"Task: {task_desc} based on the user request.", deps_info, f"\n{code_context_header}\n{code_context}", f"{refinement_header}" if refinement_header else "", f"{user_request if not is_initial else ''}", "\nInstructions:", "1. Analyze the request and current code (if provided).", f"2. {'Generate' if is_initial else 'Modify'} the Python code, using ONLY the specified external dependencies if needed.", "3. Output ONLY the complete, runnable Python code required.", "4. Wrap the ENTIRE code output in a single ```python ... ``` markdown block.", "5. Do NOT include any explanations, comments, or introductory text outside the code block.",]
        full_prompt = "\n".join(prompt_lines)

        # Définir des safety_settings moins stricts
        # S'assurer que les classes HarmCategory/HarmBlockThreshold sont définies (voir imports en haut)
        less_strict_safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        print(f"{log_prefix} Requesting code stream for: '{user_request[:50]}...' using deps: {deps_list_str} with relaxed safety settings.")
        full_response_content = ""

        # --- Bloc try/except principal ---
        try:
            # Passe les safety_settings modifiés à l'appel
            prediction_stream = self.client.generate_content(
                full_prompt,
                stream=True,
                safety_settings=less_strict_safety_settings # Utilise les paramètres moins stricts
            )

            fragment_count = 0
            print(f"{log_prefix} Starting to stream fragments...")
            for chunk in prediction_stream:
                 # Vérifie le blocage DANS la boucle
                 block_reason = self._get_gemini_block_reason(chunk)
                 if block_reason:
                     error_msg_block = f"# --- GEMINI STREAM ERROR: Blocked{block_reason} --- #"
                     print(f"{log_prefix} Stream blocked: {block_reason}")
                     full_response_content += error_msg_block # Ajoute l'erreur au contenu accumulé
                     # Essaie d'envoyer l'erreur via callback aussi
                     try:
                         fragment_callback(f"\nSTREAM ERROR: Blocked - {block_reason}\n")
                     except Exception as cb_err_block:
                         print(f"Error sending block reason via callback: {cb_err_block}")
                     break # Arrête de traiter le stream après un blocage

                 # Extrait le texte si non bloqué
                 chunk_text = self._extract_text_from_gemini_response(chunk)
                 if chunk_text:
                    full_response_content += chunk_text # Accumule la réponse complète
                    try:
                        fragment_callback(chunk_text) # Envoie le fragment au GUI
                    except Exception as cb_err:
                        # Log l'erreur de callback mais continue
                        print(f"Error in fragment_callback: {cb_err}")
                    fragment_count += 1

            print(f"{log_prefix} Finished streaming ({fragment_count} fragments). Returning accumulated code response.")
            # Retourne la chaîne de réponse complète accumulée APRÈS la fin du stream
            return full_response_content

        # Capture les exceptions générales pendant l'appel API ou le streaming
        except Exception as e:
            error_msg_exc = f"# --- LLM STREAM ERROR ({log_prefix}) --- #\n# {type(e).__name__}: {e}\n# Check console logs."
            print(f"{log_prefix} EXCEPTION: {traceback.format_exc()}")
            # Tente d'envoyer l'erreur via callback
            try:
                 fragment_callback(f"\nSTREAM ERROR: {e}\n")
            except Exception as cb_err_exc:
                 print(f"Error sending exception via callback: {cb_err_exc}")
            # Retourne l'erreur pour que le handler puisse la traiter
            return error_msg_exc
        # --- Fin Bloc try/except ---


    def get_backend_name(self) -> str:
        return "Google Gemini"