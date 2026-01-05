"""
Tests for Dynamic Materials Loading (No Hardcoding).

These tests ensure that:
1. Materials shown to users come from the database, not hardcoded values
2. Only applicable materials for a given HTS code are returned
3. The API response includes the correct applicable_materials list
4. Frontend would only show materials that exist in the database

This prevents the bug where steel was shown for HTS codes that only have
copper/aluminum in the section_232_materials table.
"""

import json
import pytest
from unittest.mock import patch, Mock


@pytest.fixture
def tariff_app(app):
    """App fixture with tariff tables created."""
    from app.web.db import db
    from app.web.db.models.tariff_tables import (
        Section232Material, TariffProgram, Section301Inclusion
    )

    with app.app_context():
        # Tables are created by db.create_all() in the app fixture
        yield app


class TestEnsureMaterialsNoHardcoding:
    """Tests for ensure_materials tool - verifies no hardcoded materials."""

    def test_ensure_materials_returns_only_db_materials(self, tariff_app):
        """Verify ensure_materials returns ONLY materials from the database."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Setup: Add only copper and aluminum for HTS 85444290
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="aluminum",
                claim_code="9903.85.08",
                disclaim_code="9903.85.09",
                duty_rate=0.10
            ))
            # NOTE: NO STEEL entry for this HTS code
            db.session.commit()

            # Patch get_flask_app to return our test app
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result = ensure_materials.invoke({
                    "hts_code": "8544.42.9090",
                    "product_description": "electrical conductor",
                    "known_materials": None
                })
            data = json.loads(result)

            # Assert: Only copper and aluminum returned, NO STEEL
            assert data["materials_needed"] is True
            assert "copper" in data["applicable_materials"]
            assert "aluminum" in data["applicable_materials"]
            assert "steel" not in data["applicable_materials"], \
                "Steel should NOT be in applicable_materials - it's not in the database for this HTS"
            assert len(data["applicable_materials"]) == 2

    def test_ensure_materials_no_materials_for_hts(self, tariff_app):
        """Verify ensure_materials returns empty when HTS has no 232 materials."""
        with tariff_app.app_context():
            # No materials in database for this HTS
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result = ensure_materials.invoke({
                    "hts_code": "9999.99.9999",
                    "product_description": "random product",
                    "known_materials": None
                })
            data = json.loads(result)

            # Assert: No materials needed
            assert data["materials_needed"] is False
            assert "applicable_materials" not in data or data.get("applicable_materials") == []

    def test_ensure_materials_only_steel(self, tariff_app):
        """Verify when only steel exists, only steel is returned."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Setup: Add only steel for a specific HTS
            db.session.add(Section232Material(
                hts_8digit="72101100",  # A steel product HTS
                material="steel",
                claim_code="9903.80.01",
                disclaim_code="9903.80.02",
                duty_rate=0.25
            ))
            db.session.commit()

            # Call ensure_materials
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result = ensure_materials.invoke({
                    "hts_code": "7210.11.0000",
                    "product_description": "steel sheets",
                    "known_materials": None
                })
            data = json.loads(result)

            # Assert: Only steel returned
            assert data["materials_needed"] is True
            assert "steel" in data["applicable_materials"]
            assert "copper" not in data["applicable_materials"]
            assert "aluminum" not in data["applicable_materials"]
            assert len(data["applicable_materials"]) == 1

    def test_ensure_materials_all_three(self, tariff_app):
        """Verify when all three materials exist, all three are returned."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Setup: Add all three materials for a specific HTS
            for material, claim in [("copper", "9903.78.01"), ("steel", "9903.80.01"), ("aluminum", "9903.85.08")]:
                db.session.add(Section232Material(
                    hts_8digit="84733051",
                    material=material,
                    claim_code=claim,
                    disclaim_code=claim.replace(".01", ".02").replace(".08", ".09"),
                    duty_rate=0.25
                ))
            db.session.commit()

            # Call ensure_materials
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result = ensure_materials.invoke({
                    "hts_code": "8473.30.5100",
                    "product_description": "computer parts",
                    "known_materials": None
                })
            data = json.loads(result)

            # Assert: All three returned
            assert data["materials_needed"] is True
            assert set(data["applicable_materials"]) == {"copper", "steel", "aluminum"}


class TestStackingGraphPassesMaterials:
    """Tests that the stacking graph correctly passes applicable_materials."""

    def test_check_materials_node_includes_applicable_materials(self, tariff_app):
        """Verify check_materials_node includes applicable_materials in output."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Setup: Add copper only
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            db.session.commit()

            # Mock state
            state = {
                "hts_code": "8544.42.9090",
                "product_description": "cable",
                "materials": None,
                "decisions": []
            }

            # Call check_materials_node with patched app
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.graphs.stacking_rag import check_materials_node
                result = check_materials_node(state)

            # Assert: applicable_materials is included
            assert result.get("materials_needed") is True or result.get("awaiting_user_input") is True
            assert "applicable_materials" in result, \
                "check_materials_node must include applicable_materials in output"
            assert "copper" in result["applicable_materials"]
            assert "steel" not in result["applicable_materials"]


class TestNoHardcodedMaterialLists:
    """Tests to ensure there are no hardcoded material lists in critical paths."""

    def test_ensure_materials_queries_database(self, tariff_app):
        """Verify ensure_materials queries the database, not a hardcoded list."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Empty database - should return no materials
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result1 = ensure_materials.invoke({
                    "hts_code": "8544.42.9090",
                    "product_description": "test",
                    "known_materials": None
                })
            data1 = json.loads(result1)
            assert data1["materials_needed"] is False, \
                "With empty database, no materials should be needed"

            # Add copper to database
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            db.session.commit()

            # Now should return copper
            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                result2 = ensure_materials.invoke({
                    "hts_code": "8544.42.9090",
                    "product_description": "test",
                    "known_materials": None
                })
            data2 = json.loads(result2)
            assert data2["materials_needed"] is True
            assert data2["applicable_materials"] == ["copper"], \
                "After adding copper to DB, only copper should be returned"

    def test_different_hts_different_materials(self, tariff_app):
        """Verify different HTS codes get different materials from database."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # HTS 1: Only copper
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            # HTS 2: Only steel
            db.session.add(Section232Material(
                hts_8digit="72101100",
                material="steel",
                claim_code="9903.80.01",
                disclaim_code="9903.80.02",
                duty_rate=0.25
            ))
            # HTS 3: Copper and aluminum
            db.session.add(Section232Material(
                hts_8digit="76061100",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            db.session.add(Section232Material(
                hts_8digit="76061100",
                material="aluminum",
                claim_code="9903.85.08",
                disclaim_code="9903.85.09",
                duty_rate=0.10
            ))
            db.session.commit()

            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials

                # Test HTS 1
                result1 = json.loads(ensure_materials.invoke({
                    "hts_code": "8544.42.9090",
                    "product_description": "test",
                    "known_materials": None
                }))
                assert set(result1["applicable_materials"]) == {"copper"}

                # Test HTS 2
                result2 = json.loads(ensure_materials.invoke({
                    "hts_code": "7210.11.0000",
                    "product_description": "test",
                    "known_materials": None
                }))
                assert set(result2["applicable_materials"]) == {"steel"}

                # Test HTS 3
                result3 = json.loads(ensure_materials.invoke({
                    "hts_code": "7606.11.0000",
                    "product_description": "test",
                    "known_materials": None
                }))
                assert set(result3["applicable_materials"]) == {"copper", "aluminum"}


class TestSuggestedQuestionDynamic:
    """Tests that the suggested question only mentions applicable materials."""

    def test_suggested_question_only_applicable_materials(self, tariff_app):
        """Verify suggested_question mentions only materials from database."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Material

        with tariff_app.app_context():
            # Add only copper
            db.session.add(Section232Material(
                hts_8digit="85444290",
                material="copper",
                claim_code="9903.78.01",
                disclaim_code="9903.78.02",
                duty_rate=0.25
            ))
            db.session.commit()

            with patch('app.chat.tools.stacking_tools.get_flask_app', return_value=tariff_app):
                from app.chat.tools.stacking_tools import ensure_materials
                result = ensure_materials.invoke({
                    "hts_code": "8544.42.9090",
                    "product_description": "test",
                    "known_materials": None
                })
            data = json.loads(result)

            question = data.get("suggested_question", "")
            assert "copper" in question.lower()
            assert "steel" not in question.lower(), \
                "Suggested question should NOT mention steel if not in database"
            assert "aluminum" not in question.lower(), \
                "Suggested question should NOT mention aluminum if not in database"
