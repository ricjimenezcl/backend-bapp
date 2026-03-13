def geo_grid(value: float, precision: int = 2) -> float:
    """
    Redondea coordenadas para cache geográfico
    precision=2 ≈ 1km
    """
    return round(value, precision)
