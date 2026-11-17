# Lignes Over/Under

Le projet ne récupère pas encore de cotes automatiquement. Pour comparer une
projection de total à une ligne réellement proposée, créez un fichier
`data/market_totals.csv` à partir de `market_totals.example.csv`.

- `game_id` : identifiant affiché dans `data/picks.json` ;
- `total_line` : total du bookmaker, par exemple `222.5` ;
- `book` : nom du bookmaker, uniquement pour la traçabilité.

Le modèle conserve les lignes pour son suivi historique. L’interface affiche
des seuils prudents construits avec une marge fixe de 10 points autour de sa
projection : une projection de 220 mène à `Over 210` ou `Under 230` selon le
sens du signal. Ces seuils sont des repères de modèle et ne correspondent pas
forcément à une ligne effectivement proposée par un bookmaker.
