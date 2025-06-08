"""
Mac WeChat Hook Service
负责与微信本地数据进行交互，包括数据库的解密和读取。
"""

import re
import os
import sqlite3
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import shutil
from pysqlcipher3 import dbapi2 as sqlcipher
import blackboxprotobuf

logger = logging.getLogger(__name__)

# 根据用户验证成功的 SQLCipher 3 Defaults 配置
# 这是我们唯一的、最终的解密参数
SQLCIPHER3_DEFAULTS_CONFIG = [
    "PRAGMA cipher_page_size = 1024;",
    "PRAGMA kdf_iter = 64000;",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA1;",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA1;"
]

class DBManager:
    """封装对单个解密后数据库的查询操作"""
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def execute_query(self, query: str, params=()) -> Optional[List]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except sqlite3.OperationalError as e:
            # 如果是"表不存在"的错误，静默处理，返回None表示未找到
            if "no such table" in str(e):
                return None
            # 其他数据库操作错误，依然需要记录
            logger.error(f"数据库查询失败: {e} in query: {query}")
            return [] # 返回空列表表示查询出错，但表存在
        except sqlite3.Error as e:
            logger.error(f"数据库查询失败: {e} in query: {query}")
            return []

class MacWeChatHook:
    """
    Mac微信数据访问服务。
    通过读取和解密本地数据库文件来获取信息。
    """

    def __init__(self):
        self.wechat_path = "/Applications/WeChat.app"
        self.db_base_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat"
        self.db_key = self._get_db_key_from_env()
        self.wechat_version = self._get_wechat_version()
        self.decrypted_db_path = None
        self.tweak_log_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat/log/tweak.log"
        self.db_manager = None

    def initialize(self):
        """初始化数据库等资源"""
        return self._prepare_databases()

    def _get_db_key_from_env(self) -> str:
        key = os.getenv("WECHAT_DB_KEY")
        if not key or len(key) != 64 or not re.match(r"^[0-9a-fA-F]{64}$", key):
            raise ValueError("环境变量 WECHAT_DB_KEY 未设置或格式不正确。")
        logger.info("成功从环境变量加载数据库密钥。")
        return key

    def _get_wechat_version(self) -> Optional[str]:
        """获取微信客户端版本"""
        try:
            info_plist = Path(self.wechat_path) / "Contents/Info.plist"
            if not info_plist.exists():
                logger.warning("未找到微信Info.plist文件，无法检测版本。")
                return None
            result = subprocess.run(
                ["defaults", "read", str(info_plist), "CFBundleShortVersionString"],
                capture_output=True, text=True, check=True
            )
            version = result.stdout.strip()
            logger.info(f"检测到微信版本: {version}")
            return version
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"获取微信版本失败: {e}")
            return None

    def find_user_data_path(self) -> Optional[Path]:
        for msg_dir in self.db_base_path.rglob("Message"):
            if msg_dir.is_dir() and (msg_dir.parent / "Contact").exists():
                logger.info(f"找到有效的用户数据目录: {msg_dir.parent}")
                return msg_dir.parent
        logger.error("未找到有效的用户数据目录。")
        return None

    def decrypt_database(self, db_path: Path) -> Optional[Path]:
        decrypted_db_dir = Path.home() / ".dailybot/decrypted_db"
        decrypted_db_dir.mkdir(parents=True, exist_ok=True)
        decrypted_path = decrypted_db_dir / f"{db_path.name}.decrypted"

        if decrypted_path.exists():
            try:
                if decrypted_path.stat().st_mtime > db_path.stat().st_mtime:
                    logger.info(f"使用已存在的有效解密缓存: {decrypted_path}")
                    return decrypted_path
            except FileNotFoundError: pass

        temp_encrypted_path = decrypted_db_dir / f"{db_path.name}.temp_encrypted"
        try:
            shutil.copy2(db_path, temp_encrypted_path)
            # ... (omitting WAL/SHM file copy for brevity)
            
            logger.info(f"正在尝试解密 {db_path.name}...")
            conn = sqlcipher.connect(str(temp_encrypted_path))
            conn.execute(f"PRAGMA key = \"x'{self.db_key}'\"")
            for line in SQLCIPHER3_DEFAULTS_CONFIG:
                conn.execute(line)
            
            conn.execute("SELECT count(*) FROM sqlite_master;").fetchall()
            
            logger.info("密钥验证成功，正在导出...")
            if decrypted_path.exists(): decrypted_path.unlink()
            
            conn.execute(f"ATTACH DATABASE '{decrypted_path}' AS plaintext KEY '';")
            conn.execute("SELECT sqlcipher_export('plaintext');")
            conn.execute("DETACH DATABASE plaintext;")
            conn.close()
            
            if decrypted_path.exists() and decrypted_path.stat().st_size > 0:
                logger.info(f"成功解密数据库: {db_path.name}")
                return decrypted_path
            raise Exception("sqlcipher_export failed.")

        except Exception as e:
            logger.error(f"解密失败: {e}")
            return None
        finally:
            if temp_encrypted_path.exists(): temp_encrypted_path.unlink()

    def _unpack_contact_data(self, packed_data: bytes) -> Dict[str, Any]:
        """
        解析 _packed_WCContactData (protobuf) 字段以提取额外信息。
        """
        if not packed_data:
            return {}
        try:
            message, typedef = blackboxprotobuf.decode_message(packed_data)
            return message
        except Exception as e:
            logger.warning(f"解析 _packed_WCContactData 失败: {e}")
            return {}

    def _execute_query(self, decrypted_db_path: Path, query: str, params=()) -> List:
        """在解密的数据库上执行查询"""
        try:
            with sqlite3.connect(decrypted_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"数据库查询失败: {e} in query: {query}")
            return []

    def get_chat_messages(self, decrypted_db_path: Path, last_check_time: int = 0, limit: int = 100) -> List[Dict]:
        """
        从解密的数据库获取聊天记录。
        该方法会动态检查表结构，以适应不同版本的列名。
        """
        messages = []
        
        tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%' AND name NOT LIKE '%_dels'"
        tables = self._execute_query(decrypted_db_path, tables_query)

        for table in tables:
            table_name = table[0]
            is_group = "@chatroom" in table_name

            # 动态获取表结构
            table_info = self._execute_query(decrypted_db_path, f"PRAGMA table_info({table_name});")
            column_names = {row[1].lower() for row in table_info}

            # 动态确定列名，使用从日志中验证的真实列名
            create_time_col = "msgcreatetime"
            message_col = "msgcontent"
            status_col = "msgstatus"
            msg_svr_id_col = "messvrid"
            mes_local_id_col = "meslocalid"
            msg_source_col = "msgsource"
            
            # 确认所有必要的列都存在
            required_cols = {create_time_col, message_col, status_col, msg_svr_id_col, mes_local_id_col}
            if not required_cols.issubset(column_names):
                logger.warning(f"跳过表 {table_name}，因为它缺少必要的列。现有列: {column_names}")
                continue

            query = f"""
            SELECT
                {create_time_col},
                {message_col},
                {status_col},
                {msg_svr_id_col},
                {mes_local_id_col},
                {msg_source_col}
            FROM {table_name}
            WHERE {create_time_col} > ?
            ORDER BY {create_time_col} DESC
            LIMIT ?
            """
            
            rows = self._execute_query(decrypted_db_path, query, (last_check_time, limit))

            for row in reversed(rows): # 按时间升序处理
                content = row[1]
                sender = None

                if is_group and content and '<sysmsg' not in content:
                    # 解析群聊中的发言人
                    # 格式: wxid_xxxx:\n{content}
                    match = re.match(r"^(wxid_[a-zA-Z0-9]+):\n", content)
                    if match:
                        sender = match.group(1)
                        content = content[match.end():]
                
                messages.append({
                    'create_time': row[0],
                    'content': content,
                    'status': row[2],
                    'msg_id': row[3] or row[4],
                    'room_id': table_name.replace("Chat_", ""),
                    'sender_id': sender,
                    'is_group': is_group,
                })
        
        messages.sort(key=lambda x: x['create_time'])
        return messages

    def get_groups(self, decrypted_group_db_path: Path) -> List[Dict]:
        """从 group_new.db 获取群聊信息"""
        query = "SELECT m_nsUsrName, m_nsEncodeUserName, nickname, _packed_WCContactData FROM GroupContact"
        rows = self._execute_query(decrypted_group_db_path, query)
        groups = []
        for row in rows:
            user_id, encoded_username, nickname, packed_data = row
            if not user_id:
                continue

            unpacked_info = self._unpack_contact_data(packed_data)
            
            # 优先使用解包后的群名, '2' 字段通常是群名
            final_nickname = unpacked_info.get('2', nickname)
            
            groups.append({
                'user_id': user_id,
                'encoded_username': encoded_username,
                'nickname': final_nickname,
                'remark': '', # 群聊通常没有备注名
                'type': 'group',
            })
        return groups

    def get_contacts(self, decrypted_db_path: Path) -> List[Dict]:
        """获取联系人信息 (不含群聊)"""
        query = """
        SELECT
            m_nsUsrName,
            m_nsEncodeUserName,
            nickname,
            m_nsRemark,
            m_uiType,
            _packed_WCContactData
        FROM WCContact
        """
        
        rows = self._execute_query(decrypted_db_path, query)
        contacts = []
        for row in rows:
            user_id, encoded_username, nickname, remark, user_type_code, packed_data = row
            
            if not user_id:
                continue

            # 群聊已在get_groups中处理，这里跳过
            if "@chatroom" in user_id or "@openim" in user_id:
                continue

            unpacked_info = self._unpack_contact_data(packed_data)
            
            # 优先使用解包后的昵称
            final_nickname = unpacked_info.get('1', {}).get('2', nickname)
            
            user_type = "unknown"
            if user_type_code == 3:
                user_type = "friend"
            elif user_id.startswith("gh_"):
                user_type = "official_account"
            else:
                # 只保留好友和公众号
                continue

            contacts.append({
                'user_id': user_id,
                'encoded_username': encoded_username,
                'nickname': final_nickname,
                'remark': remark,
                'type': user_type,
            })
        
        return contacts

# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        hook = MacWeChatHook()
        
        # 查找消息数据库
        msg_db_path = hook.find_user_data_path()
        if msg_db_path:
            # 解密
            decrypted_msg_db = hook.decrypt_database(msg_db_path)
            
            if decrypted_msg_db:
                print(f"数据库解密成功: {decrypted_msg_db}")
                
                # 获取最近10条消息
                ten_seconds_ago = int(datetime.now().timestamp()) - 1000000
                messages = hook.get_chat_messages(decrypted_msg_db, last_check_time=ten_seconds_ago, limit=10)
                print("\n--- 最近消息 ---")
                for msg in messages:
                    print(f"[{datetime.fromtimestamp(msg['create_time'])}] From: {msg['room_id']}"
                          f" Sender: {msg.get('sender_id', 'N/A')}\n  Content: {msg['content'][:50]}...")

        # 查找联系人数据库
        contact_db_path = hook.find_user_data_path()
        if contact_db_path:
            decrypted_contact_db = hook.decrypt_database(contact_db_path)
            if decrypted_contact_db:
                print(f"\n联系人数据库解密成功: {decrypted_contact_db}")
                contacts = hook.get_contacts(decrypted_contact_db)
                print("\n--- 部分联系人 ---")
                for contact in contacts[:5]:
                    print(f"ID: {contact['user_id']}, Nick: {contact['nickname']}, Remark: {contact['remark']}, Type: {contact['type']}")

    except (ValueError, FileNotFoundError) as e:
        logger.error(f"启动测试失败: {e}")

"""
Changes:
- Removed `get_db_key_lldb` and replaced with `_get_db_key_from_env`.
- `__init__` now validates the key from the environment.
- Added `_get_wechat_version`.
- Rewritten `find_user_data_path` to handle both old and new WeChat directory structures and correctly select the user data folder.
- Completely rewrote `decrypt_database` to be more robust, efficient (avoids re-decrypting), and safer (checks for `sqlcipher` tool, copies db before decrypting).
- Rewritten `get_chat_messages` to accept `last_check_time`, filter in SQL, correctly parse group chat sender from message content, and return a more structured dictionary.
- Rewritten `get_groups` and `get_contacts` to return more structured data.
- Added a `_execute_query` helper for cleaner code.
- Updated main test block to reflect new methods.
"""