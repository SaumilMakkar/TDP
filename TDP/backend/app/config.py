class Settings:
    APP_NAME = "PA Multi-Agent System"

settings = Settings()

# Clinical Agent Stage C Scoring Configuration
CLINICAL_WEIGHTS = {
    "ingredient":0.55 ,  # Ingredient similarity/therapeutic equivalence
    "safety":0.45 ,      # Patient safety score
}

# Filtering thresholds
MIN_COMPOSITE_SCORE = 0.6  # Minimum composite score to include candidate
TOP_K = 3                  # Maximum number of top alternatives to return
