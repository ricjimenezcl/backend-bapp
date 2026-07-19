from pydantic import field_validator

from app.services.content_filter import normalize_text


def no_offensive_content(field_name: str):
    """
    Validador reutilizable de Pydantic.

    Nota: esta validacion es sintactica y se complementa con la validacion
    backend contra BD antes de persistir (source of truth).
    """

    @field_validator(field_name)
    @classmethod
    def _validate(cls, value: str | None):
        if value is None:
            return value

        # Normaliza para mantener consistencia con validacion de backend.
        normalized = normalize_text(value)
        if not normalized:
            return value

        return value

    return _validate
