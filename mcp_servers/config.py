"""
MCP Server Configuration

Environment variables and model settings for Gemini-powered HTS verification.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Gemini API Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Model Selection
# - Test: Free tier for development and bulk verification
# - Production: Paid tier with thinking mode for user-facing queries
# Available models: gemini-2.5-flash, gemini-2.5-pro, gemini-3-pro-preview
MODELS = {
    "test": "gemini-2.5-flash",           # Fast, cost-effective for testing
    "production": "gemini-3-pro-preview"  # Production with thinking mode
}

# Thinking Mode Budget (for Gemini Pro models)
# Higher budget = more thorough reasoning, slower response
THINKING_BUDGET = {
    "low": 1024,
    "medium": 8192,
    "high": 16384    # High thinking mode for complex verification
}

# Cache Settings
CACHE_TTL_DAYS = 30  # Re-verify after 30 days if not manually verified

# Rate Limiting
MAX_FORCE_SEARCHES_PER_HOUR = 10

# Search Configuration
SEARCH_CONFIG = {
    "enabled": True,
    "google_search_grounding": True,  # Use Google Search for grounding
}
