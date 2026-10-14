"""Réglages modifiables dans l'application (page « Réglages »).

Chaque champ porte un titre et une description en français : l'interface
génère le formulaire automatiquement à partir de ce schéma. Pour ajouter un
réglage, il suffit d'ajouter un champ ici (avec une valeur par défaut) —
aucune modification du front n'est nécessaire.

Les valeurs enregistrées sont fusionnées avec ces valeurs par défaut : un
nouveau champ ajouté dans une version ultérieure prend sa valeur par défaut.
"""
from typing import Literal

from pydantic import BaseModel, Field

TypeBien = Literal[
    "longère",
    "colombages",
    "maison de maître",
    "moulin",
    "presbytère",
    "corps de ferme",
    "chaumière",
    "manoir",
    "maison de village",
    "maison traditionnelle",
    "construction récente",
]
Etat = Literal["clé en main", "rafraîchissement", "rénovation lourde", "à restaurer / ruine"]

# Les 11 critères notés sur 5
CRITERES = {
    "acces_voiture": "Accès en voiture",
    "acces_train": "Accès en train",
    "cachet": "Cachet",
    "travaux": "Travaux (5 = rien à faire)",
    "potentiel": "Potentiel",
    "terrain": "Terrain",
    "rapport_qualite_prix": "Rapport qualité/prix",
    "calme_nature": "Calme et nature",
    "capacite_accueil": "Capacité d'accueil",
    "risques": "Risques",
    "paysage_bocage": "Paysage et bocage",
}

PAYS_D_AUGE_EPCI = [
    "200069532",  # CA Lisieux Normandie
    "241400878",  # CC Terre d'Auge
    "241400415",  # CC Cœur Côte Fleurie
    "200066827",  # CC du Pays de Honfleur-Beuzeville
    "200065563",  # CC Normandie-Cabourg-Pays d'Auge
    "200066017",  # CC Lieuvin Pays d'Auge
    "200069458",  # CC des Vallées d'Auge et du Merlerault
]

COTE_FLEURIE = [
    "14059", "14079", "14117", "14220", "14225", "14243", "14305", "14333", "14338",
    "14492", "14557", "14578", "14645", "14699", "14701", "14715", "14731", "14754", "14755",
]


class Criteres(BaseModel):
    """Un bien hors critères n'est pas éliminé : il est pénalisé et signalé."""

    prix_max_eur: int = Field(800_000, title="Prix maximum (€, frais d'agence inclus)", ge=0, json_schema_extra={"step": 10000})
    budget_travaux_max_eur: int = Field(200_000, title="Budget travaux maximum (€)", ge=0, json_schema_extra={"step": 10000})
    budget_total_max_eur: int = Field(900_000, title="Budget total maximum, prix + travaux (€)", ge=0, json_schema_extra={"step": 10000})
    surface_min_m2: int = Field(80, title="Surface habitable minimum (m²)", ge=0)
    surface_max_m2: int = Field(400, title="Surface habitable maximum (m²)", description="Au-delà, le bien est jugé trop grand à entretenir.", ge=0)
    chambres_min: int = Field(2, title="Chambres minimum", ge=0, le=20)
    terrain_min_m2: int = Field(1000, title="Terrain minimum (m²)", ge=0, json_schema_extra={"step": 500})
    terrain_ideal_m2: int = Field(10000, title="Terrain idéal (m²)", description="La note « terrain » atteint 5 à partir de cette surface.", ge=0, json_schema_extra={"step": 500})
    etats_acceptes: list[Etat] = Field(
        default_factory=lambda: ["clé en main", "rafraîchissement", "rénovation lourde", "à restaurer / ruine"],
        title="États acceptés",
    )
    types_preferes: list[TypeBien] = Field(
        default_factory=lambda: ["longère", "colombages", "maison de maître", "moulin", "presbytère", "corps de ferme", "chaumière", "manoir"],
        title="Types de bien préférés",
    )
    types_exclus: list[TypeBien] = Field(default_factory=lambda: ["construction récente"], title="Types de bien exclus")
    distance_voisin_min_m: int = Field(50, title="Distance minimum au voisin le plus proche (m)", ge=0)
    inclure_encheres: bool = Field(True, title="Inclure les ventes aux enchères notariales")
    inclure_viager: bool = Field(False, title="Inclure les viagers")


class Zone(BaseModel):
    """Zone de recherche, communes pénalisées et départ des trajets."""

    epci: list[str] = Field(
        default_factory=lambda: list(PAYS_D_AUGE_EPCI),
        title="Intercommunalités de la zone",
        description="Par défaut : le Pays d'Auge (Calvados, Eure, Orne).",
        json_schema_extra={"widget": "epci"},
    )
    communes_penalisees: list[str] = Field(
        default_factory=lambda: list(COTE_FLEURIE),
        title="Communes pénalisées (Côte fleurie)",
        json_schema_extra={"widget": "communes"},
    )
    penalite_communes: float = Field(0.5, title="Pénalité sur la note finale (points sur 5)", ge=0, le=5, json_schema_extra={"step": 0.1})
    adresse_depart: str = Field("53 avenue de Saint-Ouen, 75017 Paris", title="Adresse de départ")
    depart_lat: float = Field(48.8907, title="Latitude du départ")
    depart_lon: float = Field(2.3262, title="Longitude du départ")
    temps_route_max_min: int = Field(180, title="Temps de route maximum (minutes)", ge=30, le=300)
    depart_vendredi_heure: str = Field("18:00", title="Heure de départ le vendredi soir")


class Eliminatoires(BaseModel):
    """Un bien éliminé reste consultable, avec la raison de son élimination."""

    actif_bruit: bool = Field(True, title="Activer les éliminatoires « bruit »")
    autoroute_m: int = Field(1500, title="Distance minimum à une autoroute (m)", ge=0, json_schema_extra={"step": 100})
    route_chargee_m: int = Field(300, title="Distance minimum à une route chargée (m)", ge=0, json_schema_extra={"step": 50})
    route_chargee_seuil_vehicules_jour: int = Field(5000, title="Route « chargée » au-delà de (véhicules/jour)", ge=0, json_schema_extra={"step": 500})
    voie_ferree_m: int = Field(500, title="Distance minimum à une voie ferrée en service (m)", ge=0, json_schema_extra={"step": 50})
    aerodrome_m: int = Field(3000, title="Distance minimum à un aérodrome, dans l'axe (m)", ge=0, json_schema_extra={"step": 250})
    bruit_lden_max_db: int = Field(55, title="Bruit estimé maximum (Lden, dB)", ge=30, le=80)

    actif_agriculture: bool = Field(True, title="Activer les éliminatoires « agriculture »")
    elevage_intensif_m: int = Field(1000, title="Distance minimum à un élevage intensif (m)", ge=0, json_schema_extra={"step": 100})
    ponderer_vent_dominant: bool = Field(True, title="Tenir compte des vents d'ouest (élevages)")
    methaniseur_m: int = Field(1500, title="Distance minimum à un méthaniseur (m)", ge=0, json_schema_extra={"step": 100})
    grandes_cultures_rayon_m: int = Field(1000, title="Rayon d'analyse des cultures (m)", ge=200, le=5000, json_schema_extra={"step": 100})
    grandes_cultures_max_pct: int = Field(50, title="Part maximum de grandes cultures dans le rayon (%)", ge=0, le=100)


class Ponderations(BaseModel):
    """Poids de chaque critère dans la note finale (0 = ignoré)."""

    acces_voiture: float = Field(7, title=CRITERES["acces_voiture"], ge=0, le=10)
    acces_train: float = Field(3, title=CRITERES["acces_train"], ge=0, le=10)
    cachet: float = Field(9, title=CRITERES["cachet"], ge=0, le=10)
    travaux: float = Field(5, title=CRITERES["travaux"], ge=0, le=10)
    potentiel: float = Field(5, title=CRITERES["potentiel"], ge=0, le=10)
    terrain: float = Field(6, title=CRITERES["terrain"], ge=0, le=10)
    rapport_qualite_prix: float = Field(6, title=CRITERES["rapport_qualite_prix"], ge=0, le=10)
    calme_nature: float = Field(9, title=CRITERES["calme_nature"], ge=0, le=10)
    capacite_accueil: float = Field(4, title=CRITERES["capacite_accueil"], ge=0, le=10)
    risques: float = Field(6, title=CRITERES["risques"], ge=0, le=10)
    paysage_bocage: float = Field(9, title=CRITERES["paysage_bocage"], ge=0, le=10)


class Apprentissage(BaseModel):
    """L'outil apprend de vos réactions (J'aime / Bof / Non) et propose des ajustements."""

    actif: bool = Field(True, title="Apprendre de mes réactions")
    reactions_min: int = Field(15, title="Nombre de réactions avant de commencer à apprendre", ge=5)
    poids_max_gout: float = Field(0.5, title="Part maximum du « goût appris » dans la note finale", ge=0, le=1, json_schema_extra={"step": 0.05})


class Collecte(BaseModel):
    """Collecte automatique des annonces sur les sites des agences et notaires."""

    actif: bool = Field(True, title="Collecte automatique activée")
    heures: list[int] = Field(default_factory=lambda: [7, 12, 18, 22], title="Heures de collecte", json_schema_extra={"widget": "heures"})
    delai_min_secondes: float = Field(4.0, title="Délai minimum entre deux pages d'un même site (s)", ge=1, le=60)
    duree_cache_heures: int = Field(6, title="Durée du cache des pages (heures)", ge=0)


class Alertes(BaseModel):
    """Ce qui apparaît dans l'onglet « Nouveautés »."""

    score_min: float = Field(3.5, title="Score minimum pour signaler un nouveau bien (sur 5)", ge=0, le=5, json_schema_extra={"step": 0.1})
    baisse_prix_min_pct: float = Field(3, title="Baisse de prix minimum signalée (%)", ge=0, le=50)


class BudgetAPI(BaseModel):
    """Maîtrise des coûts : l'analyse s'arrête automatiquement au plafond."""

    plafond_mensuel_eur: float = Field(40, title="Plafond mensuel API Claude (€)", ge=0)
    modele_photos: str = Field("haiku", title="Modèle pour le tri des photos")
    modele_synthese: str = Field("sonnet", title="Modèle pour la synthèse par bien")
    score_min_pour_analyse: float = Field(2.5, title="Score de base minimum pour lancer l'analyse photo", ge=0, le=5, json_schema_extra={"step": 0.1})


class UserSettings(BaseModel):
    criteres: Criteres = Field(default_factory=Criteres, title="Le bien recherché")
    zone: Zone = Field(default_factory=Zone, title="Zone et trajets")
    eliminatoires: Eliminatoires = Field(default_factory=Eliminatoires, title="Critères éliminatoires")
    ponderations: Ponderations = Field(default_factory=Ponderations, title="Pondérations")
    apprentissage: Apprentissage = Field(default_factory=Apprentissage, title="Apprentissage de vos goûts")
    collecte: Collecte = Field(default_factory=Collecte, title="Collecte")
    alertes: Alertes = Field(default_factory=Alertes, title="Nouveautés")
    budget_api: BudgetAPI = Field(default_factory=BudgetAPI, title="Budget API")
