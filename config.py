# config.py
# -*- coding: utf-8 -*-
import os
import json

class PluginConfig:
    def __init__(self, plugin_dir):
        self.config_path = os.path.join(plugin_dir, "config.json")
        self.default_config = {
            "openai_api_key": "sk-xxxx",
            "openai_base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o",
            "stt_api_key": "",
            "stt_base_url": "",
            "stt_model": ""
        }
        self.data = self._load()

    def _load(self):
        # 1. ����ļ����ڣ��ȼ����ļ����������Ϊ����
        file_data = self.default_config.copy()
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    file_data.update(json.load(f))
            except:
                pass
        else:
            # ����ļ������ڣ�����Ĭ���ļ�
            self._save(self.default_config)
        
        return file_data

    def _save(self, data):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # === �����޸ģ����ȶ�ȡ�������� ===
    @property
    def api_key(self): 
        # ���ȶ��������� SAKIKO_OPENAI_KEY������������ļ�����
        return os.getenv("SAKIKO_OPENAI_KEY") or self.data.get("openai_api_key")

    @property
    def base_url(self): 
        return os.getenv("SAKIKO_OPENAI_URL") or self.data.get("openai_base_url")

    @property
    def model(self): 
        return os.getenv("SAKIKO_MODEL_NAME") or self.data.get("model_name")
    
    @property
    def stt_key(self): 
        return os.getenv("SAKIKO_STT_KEY") or self.data.get("stt_api_key", "")

    @property
    def stt_url(self): 
        return os.getenv("SAKIKO_STT_URL") or self.data.get("stt_base_url", "")

    @property
    def stt_model(self): 
        return os.getenv("SAKIKO_STT_MODEL") or self.data.get("stt_model", "")