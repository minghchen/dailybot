import os
import sys
import logging
import hashlib
import sqlite3
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

# --- 解决模块导入问题 ---
# 将项目根目录（即'scripts'目录的父目录）添加到sys.path中
# 这样无论从哪里运行脚本，都可以正确找到'services'等模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 在导入我们自己的模块之前，先设置好日志，避免潜在的配置问题
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s',
    force=True  # 确保我们的配置能覆盖掉其他模块可能设置的basicConfig
)

# --- 关键修复：在检查环境变量之前，加载.env文件 ---
load_dotenv(find_dotenv())

from services.mac_wechat_service import MacWeChatService

# --- 配置 ---
# 我们希望获取所有历史记录，所以时间戳设为0
START_TIMESTAMP = 0

logger = logging.getLogger(__name__)

def export_chat_history():
    """
    导出指定会话（群聊或单聊）的全部聊天记录以供调试。
    """
    logger.info("--- 开始导出聊天记录诊断脚本 ---")

    if "WECHAT_DB_KEY" not in os.environ:
        logger.error("错误: 脚本未能从 .env 文件或系统环境中加载 'WECHAT_DB_KEY'。请再次确认.env文件位置是否正确或环境变量是否已设置。")
        return

    # 1. 初始化服务，这将处理数据库解密和联系人加载
    logger.info("正在初始化MacWeChatService，这可能需要一些时间来解密数据库...")
    service = MacWeChatService(config={})
    if not service.initialize(use_hook_mode=False):
        logger.error("服务初始化失败。请检查日志输出以获取详细信息。")
        return
    logger.info("服务初始化成功。")

    # 2. 获取用户输入的会话名称
    try:
        conversation_name_input = input("请输入要导出的会话（群聊或联系人）的准确名称: ")
    except EOFError:
        logger.error("无法读取输入，可能在非交互式环境运行。脚本终止。")
        return
        
    if not conversation_name_input:
        logger.error("未输入会话名称，脚本终止。")
        return
    
    CONVERSATION_NAME = conversation_name_input

    # 3. 在所有联系人中查找会话
    target_conversation = None
    all_contacts_and_groups = service.get_contacts()

    if all_contacts_and_groups:
        for contact in all_contacts_and_groups:
            # 匹配群聊名称，或联系人昵称/备注名
            if contact.get('nickname') == CONVERSATION_NAME or \
               (contact.get('type') == 'friend' and contact.get('remark') == CONVERSATION_NAME):
                target_conversation = contact
                break  # 找到第一个匹配项即可
    
    if not target_conversation:
        logger.error(f"未能找到名为 '{CONVERSATION_NAME}' 的会话。")
        logger.warning("请确保输入的名称完全准确，没有错别字或多余的空格。")
        logger.warning("对于好友，程序会同时匹配其微信昵称和您设置的备注名。")
        
        # 增加调试信息：列出所有找到的好友，帮助用户确认正确的名称
        if all_contacts_and_groups:
            all_friends = [c for c in all_contacts_and_groups if c.get('type') == 'friend']
            if all_friends:
                logger.info("="*20 + " 可用好友列表 (for debug) " + "="*20)
                logger.info("为了帮助您调试，以下是脚本在您的联系人数据库中找到的所有好友的'昵称'和'备注'：")
                # 按备注或昵称排序，方便查找
                sorted_friends = sorted(all_friends, key=lambda c: (c.get('remark') or c.get('nickname') or ""))
                for friend in sorted_friends:
                    nick = friend.get('nickname', 'N/A')
                    remark = friend.get('remark', 'N/A')
                    # 只显示有备注或有效昵称的联系人
                    if remark != 'N/A' or nick != 'N/A':
                        logger.info(f"  - 昵称: '{nick}', 备注: '{remark}'")
                logger.info("="*66)
        return

    # 正确使用字典键来获取ID和名称
    CONVERSATION_ID = target_conversation['user_id']
    CONVERSATION_TYPE = target_conversation.get('type', 'unknown')
    OUTPUT_FILE = f"{CONVERSATION_NAME}_history.txt"
    logger.info(f"成功找到会话: '{CONVERSATION_NAME}' (ID: {CONVERSATION_ID}, 类型: {CONVERSATION_TYPE})")

    # 4. 计算目标表名 (对个人和群聊的算法是相同的)
    table_name = f"Chat_{hashlib.md5(CONVERSATION_ID.encode()).hexdigest()}"
    logger.info(f"计算出的目标表名: {table_name}")

    # 5. 遍历所有消息数据库，找到并导出数据
    found_table = False
    for db_manager in service.msg_db_managers:
        logger.info(f"正在尝试在数据库 '{db_manager.db_path.name}' 中查询表 '{table_name}'...")
        try:
            # 使用底层的 sqlite3 连接来获取列名
            with sqlite3.connect(db_manager.db_path) as conn:
                cursor = conn.cursor()
                # 检查表是否存在
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                if cursor.fetchone() is None:
                    continue # 表不在此数据库中，继续下一个

                logger.info(f"成功在 '{db_manager.db_path.name}' 中找到表！正在导出数据...")
                found_table = True

                # 获取所有列名
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [info[1] for info in cursor.fetchall()]
                
                # 查询所有数据
                cursor.execute(f"SELECT * FROM {table_name} ORDER BY msgCreateTime ASC")
                rows = cursor.fetchall()

                # 6. 将数据写入文件
                with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                    f.write(f"会话 '{CONVERSATION_NAME}' (ID: {CONVERSATION_ID}) 的历史记录导出\n")
                    f.write(f"数据库源: {db_manager.db_path.name}\n")
                    f.write(f"表名: {table_name}\n")
                    f.write(f"共找到 {len(rows)} 条记录。\n")
                    f.write("="*50 + "\n\n")

                    # 写入列头
                    f.write(" | ".join(columns) + "\n")
                    f.write("-" * (len(" | ".join(columns))) + "\n")

                    # 写入每一行数据
                    for row in rows:
                        row_str = " | ".join(
                            (
                                str(datetime.fromtimestamp(item)) if 'time' in col.lower() and isinstance(item, int) and item > 0 
                                else str(item)
                            )
                            for col, item in zip(columns, row)
                        )
                        f.write(row_str + "\n")
                
                logger.info(f"成功将 {len(rows)} 条记录导出到文件: {OUTPUT_FILE}")
                break # 找到后就停止遍历

        except sqlite3.Error as e:
            logger.error(f"查询数据库 '{db_manager.db_path.name}' 时发生错误: {e}")
            continue

    if not found_table:
        logger.warning(f"在所有已解密的消息数据库中都未能找到表 '{table_name}'。")
        logger.warning("可能原因: 1. 会话ID不正确; 2. 该会话没有产生过任何消息; 3. .env文件中的WECHAT_DB_KEY不正确或文件未被加载。")

    logger.info("--- 诊断脚本执行完毕 ---")

if __name__ == "__main__":
    export_chat_history() 