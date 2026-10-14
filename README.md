# Notre paradis

Application personnelle de recherche de maison de campagne : collecte des annonces, enrichissement par les données publiques, analyse des photos, notation selon vos goûts.

Zone de départ : le **Pays d'Auge** (7 intercommunalités du Calvados, de l'Eure et de l'Orne), avec la Côte fleurie pénalisée. Tout se règle dans l'application.

> État : **étape 0 (socle)** terminée. Voir [PLAN.md](PLAN.md) pour la suite.

---

## Ce qu'il y a dedans

| Élément | Rôle |
|---|---|
| `db` | PostgreSQL + PostGIS (toutes les données, y compris géographiques) |
| `app` | Une seule application Python : API (FastAPI), tâches planifiées (APScheduler) et interface web (React + MapLibre, compilée) |

Pages : **Carte** (fond IGN plan / photo aérienne, zone de recherche), **Liste**, **Nouveautés**, **Fiche bien**, **Réglages** (générés automatiquement), **Journaux** (tâches, exécutions, données publiques, budget API).

## Installer et lancer

Prérequis : Docker (Docker Desktop sous Windows, ou Docker sur le serveur).

```bash
git clone https://github.com/LBR3D/notre-paradis.git
cd notre-paradis
cp .env.example .env        # puis éditez .env (mot de passe, clés API)
docker compose up -d --build
```

Ouvrez <http://localhost:8000>. Au premier démarrage, l'application télécharge les contours des communes (environ 1 minute) puis affiche la zone sur la carte.

Mettre à jour après un changement de code :

```bash
git pull && docker compose up -d --build
```

Installation sur le serveur avec accès privé Tailscale : voir [docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md).

## Régler les critères

Tout se fait dans la page **Réglages** : le bien recherché, la zone, les critères éliminatoires et leurs seuils, les pondérations, l'apprentissage de vos goûts, la collecte, les nouveautés, le budget API. Chaque section a un bouton « Revenir aux valeurs par défaut ».

Pour ajouter un nouveau réglage, ajoutez un champ (avec titre et valeur par défaut) dans `backend/app/settings_schema.py` : il apparaît automatiquement dans le formulaire.

## Ajouter une source d'annonces

1. Créer `backend/app/connectors/ma_source.py` :

```python
from app.connectors.base import Connector, ListingData, ListingRef, register

@register
class MaSource(Connector):
    key = "ma_source"
    label = "Ma source"
    kind = "agence"

    def discover(self):
        page = self.client.get(self.config["url_liste"])      # client « poli »
        for url in ...:                                        # extraire les liens d'annonces
            yield ListingRef(url=url)

    def fetch(self, ref):
        page = self.client.get(ref.url)
        return ListingData(url=ref.url, title=..., price=..., photos=[...])
```

2. L'importer dans `backend/app/connectors/__init__.py`.
3. Ajouter un test avec une page d'exemple sauvegardée dans `backend/tests/pages/`.

Le client HTTP fourni (`self.client`) respecte robots.txt, espace les requêtes vers un même site, met les pages en cache et s'identifie avec un user-agent explicite. Les connecteurs sont prévus par **logiciel de site d'agence** (un connecteur couvre toutes les agences qui utilisent ce logiciel), avec un extracteur générique par LLM pour les autres.

## Ajouter une source de données publiques

Créer une classe qui hérite de `DataSource` dans `backend/app/datasources/` (voir `communes.py`), avec `refresh()` pour télécharger et mettre en cache, et `enrich()` pour calculer les valeurs d'un bien. La source, la date des données et la date de mise à jour sont enregistrées automatiquement et visibles dans **Journaux**.

## Développement

```bash
docker compose up -d db
docker compose exec db createdb -U paradis paradis_test   # une fois
cd backend
python -m venv .venv && . .venv/bin/activate              # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
DATABASE_URL=postgresql+psycopg://paradis:paradis@localhost:5432/paradis alembic upgrade head
DATABASE_URL=postgresql+psycopg://paradis:paradis@localhost:5432/paradis SCHEDULER_ENABLED=false uvicorn app.main:app --reload
pytest                                                     # tests

cd ../frontend && npm install && npm run dev               # interface sur http://localhost:5173
```

Pour exposer la base en local, ajoutez `ports: ["127.0.0.1:5432:5432"]` au service `db` (fichier `docker-compose.override.yml`).

Modifier le schéma de base : changer `backend/app/models.py`, puis `alembic revision --autogenerate -m "description"`.

## Organisation du code

```
backend/app/
  settings_schema.py   réglages modifiables (génère le formulaire)
  models.py            tables
  connectors/          sources d'annonces (une classe par source ou logiciel)
  datasources/         données publiques (une classe par jeu de données)
  services/            enregistrement des annonces, historique, réglages
  jobs/                tâches planifiées et journal d'exécution
  api/                 API HTTP
frontend/src/          interface (React + MapLibre)
```
