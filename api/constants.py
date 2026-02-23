"""
Shared API error messages and constants.
Use these for consistent user-facing errors when epic cannot be derived from story.
"""

# When epic/parent_key could not be derived (generic)
MSG_COULD_NOT_DERIVE_EPIC = (
    "Could not derive epic. Provide epic_key (or parent_key), or ensure the story has a parent epic in JIRA."
)

# When the story exists but has no parent in JIRA
MSG_STORY_HAS_NO_PARENT_EPIC = (
    "Story has no parent epic in JIRA. Provide epic_key (or parent_key) explicitly."
)
