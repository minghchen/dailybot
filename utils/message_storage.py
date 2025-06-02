#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
消息存储模块
负责持久化存储微信消息，支持按时间窗口查询
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from loguru import logger
import threading


class MessageStorage:
    """消息存储类"""
    
    def __init__(self, db_path: str = "data/messages.db"):
        """
        初始化消息存储
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 线程锁，确保并发安全
        self.lock = threading.Lock()
        
        # 初始化数据库
        self._init_db()
        
        logger.info(f"消息存储初始化成功: {self.db_path}")
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT UNIQUE,
                    from_user TEXT,
                    to_user TEXT,
                    user_nickname TEXT,
                    group_name TEXT,
                    content TEXT,
                    msg_type TEXT,
                    url TEXT,
                    is_group BOOLEAN,
                    create_time INTEGER,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_create_time 
                ON messages(create_time)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_name 
                ON messages(group_name)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_nickname 
                ON messages(user_nickname)
            """)
            
            conn.commit()
    
    def save_message(self, msg: Dict[str, Any]):
        """
        保存消息到数据库
        
        Args:
            msg: 微信消息对象
        """
        try:
            with self.lock:
                # 提取消息信息
                msg_id = msg.get('MsgId', str(time.time()))
                from_user = msg.get('FromUserName', '')
                to_user = msg.get('ToUserName', '')
                user_nickname = msg.get('User', {}).get('NickName', '')
                content = msg.get('Text', '')
                msg_type = msg.get('Type', '')
                url = msg.get('Url', '')
                is_group = from_user.startswith('@@')
                create_time = msg.get('CreateTime', int(time.time()))
                
                # 群组名称
                group_name = ''
                if is_group:
                    group_name = msg.get('User', {}).get('NickName', '')
                
                # 序列化原始数据
                raw_data = json.dumps(msg, ensure_ascii=False)
                
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO messages 
                        (msg_id, from_user, to_user, user_nickname, group_name,
                         content, msg_type, url, is_group, create_time, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        msg_id, from_user, to_user, user_nickname, group_name,
                        content, msg_type, url, is_group, create_time, raw_data
                    ))
                    
                    conn.commit()
                    
                logger.debug(f"消息已保存: {msg_id} from {user_nickname}")
                
        except Exception as e:
            logger.error(f"保存消息失败: {e}", exc_info=True)
    
    def get_messages_in_time_window(self, target_time: int, 
                                   window_seconds: int = 60,
                                   group_name: Optional[str] = None,
                                   user_nickname: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取指定时间窗口内的消息
        
        Args:
            target_time: 目标时间戳
            window_seconds: 时间窗口（秒）
            group_name: 群组名称筛选
            user_nickname: 用户昵称筛选
            
        Returns:
            消息列表
        """
        try:
            start_time = target_time - window_seconds
            end_time = target_time + window_seconds
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 构建查询
                query = """
                    SELECT * FROM messages 
                    WHERE create_time >= ? AND create_time <= ?
                """
                params = [start_time, end_time]
                
                # 添加筛选条件
                if group_name:
                    query += " AND group_name = ?"
                    params.append(group_name)
                
                if user_nickname:
                    query += " AND user_nickname = ?"
                    params.append(user_nickname)
                
                query += " ORDER BY create_time ASC"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                # 转换为消息对象列表
                messages = []
                for row in rows:
                    try:
                        # 反序列化原始数据
                        raw_data = json.loads(row['raw_data'])
                        messages.append(raw_data)
                    except:
                        # 如果原始数据解析失败，构建基本消息对象
                        messages.append({
                            'MsgId': row['msg_id'],
                            'FromUserName': row['from_user'],
                            'ToUserName': row['to_user'],
                            'User': {'NickName': row['user_nickname']},
                            'Text': row['content'],
                            'Type': row['msg_type'],
                            'Url': row['url'],
                            'CreateTime': row['create_time']
                        })
                
                logger.info(f"获取到 {len(messages)} 条消息 (时间窗口: {window_seconds}秒)")
                return messages
                
        except Exception as e:
            logger.error(f"查询消息失败: {e}", exc_info=True)
            return []
    
    def get_recent_messages(self, hours: int = 24, 
                          group_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取最近的消息
        
        Args:
            hours: 最近多少小时
            group_name: 群组名称筛选
            
        Returns:
            消息列表
        """
        target_time = int(time.time())
        window_seconds = hours * 3600
        
        return self.get_messages_in_time_window(
            target_time=target_time,
            window_seconds=window_seconds,
            group_name=group_name
        )
    
    def cleanup_old_messages(self, days: int = 30):
        """
        清理旧消息
        
        Args:
            days: 保留多少天的消息
        """
        try:
            cutoff_time = int(time.time()) - (days * 24 * 3600)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM messages 
                    WHERE create_time < ?
                """, (cutoff_time,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
            logger.info(f"清理了 {deleted_count} 条旧消息")
            
        except Exception as e:
            logger.error(f"清理旧消息失败: {e}", exc_info=True)
    
    def get_message_count(self) -> int:
        """获取消息总数"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM messages")
                return cursor.fetchone()[0]
        except:
            return 0 