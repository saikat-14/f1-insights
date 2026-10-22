"""Team colour lookup used by charts and tables (matches FastF1 and Jolpica team names)."""

# key: (display name, UI colour)
TEAMS = {
    "red_bull": ("Red Bull Racing", "#3671C6"), "racing_bulls": ("Racing Bulls", "#6692FF"),
    "ferrari": ("Ferrari", "#E8002D"), "mercedes": ("Mercedes", "#27F4D2"), "mclaren": ("McLaren", "#FF8000"),
    "aston_martin": ("Aston Martin", "#229971"), "alpine": ("Alpine", "#FF87BC"), "williams": ("Williams", "#64C4FF"),
    "haas": ("Haas", "#B6BABD"), "audi": ("Audi", "#F50537"), "cadillac": ("Cadillac", "#C0C6CC"),
    "sauber": ("Kick Sauber", "#52E252"), "generic": ("Team", "#9A9DA3"),
}


def team_key(team_name: str) -> str:
    t = str(team_name).lower().strip()
    if "racing bulls" in t or "alphatauri" in t or "toro rosso" in t or t in ("rb", "vcarb") or t.startswith("rb f1") \
            or "visa cash app" in t:
        return "racing_bulls"
    for needle, key in (("red bull", "red_bull"), ("ferrari", "ferrari"), ("mercedes", "mercedes"),
                        ("mclaren", "mclaren"), ("aston", "aston_martin"), ("alpine", "alpine"),
                        ("renault", "alpine"), ("williams", "williams"), ("haas", "haas"),
                        ("audi", "audi"), ("cadillac", "cadillac"), ("sauber", "sauber"), ("alfa", "sauber")):
        if needle in t:
            return key
    return "generic"


def team_style(team_name: str) -> dict:
    k = team_key(team_name)
    n, ui = TEAMS[k]
    return {"key": k, "name": str(team_name) if k == "generic" else n, "ui": ui}
