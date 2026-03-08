# Tests Industriels swap.exe

## 📋 Vue d'ensemble

Cette suite de tests industriels/extrêmes valide le système `swap.exe` dans des conditions de production critiques :
- **Millions de transactions** simulées
- **Milliers de BTC** par opération
- **Centaines de milliers de positions** traitées
- **Charge concurrente massive**
- **Benchmarks de performance détaillés**
- **Tests de résilience et récupération**

## 🎯 Objectifs

Valider que l'implémentation `swap.exe` peut gérer :
- ✅ **10,000+ positions** en une seule exécution
- ✅ **100,000+ positions** (test extrême)
- ✅ **Millions de BTC** par transaction
- ✅ **Exécutions concurrentes** (100+ simultanées)
- ✅ **Efficacité mémoire** (< 1GB pour 5000 positions)
- ✅ **Performance database** sous charge rapide
- ✅ **Throughput élevé** (> 1000 positions/sec)

## 🚀 Exécution des Tests

### Tests Standard (Rapides)

```bash
# Tests unitaires et intégration standards
pipenv run pytest tests/unit/test_swap_exe_parser_and_processor.py -v
pipenv run pytest tests/integration/test_swap_exe_e2e.py -v
pipenv run pytest tests/integration/test_swap_exe_volume.py -v
pipenv run pytest tests/integration/test_swap_exe_api.py -v
```

### Tests Industriels (Lents)

```bash
# Test industriel 10k positions (modéré)
pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_10k_positions -v -m slow

# Test industriel montants massifs
pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_massive_amounts -v -m slow

# Test industriel exécutions concurrentes
pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_concurrent_executions -v -m slow

# Test industriel efficacité mémoire
pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_memory_efficiency -v -m slow

# Test industriel stress database
pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_database_stress -v -m slow

# Tous les tests industriels (sauf extrêmes)
pipenv run pytest tests/integration/test_swap_exe_industrial.py -v -m slow
```

### Tests Extrêmes (Très Longs)

```bash
# Test extrême 100k positions (WARNING: Très long, nécessite ressources importantes)
SWAP_EXE_INDUSTRIAL_SCALE=100000 pipenv run pytest tests/integration/test_swap_exe_industrial.py::test_swap_exe_industrial_100k_positions -v -m extreme

# Ce test nécessite :
# - Au moins 8GB RAM
# - PostgreSQL avec ressources suffisantes
# - 30+ minutes d'exécution
```

### Benchmarks de Performance

```bash
# Benchmark petite échelle (100 positions)
pipenv run pytest tests/integration/test_swap_exe_performance_benchmark.py::test_swap_exe_performance_benchmark_small -v -s

# Benchmark moyenne échelle (1000 positions)
pipenv run pytest tests/integration/test_swap_exe_performance_benchmark.py::test_swap_exe_performance_benchmark_medium -v -s

# Benchmark grande échelle (10000 positions)
pipenv run pytest tests/integration/test_swap_exe_performance_benchmark.py::test_swap_exe_performance_benchmark_large -v -s

# Tous les benchmarks
pipenv run pytest tests/integration/test_swap_exe_performance_benchmark.py -v -s
```

## 📊 Métriques de Performance Attendues

### Test 10k Positions
- **Temps d'exécution** : < 5 minutes
- **Throughput** : > 33 positions/sec
- **Mémoire** : < 2GB

### Test 100k Positions (Extrême)
- **Temps d'exécution** : < 30 minutes
- **Throughput** : > 55 positions/sec
- **Mémoire** : < 8GB

### Test Montants Massifs (1M BTC)
- **Temps d'exécution** : < 5 secondes
- **Précision** : 100% (pas de perte de précision)

### Test Exécutions Concurrentes (100)
- **Taux de succès** : > 95%
- **Temps total** : < 2 minutes
- **Throughput** : > 50 exécutions/sec

### Test Efficacité Mémoire (5000 positions)
- **Mémoire totale** : < 1GB
- **Mémoire par position** : < 1MB

## 🔧 Configuration

### Variables d'Environnement

```bash
# Scale pour tests extrêmes (défaut: 10000)
export SWAP_EXE_INDUSTRIAL_SCALE=100000

# Pour tests d'expiration volumétriques existants
export SWAP_EXP_USERS=10000
```

### Prérequis

- **PostgreSQL** : Version 13+ avec ressources suffisantes
- **RAM** : Minimum 4GB pour tests standards, 8GB+ pour tests extrêmes
- **Disque** : Espace suffisant pour DB de test (10GB+ recommandé)
- **Python** : 3.11+ avec toutes les dépendances installées

## 📈 Interprétation des Résultats

### Résultats Acceptables

- ✅ Tous les tests passent
- ✅ Throughput > 100 positions/sec
- ✅ Temps d'exécution < seuils définis
- ✅ Mémoire < limites définies
- ✅ Taux de succès > 95% pour tests concurrents

### Points d'Attention

- ⚠️ Throughput < 50 positions/sec → Optimisation nécessaire
- ⚠️ Mémoire > limites → Optimisation mémoire requise
- ⚠️ Taux de succès < 95% → Investigation requise
- ⚠️ Temps d'exécution > seuils → Performance à améliorer

## 🐛 Dépannage

### Test échoue avec "Memory Error"
- Réduire `SWAP_EXE_INDUSTRIAL_SCALE`
- Augmenter RAM disponible
- Utiliser PostgreSQL au lieu de SQLite

### Test très lent
- Vérifier ressources système (CPU, RAM, I/O)
- Utiliser PostgreSQL optimisé
- Réduire nombre de positions

### Erreurs de base de données
- Vérifier connexion PostgreSQL
- Vérifier ressources DB (pool size, timeout)
- Augmenter `DB_POOL_SIZE` dans config

## 📝 Notes

- Les tests industriels peuvent prendre plusieurs minutes/heures
- Utiliser `-s` flag pour voir les prints de performance
- Les tests extrêmes doivent être exécutés dans un environnement dédié
- Surveiller les ressources système pendant l'exécution

## 🎯 Suite Complète de Tests

Pour exécuter toute la suite de tests swap.exe :

```bash
# Tests standards
pipenv run pytest tests/unit/test_swap_exe_parser_and_processor.py \
  tests/integration/test_swap_exe_e2e.py \
  tests/integration/test_swap_exe_volume.py \
  tests/integration/test_swap_exe_api.py -v

# Tests industriels (modérés)
pipenv run pytest tests/integration/test_swap_exe_industrial.py -v -m slow

# Benchmarks
pipenv run pytest tests/integration/test_swap_exe_performance_benchmark.py -v -s
```

## 📚 Références

- Documentation OPI : `docs/opi1_swap_init_report.md`
- Tests swap.init : `tests/integration/test_volume_expiration_huge.py`
- Guide contributeurs : `CONTRIBUTING.md`

