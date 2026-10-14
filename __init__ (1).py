"""Sources de données publiques. Importer un module suffit à l'enregistrer."""
from app.datasources import communes, dvf, routes  # noqa: F401
from app.datasources.base import REGISTRY  # noqa: F401
