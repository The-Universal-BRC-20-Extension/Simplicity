#!/usr/bin/env python3
"""Replace French comments/docstrings with minimal English in test files."""

import os
import re

REPLACEMENTS = [
    # Docstrings and comments - common French
    (r"Test d'intégration en circuit fermé pour le protocole de wrapping\.\s*Ce script teste.*?\." , "Closed-loop integration test for wrapping protocol."),
    (r"Création d'une Tx_Commit et Tx_Reveal valides", "Create valid Tx_Commit and Tx_Reveal"),
    (r"Passage de la Tx_Reveal au BRC20Processor", "Pass Tx_Reveal to BRC20Processor"),
    (r"Vérification que le mint a été correctement indexé", "Verify mint is correctly indexed"),
    (r"Création d'une Tx_Unlock valide qui dépense l'UTXO du contrat", "Create valid Tx_Unlock spending contract UTXO"),
    (r"Passage de la Tx_Unlock au BRC20Processor", "Pass Tx_Unlock to BRC20Processor"),
    (r"Vérification que le burn a été correctement indexé", "Verify burn is correctly indexed"),
    (r"# Ajouter le répertoire src au path", "# Add src to path"),
    (r"Mock Bitcoin RPC pour les tests", "Mock Bitcoin RPC for tests"),
    (r"Retourne une transaction mock", "Return mock transaction"),
    (r"# Transaction mock par défaut", "# Default mock transaction"),
    (r"Ajoute une transaction mock", "Add mock transaction"),
    (r"Mock UTXO Service pour les tests", "Mock UTXO Service for tests"),
    (r"Retourne l'adresse mock pour un input", "Return mock address for input"),
    (r"Définit l'adresse pour un input", "Set address for input"),
    (r"Crée une transaction Tx_Reveal mock pour le test", "Create mock Tx_Reveal for test"),
    (r"# Données de test", "# Test data"),
    (r"# Adresse de contrat mock \(sera calculée par la validation\)", "# Mock contract address (computed by validation)"),
    (r"Crée une transaction Tx_Unlock mock pour le test", "Create mock Tx_Unlock for test"),
    (r"# Dépense l'output du contrat", "# Spend contract output"),
    (r"Test d'intégration principal", "Main integration test"),
    (r"🚀 Démarrage du test d'intégration du protocole de wrapping", "Starting wrap protocol integration test"),
    (r"# 1\. Configuration des mocks", "# 1. Configure mocks"),
    (r"# 2\. Création du processeur", "# 2. Create processor"),
    (r"# 3\. Création de l'état intermédiaire", "# 3. Create intermediate state"),
    (r"# 4\. Test de la Tx_Reveal \(Wrap Mint\)", "# 4. Test Tx_Reveal (Wrap Mint)"),
    (r"# Parser l'OP_RETURN", "# Parse OP_RETURN"),
    (r"# Traitement de la transaction", "# Process transaction"),
    (r"Résultat: ", "Result: "),
    (r"Erreur: ", "Error: "),
    (r"# 5\. Vérification de l'état après mint", "# 5. Verify state after mint"),
    (r"# Vérifier que le contrat a été créé \(simulation\)", "# Contract created (simulation)"),
    (r"# Vérifier que la balance a été créditée", "# Verify balance credited"),
    (r"Balance de l'initiateur: ", "Initiator balance: "),
    (r"# 6\. Test de la Tx_Unlock \(Wrap Burn\)", "# 6. Test Tx_Unlock (Wrap Burn)"),
    (r"# 7\. Vérification de l'état final", "# 7. Verify final state"),
    (r"# Vérifier que la balance a été débitée", "# Verify balance debited"),
    (r"Balance finale: ", "Final balance: "),
    (r"Test d'intégration terminé avec succès !", "Integration test completed successfully"),
    # test_reorg_expiration
    (r"\(In prod, reorg handler rejoue les blocs; ici on simule un retour à ACTIVE et agrégat = 10\)", "(Simulate rollback: return to ACTIVE, agg=10)"),
    (r"# pas de double crédit", "# no double credit"),
    (r"expiration doit re-s'appliquer correctement", "expiration must re-apply correctly"),
]

FRENCH_PHRASES = {
    "Script de test standalone pour valider le recalcul d'adresse Taproot.": "Standalone script to validate Taproot address recalculation.",
    "Ce script prend une raw_tx_hex et vérifie si on peut recalculer l'adresse de OUTPUT[2] à partir du witness.": "Takes raw_tx_hex and verifies OUTPUT[2] address can be recalculated from witness.",
    "# Import des fonctions cryptographiques nécessaires": "# Import crypto utilities",
    "Parse le script révélé et le control block pour extraire les éléments nécessaires au calcul d'adresse.": "Parse revealed script and control block to extract address calculation data.",
    "FOCUS: Extraction des données cryptographiques uniquement.": "FOCUS: Extract crypto data only.",
    "W_PROOF est ignoré (on cherche juste la structure).": "W_PROOF ignored (structure only).",
    "# 7. Alice pubkey répétée (inscrite) - on skip car on a déjà la première": "# 7. Alice pubkey repeated (inscribed) - skip, use first",
    "# 1. Décoder la transaction": "# 1. Decode transaction",
    "# 5. Récupérer la platform pubkey": "# 5. Get platform pubkey",
    "# 6. Créer les scripts Taproot": "# 6. Create Taproot scripts",
    "# 8. Tweak et dérivation d'adresse": "# 8. Tweak and address derivation",
    "# Mutations déjà appliquées par le processeur OPI dans process_transaction": "# Mutations already applied by OPI processor in process_transaction",
    "Test d'intégration simplifié avec les données Bitcoin réelles exactes": "Simplified integration test with exact real Bitcoin data",
}

def clean_file(path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    orig = content
    for fr, en in FRENCH_PHRASES.items():
        content = content.replace(fr, en)
    for pattern, repl in REPLACEMENTS:
        content = re.sub(pattern, repl, content, flags=re.DOTALL)
    if content != orig:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Cleaned: {path}")

def main():
    test_dir = os.path.join(os.path.dirname(__file__), "..", "tests")
    for root, _, files in os.walk(test_dir):
        for f in files:
            if f.endswith(".py"):
                clean_file(os.path.join(root, f))

if __name__ == "__main__":
    main()
