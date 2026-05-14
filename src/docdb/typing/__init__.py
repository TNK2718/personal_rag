"""Runtime type registry and field-spec validation for the property-graph model.

Stage 1 introduces ``entity_types`` / ``relation_types`` tables whose
``fields_schema`` column is a JSON ``FieldSpec[]``. The pure-Python helpers
in this package parse and validate those schemas, and build dynamic Pydantic
models that the LLM extraction layer can pass to ``instructor``.
"""
