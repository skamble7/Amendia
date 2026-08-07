# app/contracts — DOMAIN payload contracts local to the stub generator (ADR-049).
# These are producer-side envelope shapes (wire exception, dine-in order ticket); the platform
# lib amendia_contracts holds only GENERIC platform contracts. The runtime never imports these —
# it validates a trigger against the pack's declared schema (ADR-047 D1).
