"""
Priority Engine
---------------
Combines AI severity score, category weight, location sensitivity,
and community upvotes to compute a final priority score (0-100)
and classify issues into High / Medium / Low priority.
"""

CATEGORY_WEIGHTS = {
    'pothole': 25,
    'water_leakage': 28,
    'drainage': 26,
    'streetlight': 18,
    'traffic_signal': 30,
    'garbage': 15,
    'illegal_dumping': 20,
    'broken_sidewalk': 15,
    'graffiti': 8,
    'other': 10,
}


def compute_priority(category, severity_score, upvotes=0, description=""):
    """
    Final Priority Score = severity(55%) + category_risk(30%) + community(15%)
    """
    category_weight = CATEGORY_WEIGHTS.get(category, 10)

    # Normalize category weight to 0-100 scale
    category_score = min(100, category_weight * 3.3)

    # Community engagement boost (capped)
    community_score = min(100, upvotes * 5)

    # Keyword-based urgency boost from description
    urgency_keywords = ['urgent', 'danger', 'accident', 'children', 'hospital',
                         'school', 'major', 'severe', 'flooding', 'electric shock']
    keyword_boost = 0
    if description:
        desc_lower = description.lower()
        keyword_boost = sum(8 for kw in urgency_keywords if kw in desc_lower)
        keyword_boost = min(keyword_boost, 24)

    final_score = (severity_score * 0.55) + (category_score * 0.30) + (community_score * 0.15)
    final_score = min(100, final_score + keyword_boost)
    final_score = round(final_score, 2)

    if final_score >= 70:
        level = "High"
    elif final_score >= 40:
        level = "Medium"
    else:
        level = "Low"

    return final_score, level