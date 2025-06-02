#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置加载器
负责加载和验证配置文件
"""

import json
import os
from pathlib import Path
from typing import Dict, Any
from loguru import logger


class ConfigLoader:
    """配置加载器"""
    
    @staticmethod
    def load(config_path: Path) -> Dict[str, Any]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 验证配置
            ConfigLoader._validate_config(config)
            
            # 处理路径
            ConfigLoader._process_paths(config)
            
            # 设置默认值
            ConfigLoader._set_defaults(config)
            
            return config
            
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise Exception(f"加载配置文件失败: {e}")
    
    @staticmethod
    def _validate_config(config: Dict[str, Any]):
        """验证配置的必要字段"""
        required_fields = {
            'openai': ['api_key'],
            'obsidian': ['vault_path'],
            'wechat': []
        }
        
        for section, fields in required_fields.items():
            if section not in config:
                raise ValueError(f"配置缺少必要部分: {section}")
            
            for field in fields:
                if field not in config[section]:
                    raise ValueError(f"配置缺少必要字段: {section}.{field}")
                
                # 检查API Key是否为占位符
                if field == 'api_key' and config[section][field] == 'YOUR_OPENAI_API_KEY':
                    raise ValueError("请在配置文件中设置有效的 OpenAI API Key")
    
    @staticmethod
    def _process_paths(config: Dict[str, Any]):
        """处理配置中的路径"""
        # 处理Obsidian vault路径
        if 'obsidian' in config and 'vault_path' in config['obsidian']:
            vault_path = config['obsidian']['vault_path']
            # 展开用户目录
            vault_path = os.path.expanduser(vault_path)
            # 转换为绝对路径
            vault_path = os.path.abspath(vault_path)
            config['obsidian']['vault_path'] = vault_path
    
    @staticmethod
    def _set_defaults(config: Dict[str, Any]):
        """设置默认值"""
        # OpenAI默认值
        openai_defaults = {
            'model': 'gpt-4o-mini',
            'temperature': 0.7,
            'max_tokens': 2000,
            'proxy': ''
        }
        for key, value in openai_defaults.items():
            if key not in config['openai']:
                config['openai'][key] = value
        
        # 微信默认值
        wechat_defaults = {
            'single_chat_prefix': ['bot', '@bot'],
            'single_chat_reply_prefix': '[Bot] ',
            'group_chat_prefix': ['@bot'],
            'group_chat_reply_prefix': '',
            'group_name_white_list': ['ALL_GROUP'],
            'nick_name_black_list': []
        }
        for key, value in wechat_defaults.items():
            if key not in config['wechat']:
                config['wechat'][key] = value
        
        # 内容提取默认值
        if 'content_extraction' not in config:
            config['content_extraction'] = {}
        
        extraction_defaults = {
            'context_time_window': 60,
            'auto_extract_enabled': True,
            'extract_types': ['wechat_article', 'bilibili_video', 'arxiv_paper', 'web_link'],
            'silent_mode': True
        }
        for key, value in extraction_defaults.items():
            if key not in config['content_extraction']:
                config['content_extraction'][key] = value
        
        # RAG默认值
        if 'rag' not in config:
            config['rag'] = {}
        
        rag_defaults = {
            'enabled': True,
            'embedding_model': 'text-embedding-ada-002',
            'chunk_size': 1000,
            'chunk_overlap': 200,
            'top_k': 5,
            'similarity_threshold': 0.7
        }
        for key, value in rag_defaults.items():
            if key not in config['rag']:
                config['rag'][key] = value
        
        # 系统默认值
        if 'system' not in config:
            config['system'] = {}
        
        system_defaults = {
            'log_level': 'INFO',
            'message_queue_size': 100,
            'auto_save_interval': 300,
            'timezone': 'Asia/Shanghai'
        }
        for key, value in system_defaults.items():
            if key not in config['system']:
                config['system'][key] = value 