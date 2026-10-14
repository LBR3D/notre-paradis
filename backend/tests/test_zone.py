from app.services.zone import ZoneIndex, slugify

ROWS = [
    ("14514", "Pont-l'Évêque", "14"),
    ("14366", "Lisieux", "14"),
    ("14581", "Saint-Pierre-en-Auge", "14"),
    ("60506", "Pont-l'Évêque", "60"),  # homonyme hors zone
]


def test_slugify():
    assert slugify("Pont-l'Évêque") == "pont-l-eveque"
    assert slugify("  Saint-Pierre-en-Auge ") == "saint-pierre-en-auge"


def test_match_url_orpi_style():
    z = ZoneIndex(ROWS[:3])
    hit = z.match_url("https://www.orpi.com/annonce-vente-maison-t7-pont-l-eveque-14130-d5e5f1c6-7f98/")
    assert hit and hit.commune_code == "14514" and hit.postal_code == "14130"
    assert z.match_url("https://www.orpi.com/annonce-vente-maison-t4-villers-sur-meuse-55220-7230-048927-180/") is None


def test_match_url_same_name_other_department():
    z = ZoneIndex(ROWS[:3])
    assert z.match_url("https://x.fr/annonce-vente-maison-pont-l-eveque-60400-abc/") is None


def test_match_url_with_abbreviation():
    z = ZoneIndex(ROWS[:3])
    hit = z.match_url("https://x.fr/vente/maison-st-pierre-en-auge-14170-123")
    assert hit and hit.commune_code == "14581"


def test_match_text_and_name():
    z = ZoneIndex(ROWS[:3])
    assert z.match_text("Maison à vendre — 14100 Lisieux, Calvados").commune_code == "14366"
    assert z.match("Pont l'Évêque", "14130").commune_code == "14514"
    assert z.match("Pont-l'Évêque", None).commune_code == "14514"
    assert z.match("Paris", "75017") is None
