# Source initiale retenue — résultats et calendrier

Pour le premier modèle de probabilité de victoire, le projet utilisera les
fichiers de calendrier NBA publiés par **hoopR / SportsDataverse** et produits
à partir de l’API ESPN NBA.

- Données : une ligne par match, saisons disponibles de 2002 à aujourd’hui.
- Format retenu au départ : CSV de calendrier ; ce choix permet un import sans
  dépendance supplémentaire.
- Licence annoncée par le dépôt : CC BY 4.0.
- Attribution à conserver dans l’application et toute redistribution :
  `Source de données : hoopR.nba authors / SportsDataverse, CC BY 4.0 ; données
  ESPN NBA. Modifications : normalisation et calculs par NBA Picks.`

## Limites

Cette source ne fournit pas une validation de cotes de bookmakers. Les cotes,
blessures et autres données proches du direct restent hors du MVP jusqu’à ce
qu’une source distincte et adaptée soit validée.

## Téléchargement local

Quand la connexion Internet fonctionne, télécharge cinq saisons complètes pour
le premier entraînement :

```powershell
python -m scripts.download_hoopr_schedules
python -m scripts.download_hoopr_schedules 2027
```

Les fichiers sont conservés tels quels dans `data/raw/hoopr/` avec leur empreinte
SHA-256 affichée. Aucun fichier n’est téléchargé automatiquement par
l’application web.

Après téléchargement, importez les matchs terminés dans SQLite :

```powershell
python -m scripts.import_hoopr_schedules
```

Les matchs de saison régulière et de playoffs sont importés. Les matchs
postposés et événements hors compétition sont écartés. Les matchs planifiés
sont conservés sans score pour permettre la génération de probabilités.
