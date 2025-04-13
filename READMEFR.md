# PythAutom : Constructeur de Projets Python en Un Clic avec IA

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)

PythAutom est une application de bureau utilisant PyQt6, UV et LM Studio pour aider les utilisateurs à créer des projets Python en interagissant avec un modèle d'IA exécuté localement ou à travers votre réseau. Construisez plus vite, plus intelligemment. 🚀

### ✨ Nouvelles Fonctionnalités Ajoutées ! ✨

*   **Exportation de Projets :** 🗂️ Vous pouvez désormais exporter vos projets Python générés sous forme de dossiers ou de packages prêts à l'emploi.
*   **Intégration d'IA Externe :** 🤖 Utilisez des modèles d'IA au-delà de LM Studio local — PythAutom peut désormais se connecter à distance avec l'IA Gemini.
*   **Support des Modèles de Raisonnement (LM Studio) :** 🧠 PythAutom est désormais compatible avec les modèles avancés de type "reasoning".
*   **Compatibilité Linux :** 🐧 PythAutom fonctionne désormais parfaitement sous Linux !

## Prérequis

Avant de commencer, assurez-vous d'avoir installé et configuré les éléments suivants :

1.  **Python :** Version **3.11 ou supérieure**, ajoutée à la variable d’environnement `PATH`.
2.  **LM Studio :**
    *   Téléchargez LM Studio depuis : [https://lmstudio.ai/](https://lmstudio.ai/)
    *   Lancez l’application, allez dans la section des modèles (icône loupe).
    *   Téléchargez un modèle "instruction-tuned" compatible (ex : `Qwen/Qwen1.5-7B-Chat-GGUF`).
    *   Dans l’onglet **Serveur Local** (`<->`), sélectionnez votre modèle, cliquez sur **"Démarrer le Serveur"**.
    *   **(Optionnel)** Pour la connexion réseau, configurez LM Studio pour accepter des connexions extérieures (liaison à `0.0.0.0`).

## Comment Lancer

### 🪟 Windows :

1. Double-cliquez sur le fichier `run_windows.bat` à la racine du projet.

### 🐧 Linux :

1. Dans un terminal :
    ```bash
    chmod +x run_linux.sh
    ./run_linux.sh
    ```

Ces scripts :

* Vérifient si **UV** est installé (et le téléchargent si nécessaire),
* Créent un environnement virtuel Python `.venv`,
* Installent `PyQt6` et `lmstudio-client` dans cet environnement,
* Lancement automatique de `main.py` avec l'interpréteur de `.venv`.

## Fonctionnalités

*   **Interface Graphique (GUI) :** Interface intuitive avec PyQt6 pour gérer les projets et discuter avec l’IA.
*   **Génération de Code avec IA :** Le code Python est généré à partir de vos prompts grâce à un modèle IA local ou distant.
*   **Gestion Automatique des Dépendances :** UV installe les bibliothèques nécessaires selon le contexte du projet.
*   **Exécution Isolée :** Chaque projet tourne dans son environnement virtuel propre, géré par UV.
*   **Débogage Basique et Boucle Itérative :** Capacité à détecter les erreurs et itérer automatiquement avec l’IA pour les corriger.

## Améliorations Prévues / Feuille de Route

*   [x] Interaction conversationnelle améliorée avec l'IA.
*   [x] Fonctionnalité pour exporter les projets générés.
*   [x] Mécanismes d’autocorrection pour le code généré basé sur les erreurs.
*   [ ] Intégration de capacités de vision IA (ex. : diagrammes, maquettes).
*   [ ] Possibilité d'importer des fichiers (images, sons, vidéos) pour des interactions multimodales.

---
