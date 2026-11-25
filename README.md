# BetPawa virtual collector
1. Cree un depot GitHub PUBLIC et envoie-y ces fichiers (garde le dossier `.github`).
2. Settings > Actions > General > Workflow permissions : "Read and write permissions".
3. Onglet Actions > collect > Run workflow, avec `start_round` = un round qui n'a pas encore commence.
4. Les donnees arrivent dans `data/AAAA-MM-JJ.csv`. Analyse: `python analyze.py` (ou `python ml_test.py`).
Si le job echoue avec "aucune reponse du site", GitHub est bloque: lance collect.py sur un PC/serveur a la place.
