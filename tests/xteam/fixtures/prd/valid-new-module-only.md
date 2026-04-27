---
title: New recommendation widget (greenfield)
background: |
  We want to launch an independent recommendation widget in a new service,
  isolated from the existing feed.
goal: Ship a standalone rec widget with its own storage and API.
user_scenarios:
  - "User sees 'recommended for you' card below the feed."
features:
  - id: F1
    summary: Rec candidate generation service
    priority: P0
metrics:
  - "Rec CTR ≥ 8%"
out_of_scope:
  - Replacing existing feed ranker
involved_modules:
  - name: rec_widget
    kind: new
    touches_core_feature: false
business_type: content_social
---

# New Rec Widget
