# Données

Ce dossier accueillera seulement des données dont les conditions d’utilisation et de redistribution ont été vérifiées. La première source retenue est décrite dans [`SOURCE.md`](SOURCE.md).

## Contrat minimal pour le premier import

Un fichier d’historique doit fournir une ligne par match avec les champs suivants :

```text
game_id,game_date,season,season_type,home_team,away_team,home_points,away_points,source_name,source_game_id
```

- `game_date` : format ISO `YYYY-MM-DD`.
- `season_type` : `regular` ou `playoffs`.
- les scores doivent être absents ensemble pour un match non terminé ; sinon ils doivent être tous les deux présents.
- `source_name` et `source_game_id` assurent la traçabilité de chaque match.

## Décision de source

Ne pas aspirer automatiquement NBA.com : sa FAQ précise que les statistiques ne sont pas disponibles au téléchargement, même pour une utilisation personnelle ou universitaire. Les calendriers historiques hoopR / SportsDataverse constituent la première source ; ils sont publiés sous CC BY 4.0 avec attribution obligatoire. Voir [`SOURCE.md`](SOURCE.md).
