#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
# Vous pouvez le réactiver si vous le souhaitez, une fois le debug terminé
# set -e

# --- Configuration ---
APP_DIR=$(dirname "$(realpath "$0")")
VENV_NAME=".venv"
VENV_DIR="$APP_DIR/$VENV_NAME"
REQUIRED_PYTHON_VERSION="python3.11" # Version de Python requise
PYTHON_EXE="$VENV_DIR/bin/python"
REQUIREMENTS="PyQt6 lmstudio pydantic google-genai google-generativeai"
LINUX_PKG="libxcb-cursor-dev"

echo "--- Démarrage du script d'installation ---"
echo "Répertoire de l'application : $APP_DIR"
echo "Répertoire de l'environnement virtuel cible : $VENV_DIR"

# --- Vérification et Installation du Paquet Système (Debian/Ubuntu/Pop!_OS) ---
echo "Vérification de la présence du paquet système requis : $LINUX_PKG..."
if command -v apt &> /dev/null; then
    if ! dpkg -s $LINUX_PKG &> /dev/null; then
        echo "Le paquet '$LINUX_PKG' n'est pas installé."
        echo "Tentative d'installation via apt (sudo requis)..."
        sudo apt update && sudo apt install -y $LINUX_PKG || {
            echo "Erreur : Échec de l'installation de '$LINUX_PKG'." >&2
            echo "Veuillez essayer de l'installer manuellement : sudo apt update && sudo apt install $LINUX_PKG" >&2
            read -p "Appuyez sur Entrée pour quitter..."
            exit 1
        }
        echo "Paquet '$LINUX_PKG' installé avec succès."
    else
        echo "Le paquet '$LINUX_PKG' est déjà installé."
    fi
else
    echo "Attention : La commande 'apt' n'a pas été trouvée. Impossible de vérifier/installer '$LINUX_PKG' automatiquement."
    echo "Assurez-vous que '$LINUX_PKG' (ou son équivalent pour votre distribution) est installé."
    read -p "Appuyez sur Entrée pour continuer malgré tout..."
fi


# --- Vérification de Python (Version Spécifique) ---
echo "Vérification de la présence de $REQUIRED_PYTHON_VERSION..."
if ! command -v $REQUIRED_PYTHON_VERSION &> /dev/null; then
    echo "Erreur : La commande '$REQUIRED_PYTHON_VERSION' n'est pas trouvée dans le PATH." >&2
    echo "Veuillez installer Python 3.11+ (par exemple, avec 'sudo apt install python3.11 python3.11-venv')." >&2
    read -p "Appuyez sur Entrée pour quitter..."
    exit 1
fi
PYTHON_VERSION=$($REQUIRED_PYTHON_VERSION --version)
echo "Version Python requise trouvée : $PYTHON_VERSION"

# --- Vérification/Installation de UV ---
echo "Vérification et installation/mise à jour de 'uv'..."
python3 -m pip install --user --upgrade uv
LOCAL_BIN_PATH="$HOME/.local/bin"
if [[ ":$PATH:" != *":$LOCAL_BIN_PATH:"* ]]; then
    export PATH="$LOCAL_BIN_PATH:$PATH"
    echo "Ajout de $LOCAL_BIN_PATH au PATH pour cette session."
fi
if ! command -v uv &> /dev/null; then
     echo "Erreur : La commande 'uv' n'est toujours pas trouvée après la tentative d'installation." >&2
     echo "Vérifiez que '$LOCAL_BIN_PATH' est dans votre PATH système." >&2
     read -p "Appuyez sur Entrée pour quitter..."
     exit 1
 fi
UV_VERSION=$(uv --version)
echo "'uv' est disponible : $UV_VERSION"

# --- Gestion de l'Environnement Virtuel ---
echo "Vérification de l'état de l'environnement virtuel ($VENV_DIR)..."

VENV_NEEDS_CREATION=false # Flag pour savoir si on doit créer le venv

# Vérifie si le fichier de configuration du venv existe
if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    echo "Un environnement virtuel existe déjà dans '$VENV_DIR'."
    # Essayer de déterminer la version de Python DANS le venv existant
    EXISTING_PYTHON_EXE="$VENV_DIR/bin/python"
    if [ -x "$EXISTING_PYTHON_EXE" ]; then
        EXISTING_PYTHON_VERSION=$($EXISTING_PYTHON_EXE --version 2>&1 | cut -d' ' -f2) # Capturer stderr aussi
    else
        EXISTING_PYTHON_VERSION="inconnue (exécutable non trouvé)"
    fi

    # Extraire la version cible (ex: 3.11) de REQUIRED_PYTHON_VERSION (ex: python3.11)
    TARGET_VERSION=$(echo $REQUIRED_PYTHON_VERSION | grep -oP '\d+\.\d+')

    # Vérifier si la version existante commence par la version cible
    if [[ "$EXISTING_PYTHON_VERSION" == "$TARGET_VERSION"* ]]; then
        echo "L'environnement virtuel existant utilise Python $EXISTING_PYTHON_VERSION (version compatible)."
        VENV_NEEDS_CREATION=false # Pas besoin de recréer
    else
        echo "----------------------------------------------------------------------" >&2
        echo "ATTENTION : L'environnement virtuel trouvé utilise Python $EXISTING_PYTHON_VERSION." >&2
        echo "           Ce script nécessite Python $TARGET_VERSION ou une version ultérieure." >&2
        echo "           Utiliser cet environnement existant causera probablement des erreurs." >&2
        echo "----------------------------------------------------------------------" >&2
        # Demander confirmation avant de supprimer
        read -p "Voulez-vous supprimer cet environnement incompatible et en créer un nouveau ? (o/N) : " CONFIRM_DELETE
        CONFIRM_DELETE_LOWER=$(echo "$CONFIRM_DELETE" | tr '[:upper:]' '[:lower:]')

        if [[ "$CONFIRM_DELETE_LOWER" == "o" || "$CONFIRM_DELETE_LOWER" == "oui" ]]; then
            echo "Suppression de l'environnement virtuel existant : $VENV_DIR ..."
            rm -rf "$VENV_DIR"
            if [ $? -ne 0 ]; then
                echo "Erreur : Échec de la suppression de '$VENV_DIR'." >&2
                read -p "Appuyez sur Entrée pour quitter..."
                exit 1
            fi
            echo "Ancien environnement supprimé."
            VENV_NEEDS_CREATION=true # Marquer pour création
        else
            echo "L'environnement virtuel n'a pas été modifié." >&2
            echo "Le script ne peut pas continuer avec un environnement incompatible." >&2
            read -p "Appuyez sur Entrée pour quitter..."
            exit 1
        fi
    fi
else
    # Le fichier pyvenv.cfg n'existe pas, donc le venv n'existe pas ou est incomplet
    echo "Aucun environnement virtuel valide trouvé."
    VENV_NEEDS_CREATION=true # Marquer pour création
fi

# Créer le venv si nécessaire
if [ "$VENV_NEEDS_CREATION" = true ]; then
    echo "Création d'un nouvel environnement virtuel avec $REQUIRED_PYTHON_VERSION..."
    uv venv "$VENV_DIR" --seed -p $REQUIRED_PYTHON_VERSION
    if [ $? -ne 0 ]; then
        echo "Erreur : Échec de la création de l'environnement virtuel avec $REQUIRED_PYTHON_VERSION." >&2
        echo "Vérifiez que '$REQUIRED_PYTHON_VERSION' et les paquets venv associés (ex: python3.11-venv) sont bien installés." >&2
        read -p "Appuyez sur Entrée pour quitter..."
        exit 1
    fi
    echo "Environnement virtuel créé avec succès ($($PYTHON_EXE --version))."
fi

# --- Installation/Mise à jour des Requirements ---
echo "Installation/Mise à jour des requirements Python : $REQUIREMENTS..."
# Utilise le Python DANS le venv pour installer les paquets
uv pip install $REQUIREMENTS -p "$PYTHON_EXE"
if [ $? -ne 0 ]; then
    echo "Erreur : Échec de l'installation des requirements Python." >&2
    echo "Vérifiez votre connexion internet ou la sortie de la commande 'uv pip install' ci-dessus." >&2
    read -p "Appuyez sur Entrée pour quitter..."
    exit 1
fi
echo "Requirements installés avec succès dans l'environnement virtuel."

# --- Lancement de l'Application ---
echo "Lancement de l'application (main.py)..."
"$PYTHON_EXE" "$APP_DIR/main.py"
if [ $? -ne 0 ]; then
    echo "Erreur : Échec du lancement de main.py. Vérifiez le script Python pour des erreurs." >&2
    read -p "Appuyez sur Entrée pour continuer..." # Pause pour voir l'erreur
    exit 1
fi

echo "Application fermée ou script terminé."
read -p "Appuyez sur Entrée pour quitter..."
exit 0
