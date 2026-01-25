"""
Application Services

Business logic services used across the application.

Note: Imports are lazy to avoid circular import issues.
Use explicit imports from submodules when needed:
    from app.services.freshness import get_freshness_service
    from app.services.confidence_service import get_confidence_service
    from app.services.section301_engine import evaluate_section_301
"""


def __getattr__(name):
    """Lazy import to avoid circular imports."""
    if name in ('FreshnessService', 'get_freshness_service'):
        from app.services.freshness import FreshnessService, get_freshness_service
        return FreshnessService if name == 'FreshnessService' else get_freshness_service

    if name in ('HTSValidator', 'HTSValidationResult', 'get_hts_validator'):
        from app.services.hts_validator import HTSValidator, HTSValidationResult, get_hts_validator
        if name == 'HTSValidator':
            return HTSValidator
        elif name == 'HTSValidationResult':
            return HTSValidationResult
        else:
            return get_hts_validator

    if name in ('ConfidenceService', 'ConfidenceLevel', 'DataSourceType',
                'ProgramConfidence', 'StackingConfidenceResult', 'get_confidence_service'):
        from app.services.confidence_service import (
            ConfidenceService, ConfidenceLevel, DataSourceType,
            ProgramConfidence, StackingConfidenceResult, get_confidence_service
        )
        mapping = {
            'ConfidenceService': ConfidenceService,
            'ConfidenceLevel': ConfidenceLevel,
            'DataSourceType': DataSourceType,
            'ProgramConfidence': ProgramConfidence,
            'StackingConfidenceResult': StackingConfidenceResult,
            'get_confidence_service': get_confidence_service,
        }
        return mapping[name]

    # Section 301 Trade Compliance Engine
    if name in ('Section301Engine', 'Section301Result', 'evaluate_section_301',
                'get_section_301_rate', 'get_section_301_engine'):
        from app.services.section301_engine import (
            Section301Engine, Section301Result, evaluate_section_301,
            get_section_301_rate, get_section_301_engine
        )
        mapping = {
            'Section301Engine': Section301Engine,
            'Section301Result': Section301Result,
            'evaluate_section_301': evaluate_section_301,
            'get_section_301_rate': get_section_301_rate,
            'get_section_301_engine': get_section_301_engine,
        }
        return mapping[name]

    raise AttributeError(f"module 'app.services' has no attribute '{name}'")
