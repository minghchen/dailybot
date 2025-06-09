import os
import logging
import hashlib
import sqlite3
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

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
# 从你提供的日志中，我们确认了群聊的准确ID
GROUP_ID = "45867722107@chatroom"
GROUP_NAME = "Agent工程落地讨论"
OUTPUT_FILE = f"{GROUP_NAME}_history.txt"
# 我们希望获取所有历史记录，所以时间戳设为0
START_TIMESTAMP = 0

logger = logging.getLogger(__name__)

def export_chat_history():
    """
    导出指定群聊的全部聊天记录以供调试。
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

    # 2. 计算目标表名
    table_name = f"Chat_{hashlib.md5(GROUP_ID.encode()).hexdigest()}"
    logger.info(f"目标群聊: '{GROUP_NAME}' (ID: {GROUP_ID})")
    logger.info(f"计算出的目标表名: {table_name}")

    # 3. 遍历所有消息数据库，找到并导出数据
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

                # 4. 将数据写入文件
                with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                    f.write(f"群聊 '{GROUP_NAME}' (ID: {GROUP_ID}) 的历史记录导出\n")
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
        logger.warning("可能原因: 1. 群聊ID不正确; 2. 该群聊没有产生过任何消息; 3. .env文件中的WECHAT_DB_KEY不正确或文件未被加载。")

    logger.info("--- 诊断脚本执行完毕 ---")

if __name__ == "__main__":
    export_chat_history() 