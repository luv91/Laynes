"""
Unit tests for the Corpus model.

Tests:
- CRUD operations
- is_active filtering
- Version tracking
- Unique name constraint
"""

import pytest
from datetime import datetime


class TestCorpusModel:
    """Test Corpus model basic operations."""

    def test_create_corpus(self, app):
        """Test creating a new corpus."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(
                name="test_trade_v1",
                description="Trade compliance documents",
                is_active=True,
                version="v1.0"
            )

            assert corpus.id is not None
            assert corpus.name == "test_trade_v1"
            assert corpus.description == "Trade compliance documents"
            assert corpus.is_active is True
            assert corpus.version == "v1.0"
            assert corpus.created_at is not None

    def test_corpus_as_dict(self, app):
        """Test as_dict method returns correct structure."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(
                name="dict_test",
                description="Test description",
                is_active=True,
                version="v2"
            )

            result = corpus.as_dict()

            assert "id" in result
            assert result["name"] == "dict_test"
            assert result["description"] == "Test description"
            assert result["is_active"] is True
            assert result["version"] == "v2"
            assert "created_at" in result

    def test_corpus_unique_name(self, app):
        """Test that corpus names must be unique."""
        from app.web.db.models import Corpus
        from sqlalchemy.exc import IntegrityError

        with app.app_context():
            Corpus.create(name="unique_test", is_active=True)

            with pytest.raises(IntegrityError):
                Corpus.create(name="unique_test", is_active=True)

    def test_corpus_optional_fields(self, app):
        """Test corpus can be created with minimal required fields."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(name="minimal_corpus")

            assert corpus.name == "minimal_corpus"
            assert corpus.description is None
            assert corpus.version is None
            assert corpus.is_active is True  # Default value


class TestCorpusActiveFiltering:
    """Test is_active filtering functionality."""

    def test_get_active_corpora(self, app):
        """Test getting only active corpora."""
        from app.web.db.models import Corpus

        with app.app_context():
            Corpus.create(name="active1", is_active=True)
            Corpus.create(name="active2", is_active=True)
            Corpus.create(name="inactive1", is_active=False)

            active = Corpus.get_active()

            assert len(active) == 2
            names = [c.name for c in active]
            assert "active1" in names
            assert "active2" in names
            assert "inactive1" not in names

    def test_deactivate_corpus(self, app):
        """Test deactivating a corpus."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(name="to_deactivate", is_active=True)

            corpus.is_active = False
            corpus.save()

            refreshed = Corpus.find_by(id=corpus.id)
            assert refreshed.is_active is False

    def test_no_active_corpora(self, app):
        """Test empty list when no active corpora."""
        from app.web.db.models import Corpus

        with app.app_context():
            Corpus.create(name="only_inactive", is_active=False)

            active = Corpus.get_active()

            assert len(active) == 0


class TestCorpusVersioning:
    """Test version tracking functionality."""

    def test_version_can_be_updated(self, app):
        """Test updating corpus version."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(name="versioned", version="v1.0")

            corpus.version = "v1.1"
            corpus.save()

            refreshed = Corpus.find_by(id=corpus.id)
            assert refreshed.version == "v1.1"

    def test_multiple_versions_different_names(self, app):
        """Test multiple corpus versions with different names."""
        from app.web.db.models import Corpus

        with app.app_context():
            v1 = Corpus.create(name="trade_v1", version="v1", is_active=False)
            v2 = Corpus.create(name="trade_v2", version="v2", is_active=True)

            assert v1.version == "v1"
            assert v2.version == "v2"

            # Only v2 should be active
            active = Corpus.get_active()
            assert len(active) == 1
            assert active[0].name == "trade_v2"


class TestCorpusLookup:
    """Test corpus lookup methods."""

    def test_get_by_name(self, app):
        """Test finding corpus by name."""
        from app.web.db.models import Corpus

        with app.app_context():
            Corpus.create(name="findable", description="Can be found")

            found = Corpus.get_by_name("findable")

            assert found is not None
            assert found.description == "Can be found"

    def test_get_by_name_not_found(self, app):
        """Test get_by_name returns None for missing corpus."""
        from app.web.db.models import Corpus

        with app.app_context():
            result = Corpus.get_by_name("nonexistent")
            assert result is None

    def test_corpus_repr(self, app):
        """Test corpus string representation."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.create(name="repr_test", version="v3")

            repr_str = repr(corpus)
            assert "repr_test" in repr_str
            assert "v3" in repr_str


class TestConversationCorpusTracking:
    """Test corpus_name field on Conversation model."""

    def test_conversation_stores_corpus_name(self, app, test_user):
        """Test conversation can store corpus_name."""
        from app.web.db.models import Conversation

        with app.app_context():
            conv = Conversation.create(
                user_id=test_user["id"],
                mode="multi_doc",
                corpus_name="trade_compliance_v1"
            )

            assert conv.corpus_name == "trade_compliance_v1"

    def test_conversation_as_dict_includes_corpus(self, app, test_user):
        """Test as_dict includes corpus_name."""
        from app.web.db.models import Conversation

        with app.app_context():
            conv = Conversation.create(
                user_id=test_user["id"],
                mode="multi_doc",
                corpus_name="my_corpus"
            )

            result = conv.as_dict()
            assert "corpus_name" in result
            assert result["corpus_name"] == "my_corpus"

    def test_corpus_name_nullable(self, app, test_user):
        """Test corpus_name can be None for user_pdf mode."""
        from app.web.db.models import Conversation

        with app.app_context():
            conv = Conversation.create(
                user_id=test_user["id"],
                mode="user_pdf"
            )

            assert conv.corpus_name is None
