# src/llm_interaction.py
# VERSION AVEC CORRECTION PROMPT POUR ```python

import lmstudio as lms
from . import utils
from . import project_manager
import os
import traceback
from pydantic import BaseModel, Field # Pour la réponse structurée
from typing import List, Callable, Optional

# --- Configuration ---
# Essayez un modèle réputé bon en instruction following / JSON mode
# DEFAULT_MODEL = "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF"
# DEFAULT_MODEL = "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO-GGUF"
#DEFAULT_MODEL = "Qwen/Qwen1.5-7B-Chat-GGUF" # Qwen est souvent bon avec lmstudio
#DEFAULT_MODEL = "openhands-lm-7b-v0.1" # Ancien modèle testé
DEFAULT_MODEL = None

# --- Pydantic Schema for Dependencies ---
class DependencyList(BaseModel):
    """Defines the expected structure for the dependency list from the LLM."""
    dependencies: List[str] = Field(default_factory=list, description="List of NON-STANDARD Python libraries required (e.g., ['pygame', 'requests']). Empty list if none are needed.")

# --- LLM Client Wrapper ---
class LLMClient:
    def __init__(self, model_identifier=DEFAULT_MODEL):
        self.model_identifier = model_identifier
        self.model: Optional[lms.LLM] = None # Type hint pour clarté
        self._connect()
        print(f"LLMClient initialized trying model: {self.model_identifier}")

    def _connect(self):
        """Attempts to connect to the specified LLM via LM Studio."""
        try:
            print(f"Attempting to get model reference: {self.model_identifier}")
            self.model = lms.llm(self.model_identifier)
            if not self.model: raise ConnectionError(f"lms.llm('{self.model_identifier}') returned None.")
            loaded_name = getattr(self.model, 'model_identifier', self.model_identifier); print(f"Successfully got model reference: {loaded_name}")
        except Exception as e:
            print(f"ERROR connecting to or getting reference for model '{self.model_identifier}': {e}"); print(traceback.format_exc()); self.model = None

    def is_available(self):
        """Checks if the LLM client has a valid model reference."""
        return self.model is not None

    def check_connection(self):
        """Checks basic model responsiveness by sending a short prompt."""
        if not self.model: print("LLM check failed: Model reference is None."); return False
        model_id = getattr(self.model, 'model_identifier', self.model_identifier)
        try:
            print(f"Checking LLM connection by sending 'Hi' to {model_id}...")
            response = self.model.respond("Hi", config={"max_tokens": 5})
            print(f"LLM connection check successful. Response snippet: {response.content[:50]}..."); return True
        except Exception as e:
            print(f"LLM connection check failed for {model_id}: {e}"); return False

    # --- Phase 1: Identify Dependencies ---
    def identify_dependencies(self, user_prompt: str, project_name: str) -> List[str]:
        """Asks the LLM for non-standard dependencies using structured response."""
        if not self.model: return ["ERROR: LLM not available"]
        system_prompt = f"""Analyze user request for project '{project_name}'. List ONLY external, non-standard Python libraries needed (e.g., pygame, requests, numpy). Ignore standard libs (os, sys, math, json, re, tkinter). If none needed, provide an empty list. Respond ONLY in JSON format matching the schema."""
        full_prompt = f"{system_prompt}\n\nUser request: '{user_prompt}'\n\nRequired dependencies (JSON):"
        print(f"[LLM ID_Deps] Requesting deps for: '{user_prompt[:50]}...'"); deps = []
        try:
            prediction_stream = self.model.respond_stream(full_prompt, response_format=DependencyList)
            print("[LLM ID_Deps] Streaming response (for parsing)...")
            final_content = "".join([f.content for f in prediction_stream if f.content])
            result = prediction_stream.result(); print(f"[LLM ID_Deps] Parsing result...")
            if result and hasattr(result, 'parsed') and isinstance(result.parsed, dict) and 'dependencies' in result.parsed:
                 raw_deps = result.parsed['dependencies']
                 if isinstance(raw_deps, list) and all(isinstance(d, str) for d in raw_deps): deps = raw_deps; print(f"[LLM ID_Deps] Deps found: {deps}")
                 else: print(f"[LLM ID_Deps] WARN: Parsed 'dependencies' not list[str]: {raw_deps}. Assuming none.")
            else: print(f"[LLM ID_Deps] WARN: Could not parse deps. Raw: {final_content[:200]}...");
        except Exception as e: print(f"EXCEPTION during ID_Deps:\n{traceback.format_exc()}"); return [f"ERROR: {e}"]
        return deps

    # --- Phase 2: Generate or Correct Code (Streaming) ---
    def generate_code_streaming(self,
                                user_prompt: str,
                                project_name: str,
                                current_code: str, # Sera le code à corriger ou ""
                                dependencies_identified: List[str],
                                fragment_callback: Callable[[str], None],
                                execution_error: Optional[str] = None): # <-- Paramètre pour l'erreur
        """
        Generates or corrects Python code based on the prompt and optional error context, streaming the output.
        """
        if not self.model:
            fragment_callback("ERROR: LLM not available for code generation.")
            return

        # Définir les parties variables du prompt
        if execution_error:
            task_description = "CORRECT the Python code provided below"
            # L'erreur elle-même est présentée comme du texte préformaté, pas nécessairement du code python
            error_context = f"The previous execution failed with this error:\n```\n{execution_error.strip()}\n```\nPlease fix the code based on this error and the original user request."
            code_context_label = "Code to Correct:" # Label texte simple
            log_prefix = "[LLM Correct]"
        else: # Mode génération initiale
            task_description = "GENERATE Python code"
            error_context = "Generate the complete Python code based on the user request." # Instruction simple
            code_context_label = "Current Code (modify or replace if needed):" # Label texte simple
            log_prefix = "[LLM Generate]"

        deps_info = f"Dependencies available: {', '.join(dependencies_identified) if dependencies_identified and not any(d.startswith('ERROR:') for d in dependencies_identified) else 'Standard Python only.'}"

        # --- Construction du prompt ---
        prompt_lines = [
            f"You are an AI Python developer for project '{project_name}'.",
            f"Your task: {task_description}.",
            deps_info,
        ]

        # Ajouter le contexte d'erreur s'il existe
        if execution_error:
            prompt_lines.append(error_context)

        # Ajouter le label et le bloc de code existant/à corriger
        prompt_lines.extend([
            f"\n{code_context_label}",
            "```python", # Marqueur de début pour le bloc de code fourni en contexte
            current_code if current_code else '# Start writing Python code here.',
            "```" # Marqueur de fin pour le bloc de code fourni en contexte
        ])

        # Ajouter la requête utilisateur originale
        prompt_lines.append(f"\nOriginal User request: '{user_prompt}'")

        # Instruction finale pour le format de sortie de l'IA
        prompt_lines.append("\nAssistant Response (Output ONLY the complete, runnable Python code in a single ```python ... ``` block. Do not add any explanation before or after the code block.):")

        full_prompt = "\n".join(prompt_lines)
        # --- Fin Construction du prompt ---

        print(f"{log_prefix} Requesting code for: '{user_prompt[:50]}...'");
        if execution_error: print(f"{log_prefix} Providing error context: {execution_error[:100]}...")

        try:
            # Appel à l'IA en streaming
            prediction_stream = self.model.respond_stream(full_prompt)
            print(f"{log_prefix} Streaming code fragments...")
            fragment_count = 0
            for fragment in prediction_stream:
                if fragment and fragment.content:
                    fragment_callback(fragment.content)
                    fragment_count += 1
            print(f"{log_prefix} Streaming finished. Received {fragment_count} fragments.")
            # result = prediction_stream.result() # Optionnel pour stats
            # print(f"{log_prefix} Final result stats: {result.stats}")
        except Exception as e:
            error_msg = f"\n!!!!!!!! {log_prefix} EXCEPTION !!!!!!!!!!\n{traceback.format_exc()}\n"
            print(error_msg)
            try: fragment_callback(f"\n\n# --- ERROR DURING LLM CALL --- #\n# {e}\n# --- END ERROR ---")
            except Exception as cb_err: print(f"Error sending LLM error via callback: {cb_err}")