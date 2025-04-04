# PythAutom : Constructeur de Projets Python en Un Clic avec IA

[![English](https://img.shields.io/badge/Language-English-blue.svg)](README.md)

PythAutom est une application de bureau utilisant PyQt6, UV et LM Studio pour aider les utilisateurs à créer des projets Python en interagissant avec un modèle d'IA exécuté localement.

## Prérequis

Avant de commencer, assurez-vous d'avoir installé et configuré les éléments suivants :

1.  **Python :** Version **3.11 ou supérieure** installée et ajoutée correctement à la variable d'environnement `PATH` de votre système.
2.  **LM Studio :**
    *   Téléchargez et installez LM Studio depuis le site officiel : [https://lmstudio.ai/](https://lmstudio.ai/)
    *   Lancez l'application LM Studio.
    *   Naviguez vers la section de téléchargement de modèles (icône de recherche).
    *   Téléchargez un modèle compatible "instruction-tuned" (par exemple, `Qwen/Qwen1.5-7B-Chat-GGUF` ou similaire).
    *   Allez dans l'onglet **Serveur Local** (icône `<->` sur la gauche).
    *   Sélectionnez le modèle téléchargé dans le menu déroulant en haut.
    *   Cliquez sur le bouton **"Démarrer le Serveur"** ("Start Server").
    *   **Important :** Laissez LM Studio tourner avec le serveur actif pendant que vous utilisez PythAutom.

## Comment Lancer

1.  **Double-cliquez** simplement sur le fichier `run.bat` situé à la racine du projet.
2.  Ce script batch automatise le processus de configuration :
    *   Il vérifie si **UV** (un installateur et résolveur de paquets Python rapide) est installé. Sinon, il le télécharge et l'installe localement dans la structure du projet.
    *   Il utilise UV pour créer un environnement virtuel Python isolé nommé `.venv`.
    *   Il installe les bibliothèques Python requises (`PyQt6`, `lmstudio-client`) dans l'environnement `.venv` en utilisant UV.
    *   Enfin, il lance l'application principale PythAutom (`main.py`) en utilisant l'interpréteur Python de l'environnement `.venv`.

## Fonctionnalités

*   **Interface Utilisateur Graphique (GUI) :** Fournit une interface intuitive construite avec PyQt6 pour gérer les projets et interagir avec l'IA.
*   **Génération de Code Assistée par IA :** Utilise des modèles de langage exécutés localement via le serveur LM Studio pour générer du code Python basé sur les invites de l'utilisateur.
*   **Gestion Automatique des Dépendances :** Exploite UV pour installer automatiquement les bibliothèques requises en fonction des suggestions de l'IA ou des demandes explicites de l'utilisateur dans le contexte du projet.
*   **Exécution Isolée des Projets :** Exécute les scripts Python générés dans leurs environnements virtuels spécifiques et isolés, gérés par UV.
*   **Gestion Basique des Erreurs & Itération :** Inclut des mécanismes de base pour attraper les erreurs lors de l'exécution des scripts et permet d'itérer avec l'IA pour déboguer et corriger le code.

## Remerciements

Ce projet s'appuie fortement sur **LM Studio** pour permettre l'exécution locale de modèles d'IA via sa fonctionnalité de serveur. Un grand merci à **l'équipe de LM Studio** pour la création et la maintenance d'un outil aussi fantastique et convivial !

*   En savoir plus sur LM Studio : [https://lmstudio.ai/](https://lmstudio.ai/)

## Améliorations Prévues / Feuille de Route

*   [ ] Interaction conversationnelle améliorée avec l'IA.
*   [ ] Fonctionnalité pour exporter les projets générés en tant que paquets ou structures autonomes.
*   [ ] Intégration de capacités de vision à l'IA (par ex., interpréter des diagrammes ou des maquettes d'interface).
*   [ ] Mécanismes d'autocorrection améliorés pour le code généré basés sur les erreurs.

---
