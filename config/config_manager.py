import json
import os

from config.defaults import DEFAULT_SETTINGS


SETTINGS_PATH = "config/settings.json"


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_PATH, "r") as file:
            user_settings = json.load(file)
    except json.JSONDecodeError:
        user_settings = {}

    settings = DEFAULT_SETTINGS.copy()
    settings.update(user_settings)

    return settings


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)

    with open(SETTINGS_PATH, "w") as file:
        json.dump(settings, file, indent=4)


def reset_settings():
    save_settings(DEFAULT_SETTINGS)
    return DEFAULT_SETTINGS.copy()