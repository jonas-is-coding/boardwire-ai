"""Growth automation for the Boardwire Bluesky account.

Three credential-gated, reviewable operations:

* ``follower``  — a paced, permanent, idempotent follow drip fed by
  ``discover`` (four weighted graph channels, re-hydrated before filtering).
* ``profile``   — display name + bio merged onto the live profile record, and
  a pinned intro thread that explains the pipeline (the engineering project is
  the positioning; the news is its output).
* ``settings``  — ``config/growth.json`` loader.

Design rule enforced by test: there is **no unfollow / delete path** anywhere
in this package. Follows are permanent. Scoring measures graph relevance, never
follow-back likelihood — the latter is follow/unfollow thinking with an extra
step.

Replies stay human. The reply digest (``src/feedback/reply_digest.py``) only
drafts; a person posts.
"""
