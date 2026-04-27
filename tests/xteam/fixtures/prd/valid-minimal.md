---
title: Add comment reactions
background: |
  Currently users can only "like" comments. We want 6 emoji reactions
  to match peer products and increase engagement in threads.
goal: Ship 6 reactions (like / love / laugh / wow / sad / angry) with content-safety gating within one sprint.
user_scenarios:
  - "User long-presses a comment and picks a reaction."
  - "Author sees per-reaction counts on their comments."
features:
  - id: F1
    summary: Reaction picker UI on comment cards
    priority: P0
  - id: F2
    summary: Aggregated count display
    priority: P1
metrics:
  - "Reaction DAU ratio ≥ 15% among commenters"
  - "Reaction API p99 ≤ 100ms"
out_of_scope:
  - Custom emoji uploads
  - Reactions on replies (handled in a later phase)
involved_modules:
  - name: comment
    kind: legacy
    touches_core_feature: true
  - name: feed
    kind: legacy
    touches_core_feature: false
business_type: content_social
---

# Add Comment Reactions

## Background

...
