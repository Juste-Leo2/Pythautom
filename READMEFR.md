# PythAutom : Constructeur de Projets Python en Un Clic avec IA

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)

PythAutom est une application de bureau utilisant PyQt6, UV et LM Studio pour aider les utilisateurs à créer des projets Python en interagissant avec un modèle d'IA exécuté localement ou à travers votre réseau. Construisez plus vite, plus intelligemment. 🚀

### ✨ Nouveautés de la Version 3.0 ✨

*   **Importation de Fichiers :** 📁 Il est maintenant possible d'importer des fichiers dans vos projets via l'interface.
*   **Export Avancé :** 🧳 Possibilité d’exporter le projet depuis sa source, ce qui est utile pour les structures complexes.
*   **Interruption de Génération IA :** ✋ Vous pouvez désormais interrompre une génération de code IA en cours.
*   **Bouton Dev Tools :** 🛠️ Accédez aux logs en temps réel et installez manuellement des librairies via une interface dédiée.
*   **Amélioration de l’Autocorrection :** 🔁 Détection et correction plus fine des erreurs grâce à une boucle IA plus robuste.

## Prérequis

Avant de commencer, assurez-vous d'avoir installé et configuré les éléments suivants :

1.  **Python :** Version **3.11.9 ou supérieure**, ajoutée à la variable d’environnement `PATH`.  
    👉 Téléchargement ici : [https://www.python.org/downloads/release/python-3119/](https://www.python.org/downloads/release/python-3119/)

2.  **Connexion à une IA** (2 options disponibles) :

### 🧠 Méthode 1 : Utiliser LM Studio (recommandé pour usage local)

*   Téléchargez LM Studio depuis : [https://lmstudio.ai/](https://lmstudio.ai/)
*   Lancez l’application, allez dans la section des modèles (icône loupe).
*   Téléchargez un modèle "instruction-tuned" compatible (ex : `Openhands LM 7B v0.1`).
*   Dans l’onglet **Serveur Local** (`<->`), sélectionnez votre modèle, cliquez sur **"Démarrer le Serveur"**.
*   **(Optionnel)** Pour la connexion réseau, configurez LM Studio pour accepter des connexions extérieures (liaison à `0.0.0.0`).

### ☁️ Méthode 2 : Utiliser Gemini (API Google Generative AI)

*   Rendez-vous sur : [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
*   Générez une clé d’API.
*   Dans l’interface de PythAutom, activez l’option “Gemini” et collez la clé dans le champ prévu à cet effet.

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
* Installent `PyQt6`, `lmstudio-client` **et `google-generativeai`** dans cet environnement,
* Lancement automatique de `main.py` avec l'interpréteur de `.venv`.

## Fonctionnalités

*   **Interface Graphique (GUI) :** Interface intuitive avec PyQt6 pour gérer les projets et discuter avec l’IA.
*   **Génération de Code avec IA :** Le code Python est généré à partir de vos prompts grâce à un modèle IA local ou distant.
*   **Support double IA :** Choisissez entre LM Studio (local) ou Gemini (API).
*   **Gestion Automatique des Dépendances :** UV installe les bibliothèques nécessaires selon le contexte du projet.
*   **Exécution Isolée :** Chaque projet tourne dans son environnement virtuel propre, géré par UV.
*   **Débogage Basique et Boucle Itérative :** Capacité à détecter les erreurs et itérer automatiquement avec l’IA pour les corriger.
*   **Import/Export avancés** pour intégrer et partager vos projets plus facilement.
*   **Outils développeur intégrés** pour un contrôle manuel lors du développement.

## Améliorations Prévues / Feuille de Route

*   [x] Interaction conversationnelle améliorée avec l'IA.
*   [x] Fonction de génération stoppable.
*   [x] Autocorrection plus robuste et intelligente.
*   [x] Outils développeur accessibles via l’interface.
*   [x] Support de Gemini via clé API.
*   [ ] Intégration de capacités de vision IA.
