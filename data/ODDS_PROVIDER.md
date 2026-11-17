# Cotes NBA

HoopsAPI fournit les cotes Pinnacle et FanDuel. Configurer la variable d’environnement utilisateur Windows `HOOPS_API_KEY`. Le lanceur la transmet au serveur.

```powershell
python -m scripts.sync_hoopsapi_odds
python -m scripts.generate_picks
python -m scripts.analyze_line_movement
```

La routine automatique tente la synchronisation toutes les six heures. Les cotes sont écartées de l’analyse après quatre heures. Les prix sont enregistrés en décimal et rapprochés du calendrier par équipes et horaire. La variation d’une ligne s’affiche à partir de deux relevés du même bookmaker.

Le vainqueur est évalué à son prix observé. Pour le total, l’estimation utilise les erreurs récentes du modèle et traite séparément le remboursement en cas d’égalité avec la ligne.
