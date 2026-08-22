# E2 multi-hop QA corpus — imaginary entity directory (local, deterministic)
# Fields: name, role, site (plant), manager, equipment, installed_year, status
# All entities are FICTIONAL. Questions in e2_quality_battery.py reference
# relations transitively (manager-of-manager, site-of-equipment, etc.).

ENTITIES = [
    {"name": "Aria Vance",    "role": "plant director",   "site": "Northgate Plant", "manager": None,           "equipment": "turbine T-11",  "year": 2019, "status": "active"},
    {"name": "Bo Lindqvist",  "role": "line lead",        "site": "Northgate Plant", "manager": "Aria Vance",   "equipment": "press P-3",     "year": 2021, "status": "active"},
    {"name": "Cleo Martens",  "role": "technician",       "site": "Northgate Plant", "manager": "Bo Lindqvist", "equipment": "press P-3",     "year": 2022, "status": "active"},
    {"name": "Dario Kohn",    "role": "technician",       "site": "Eastfold Plant",  "manager": "Elin Park",    "equipment": "kiln K-7",     "year": 2018, "status": "retired"},
    {"name": "Elin Park",     "role": "plant director",   "site": "Eastfold Plant",  "manager": None,           "equipment": "kiln K-7",     "year": 2018, "status": "active"},
    {"name": "Fay Oduya",     "role": "line lead",        "site": "Eastfold Plant",  "manager": "Elin Park",    "equipment": "conveyor C-2", "year": 2020, "status": "active"},
    {"name": "Gus Ferreira",  "role": "technician",       "site": "Eastfold Plant",  "manager": "Fay Oduya",    "equipment": "conveyor C-2", "year": 2023, "status": "active"},
    {"name": "Hana Ito",      "role": "inspector",        "site": "Westquay Plant",  "manager": "Ivo Brandt",   "equipment": "sensor S-9",   "year": 2017, "status": "active"},
    {"name": "Ivo Brandt",    "role": "plant director",   "site": "Westquay Plant",  "manager": None,           "equipment": "sensor S-9",   "year": 2017, "status": "active"},
    {"name": "Jae Solano",    "role": "technician",       "site": "Westquay Plant",  "manager": "Ivo Brandt",   "equipment": "sensor S-9",   "year": 2019, "status": "retired"},
    {"name": "Kira Blum",     "role": "line lead",        "site": "Westquay Plant",  "manager": "Ivo Brandt",   "equipment": "press P-8",    "year": 2024, "status": "active"},
    {"name": "Lior Ashkar",   "role": "technician",       "site": "Southmere Plant", "manager": "Mira Deel",    "equipment": "turbine T-4",  "year": 2016, "status": "active"},
    {"name": "Mira Deel",     "role": "plant director",   "site": "Southmere Plant", "manager": None,           "equipment": "turbine T-4",  "year": 2016, "status": "active"},
    {"name": "Nils Okonkwo",  "role": "inspector",        "site": "Southmere Plant", "manager": "Mira Deel",    "equipment": "kiln K-2",     "year": 2021, "status": "active"},
    {"name": "Oda Ferrand",   "role": "technician",       "site": "Southmere Plant", "manager": "Mira Deel",    "equipment": "kiln K-2",     "year": 2022, "status": "retired"},
    {"name": "Pia Sorokin",   "role": "line lead",        "site": "Southmere Plant", "manager": "Mira Deel",    "equipment": "conveyor C-5", "year": 2023, "status": "active"},
    {"name": "Quinn Harada",  "role": "technician",       "site": "Southmere Plant", "manager": "Pia Sorokin",  "equipment": "conveyor C-5", "year": 2024, "status": "active"},
    {"name": "Ravi Mensah",   "role": "inspector",        "site": "Northgate Plant", "manager": "Aria Vance",   "equipment": "turbine T-11", "year": 2020, "status": "active"},
    {"name": "Sofia Rask",    "role": "technician",       "site": "Eastfold Plant",  "manager": "Fay Oduya",    "equipment": "conveyor C-2", "year": 2021, "status": "retired"},
    {"name": "Tomas Vela",    "role": "inspector",        "site": "Eastfold Plant",  "manager": "Elin Park",    "equipment": "kiln K-7",     "year": 2019, "status": "active"},
]

def render_directory():
    lines = ["Company directory (all names fictional):", ""]
    for e in ENTITIES:
        mgr = e["manager"] if e["manager"] else "(top of hierarchy)"
        lines.append(
            f"{e['name']} — {e['role']} at {e['site']}; manager: {mgr}; "
            f"primary equipment: {e['equipment']} (installed {e['year']}); status: {e['status']}.")
    return "\n".join(lines)

if __name__ == "__main__":
    print(render_directory())
