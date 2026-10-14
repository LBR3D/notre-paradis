# Plan validé

Utilisateur unique, accès privé (Tailscale), serveur loué, code sur GitHub privé.
Alertes uniquement dans l'application (onglet « Nouveautés »). Budget API Claude : 40 €/mois, coupure automatique.

## Étape 0 — Socle ✅
- Docker Compose : PostGIS + une application Python (API, planificateur, interface).
- Schéma de base : sources, agences, annonces, photos, historique des prix, biens, enrichissements, réactions, journaux, consommation API, réglages.
- Réglages modifiables dans l'application (formulaire généré automatiquement).
- Interfaces communes : connecteurs d'annonces, sources de données publiques, client HTTP poli (robots.txt, débit, cache, user-agent).
- Tâches planifiées avec journal ; données publiques avec source et date.
- Carte (fonds IGN), liste, nouveautés, fiche, réglages, journaux.
- Zone : Pays d'Auge (263 communes), Côte fleurie pénalisée (19 communes).

## Étape 1 — Collecte et MVP (en cours)
Fait :
- ✅ Découverte des agences et notaires de la zone (Sirene) : 456 établissements.
- ✅ Collecte par connecteurs testés sur pages réelles : Orpi, iad, Guy Hoquet, Laforêt, Century 21, Barnes, Espaces Atypiques, Immonot (notaires), Nestenn, Agence de la Dives, Cheychrys. Extracteur générique (JSON-LD, OpenGraph, données intégrées, texte), sans clé d'API.
- ✅ robots.txt respecté (jokers compris), délais, cache. Désactivées faute d'accès autorisé : notaires.fr, Stéphane Plaza, Belles Pierres, Agence honfleuraise (blocage anti-robot, aucun contournement).
- ✅ Dédoublonnage (photos + caractéristiques), historique des prix.
- ✅ Géolocalisation : adresse (BAN) → DPE ADEME → coordonnées de l'annonce → centre commune, avec niveau A–D.
- ✅ Trajet (OSRM ; TomTom vendredi soir dès que la clé est saisie), comparables DVF (44 788 ventes) et écart au marché.
À faire : extracteur par IA pour les champs manquants (clé Anthropic), portails par e-mail d'alerte + extension navigateur, cadastre / orthophoto assistée, isochrone 3 h, autres agences locales (sites à trouver), déploiement sur le serveur.

## Étape 2 — Territoire et éliminatoires
Bruit, cultures (RPG), haies, élevages et méthaniseurs (ICPE), Géorisques, sols, relief et vue, nature, éoliennes, lignes HT, antennes, PLU et monuments historiques, équipements, fibre, eau, air. Calques de carte. Éliminatoires avec raison.

## Étape 3 — Analyse et notation
Analyse des photos et du texte (Claude), travaux avec grille de prix modifiable, potentiel, signaux d'alerte, questions à poser. Onze notes sur 5 expliquées. Apprentissage des goûts : modèle explicable, page « Ce que j'ai compris de vos goûts », propositions de pondérations et de nouveaux critères.

## Étape 4 — Nouveautés et fiche PDF
Nouveautés filtrées par score et baisses de prix, résumé hebdomadaire du marché dans l'application, fiche PDF de visite.

## Étape 5 — Visites et nouvelles zones
Planificateur de week-end (tournée optimisée au départ de Paris). Extension : Perche, Pays de Bray, Suisse normande, Eure, et repérage automatique des zones similaires à moins de 3 h.
