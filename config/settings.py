from config.config_manager import load_settings


class Settings:
    def __init__(self):
        loaded_settings = load_settings()

        for key, value in loaded_settings.items():
            setattr(self, key, value)


settings = Settings()