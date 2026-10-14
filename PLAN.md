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

## Étape 1 — Collecte et MVP
- Découverte de toutes les agences, mandataires et notaires de la zone (Sirene) + réseaux nationaux + biens de caractère + notaires (immonot, immobilier.notaires.fr).
- Connecteurs par logiciel de site d'agence + extracteur générique (LLM) ; tests sur pages sauvegardées.
- Portails : automatique quand l'accès est ouvert ; sinon lecture des e-mails d'alerte des portails + extension navigateur « Envoyer à Notre paradis ».
- Extraction structurée, photos HD, dédoublonnage (empreintes de photos, caractéristiques, proximité), historique.
- Géolocalisation en cascade : adresse → DPE ADEME → cadastre / DVF → orthophoto assistée → centre de la commune, avec niveau de confiance.
- Trajets (TomTom, trafic du vendredi soir), isochrone 3 h, comparables DVF et écart au marché.
- Réactions J'aime / Bof / Non dès cette étape (pour accumuler vos goûts).
- Déploiement sur le serveur.

## Étape 2 — Territoire et éliminatoires
Bruit, cultures (RPG), haies, élevages et méthaniseurs (ICPE), Géorisques, sols, relief et vue, nature, éoliennes, lignes HT, antennes, PLU et monuments historiques, équipements, fibre, eau, air. Calques de carte. Éliminatoires avec raison.

## Étape 3 — Analyse et notation
Analyse des photos et du texte (Claude), travaux avec grille de prix modifiable, potentiel, signaux d'alerte, questions à poser. Onze notes sur 5 expliquées. Apprentissage des goûts : modèle explicable, page « Ce que j'ai compris de vos goûts », propositions de pondérations et de nouveaux critères.

## Étape 4 — Nouveautés et fiche PDF
Nouveautés filtrées par score et baisses de prix, résumé hebdomadaire du marché dans l'application, fiche PDF de visite.

## Étape 5 — Visites et nouvelles zones
Planificateur de week-end (tournée optimisée au départ de Paris). Extension : Perche, Pays de Bray, Suisse normande, Eure, et repérage automatique des zones similaires à moins de 3 h.
