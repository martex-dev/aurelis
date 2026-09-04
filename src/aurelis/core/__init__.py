"""Identity, time, canonical encoding, configuration and shared vocabularies.

The bottom layer. Nothing here knows about the corporation, the database, or
any model provider — which is what lets everything above it depend on this
without circularity.
"""
