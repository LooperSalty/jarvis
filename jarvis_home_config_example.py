"""Exemple de config Home Assistant (generique, sans donnees personnelles).

Copie ce fichier vers `jarvis_home_config.py` (ignore par git) et remplace les
entity_id par les tiens. Chaque cle est un mot-cle vocal ; chaque valeur est un
entity_id Home Assistant (visible dans Outils de developpement > Etats).

Si `jarvis_home_config.py` est absent, Jarvis utilise ces exemples par defaut.
"""

# Lumieres : "allume le salon", "eteins la cuisine"...
PIECES_LUMIERES = {
    "salon"            : "light.salon",
    "cuisine"          : "light.cuisine",
    "bureau"           : "light.bureau",
    "chambre"          : "light.chambre",
    "toutes"           : "light.all",
    "tout"             : "light.all",
}

# Prises commandables
PIECES_PRISES = {
    "salon"   : "switch.prise_salon",
    "bureau"  : "switch.prise_bureau",
    "cuisine" : "switch.prise_cuisine",
}

# Capteurs de temperature (+ capteurs divers : consommation, etc.)
PIECES_CAPTEURS = {
    "salon"        : "sensor.salon_temperature",
    "chambre"      : "sensor.chambre_temperature",
    "bureau"       : "sensor.bureau_temperature",
    "exterieur"    : "sensor.temperature_exterieure",
    "dehors"       : "sensor.temperature_exterieure",
    "consommation" : "sensor.puissance_apparente",
}

# Capteurs d'humidite
PIECES_HUMIDITE = {
    "bureau"    : "sensor.bureau_humidite",
}

# Tarifs electricite (EUR/kWh) par periode tarifaire
HA_TARIFS = { "p1": 0.1296, "p2": 0.1603, "p3": 0.1486, "p4": 0.1894, "p5": 0.1568, "p6": 0.7562 }

# Conso energie par appareil : "consommation de la tele ce mois"
APPAREILS_ENERGIE = {
    "tv"              : "sensor.prise_tv_mensuel",
    "salon"           : "sensor.prise_salon_mensuel",
    "lave-vaisselle"  : "sensor.prise_lave_vaisselle_mensuel",
    "bureau"          : "sensor.bureau_mensuel",
}

# Suivi de batterie : "batterie de mon telephone"
APPAREILS_BATTERIE = {
    "mon telephone"     : "sensor.telephone_battery_level",
    "tablette"          : "sensor.tablette_battery_level",
    "montre"            : "sensor.montre_battery_level",
    "aspirateur"        : "sensor.aspirateur_batterie",
    "camera jardin"     : "sensor.camera_jardin_battery_percentage",
}
