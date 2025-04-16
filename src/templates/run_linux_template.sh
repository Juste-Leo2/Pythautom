#!/bin/bash
# set -e # Commenté pour ne pas quitter immédiatement en cas d'erreur mineure

# --- Configuration ---
APP_DIR=$(dirname "$(realpath "$0")")
VENV_NAME=".venv_dist"
VENV_DIR="$APP_DIR/$VENV_NAME"
PYTHON_EXE="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$APP_DIR/requirements.txt"
MAIN_SCRIPT="$APP_DIR/main.py"
# Tente de trouver python3.11 ou python3 (fallback)
PYTHON_CMD="python3.11"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python3"
    echo "Attention: '$REQUIRED_PYTHON_VERSION' non trouvé, utilisation de 'python3' (peut ne pas fonctionner si la version est trop ancienne)."
fi

echo "--- Pythautom Project Runner (Linux/macOS) ---"
echo "Project Directory: $APP_DIR"

# Fonction pour gérer les erreurs et pauser
error_exit() {
    echo "--------------------------------------------------" >&2
    echo "Erreur : $1" >&2
    echo "--------------------------------------------------" >&2
    read -p "Appuyez sur Entrée pour quitter..."
    exit 1
}

# --- Vérification de Python ---
echo "Vérification de Python ($PYTHON_CMD)..."
if ! command -v $PYTHON_CMD &> /dev/null; then
    error_exit "La commande '$PYTHON_CMD' n'est pas trouvée. Veuillez installer Python 3.11+."
fi
PYTHON_VER=$($PYTHON_CMD --version)
echo "Python trouvé : $PYTHON_VER"

# --- Vérification/Installation de UV ---
echo "Vérification et installation/mise à jour de 'uv'..."
$PYTHON_CMD -m pip install --user --upgrade uv || error_exit "Échec de l'installation/mise à jour de 'uv' via pip."

# Ajout potentiel de ~/.local/bin au PATH pour cette session
LOCAL_BIN_PATH="$HOME/.local/bin"
if [[ ":$PATH:" != *":$LOCAL_BIN_PATH:"* ]]; then
    export PATH="$LOCAL_BIN_PATH:$PATH"
    echo "Ajout de $LOCAL_BIN_PATH au PATH pour cette session."
fi

if ! command -v uv &> /dev/null; then
    error_exit "La commande 'uv' n'est toujours pas trouvée après la tentative d'installation. Vérifiez que '$LOCAL_BIN_PATH' est dans votre PATH système."
fi
UV_VERSION=$(uv --version)
echo "'uv' est available : $UV_VERSION"

# --- Gestion de l'Environnement Virtuel ---
echo "Vérification de l'environnement virtuel ($VENV_DIR)..."
if [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
    echo "Création d'un nouvel environnement virtuel..."
    # Utilise le python trouvé pour créer le venv
    uv venv "$VENV_DIR" --seed -p $PYTHON_CMD || error_exit "Échec de la création de l'environnement virtuel avec $PYTHON_CMD."
    echo "Environnement virtuel créé avec succès."
else
    echo "Environnement virtuel existant trouvé."
    # Optionnel: Ajouter une vérification de la version python du venv existant ici
fi

# --- Vérification de requirements.txt ---
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    error_exit "Le fichier '$REQUIREMENTS_FILE' n'a pas été trouvé. Impossible d'installer les dépendances."
fi

# --- Installation/Mise à jour des Requirements ---
echo "Installation des requirements depuis $REQUIREMENTS_FILE..."
# Utilise le Python DANS le venv pour installer
uv pip install -r "$REQUIREMENTS_FILE" -p "$PYTHON_EXE" || error_exit "Échec de l'installation des requirements. Vérifiez le fichier et la connexion internet."
echo "Requirements installés avec succès."

 # --- Vérification du script principal ---
if [ ! -f "$MAIN_SCRIPT" ]; then
    error_exit "Le script principal '$MAIN_SCRIPT' n'a pas été trouvé."
fi

# --- Lancement de l'Application ---
echo "Lancement de l'application..."
"$PYTHON_EXE" "$MAIN_SCRIPT"
EXIT_CODE=$? # Capture le code de sortie

if [ $EXIT_CODE -ne 0 ]; then
    echo "--------------------------------------------------" >&2
    echo "Erreur : Le script Python s'est terminé avec le code $EXIT_CODE." >&2
    echo "         Vérifiez les messages d'erreur ci-dessus." >&2
    echo "--------------------------------------------------" >&2
    read -p "Appuyez sur Entrée pour continuer..." # Pause pour voir l'erreur
    exit $EXIT_CODE
fi

echo "Application fermée ou script terminé avec succès."
read -p "Appuyez sur Entrée pour quitter..."
exit 0