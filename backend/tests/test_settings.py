import pytest
from pydantic import ValidationError

from app.services.settings_service import load_settings, reset_section, save_settings
from app.settings_schema import COTE_FLEURIE, UserSettings


def test_defaults_cover_pays_d_auge():
    s = UserSettings()
    assert len(s.zone.epci) == 7
    assert "14220" in s.zone.communes_penalisees  # Deauville
    assert set(COTE_FLEURIE) == set(s.zone.communes_penalisees)


def test_save_merges_and_validates(db):
    save_settings(db, {"criteres": {"chambres_min": 4}})
    s = load_settings(db)
    assert s.criteres.chambres_min == 4
    assert s.criteres.terrain_min_m2 == 1000  # inchangé

    with pytest.raises(ValidationError):
        save_settings(db, {"eliminatoires": {"grandes_cultures_max_pct": 150}})


def test_reset_section(db):
    save_settings(db, {"ponderations": {"cachet": 1}})
    reset_section(db, "ponderations")
    assert load_settings(db).ponderations.cachet == UserSettings().ponderations.cachet


def test_unknown_stored_fields_are_ignored(db):
    from app.models import AppSettings

    db.add(AppSettings(id=1, data={"criteres": {"champ_disparu": 3, "chambres_min": 5}}))
    db.commit()
    assert load_settings(db).criteres.chambres_min == 5
