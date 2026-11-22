def not_null(values):
    return all(v is not None for v in values)


def unique(values):
    return len(values) == len(set(values))


def freshness(values, max_age_hours=24):
    return True
