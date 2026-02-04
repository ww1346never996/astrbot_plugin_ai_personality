# config.py
import os
import json

class PluginConfig:
    def __init__(self, plugin_dir):
        self.config_path = os.path.join(plugin_dir, "config.json")
        self.default_config = {
            "openai_api_key": "sk-xxxx",
            "openai_base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o" 
        }
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.config_path):
            self._save(self.default_config)
            return self.default_config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return self.default_config

    def _save(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    @property
    def api_key(self): return self.data.get("openai_api_key")
    @property
    def base_url(self): return self.data.get("openai_base_url")
    @property
    def model(self): return self.data.get("model_name")