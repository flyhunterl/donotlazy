# encoding:utf-8

import os
import json
import sqlite3
from datetime import datetime, timedelta
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from config import conf


@plugins.register(
    name="donotlazy",
    desire_priority=90,
    hidden=True,
    desc="记录群消息已读情况",
    version="0.1",
    author="wangcl",
    accept_all_context=True
)
class DoNotLazy(Plugin):
    def __init__(self):
        super().__init__()
        try:
            logger.info(f"[donotlazy] 开始初始化插件")
            self.curdir = os.path.dirname(__file__)
            logger.info(f"[donotlazy] 插件目录: {self.curdir}")
            
            # 加载配置
            self.config = super().load_config()
            logger.info(f"[donotlazy] 加载配置结果: {self.config}")
            
            if not self.config:
                logger.warning("[donotlazy] 未找到配置文件，使用默认配置")
                self.config = {
                    "max_record_days": 7,
                    "read_keyword": "已读",
                    "class_name": "3班",
                    "student_file": "students.json",
                    "white_group_list": []
                }
            
            self.max_record_days = self.config.get("max_record_days", 7)
            self.read_keyword = self.config.get("read_keyword", "已读")
            self.class_name = self.config.get("class_name", "3班")
            self.student_file = self.config.get("student_file", "students.json")
            self.white_group_list = self.config.get("white_group_list", [])
            
            logger.info(f"[donotlazy] 配置: max_record_days={self.max_record_days}, read_keyword={self.read_keyword}, class_name={self.class_name}, student_file={self.student_file}")
            logger.info(f"[donotlazy] 白名单群组: {self.white_group_list}")
            
            # 加载学生名单
            self.students = self.load_students()
            
            # 初始化数据库
            self.db_path = os.path.join(self.curdir, "read_records.db")
            logger.info(f"[donotlazy] 数据库路径: {self.db_path}")
            self.init_database()
            
            logger.info(f"[donotlazy] 插件初始化成功，已加载 {len(self.students)} 名学生")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_receive_message
            
        except Exception as e:
            logger.error(f"[donotlazy] 初始化异常：{e}")
            raise f"[donotlazy] 初始化失败，忽略插件: {e}"
    
    def load_students(self):
        """加载学生名单"""
        students = {}
        try:
            # 尝试从插件目录加载JSON格式的学生名单
            student_file = os.path.join(self.curdir, self.student_file)
            logger.info(f"[donotlazy] 尝试加载学生名单: {student_file}")
            
            if not os.path.exists(student_file):
                logger.warning(f"[donotlazy] 找不到学生名单文件: {student_file}")
                # 尝试直接加载students.json
                default_file = os.path.join(self.curdir, "students.json")
                if os.path.exists(default_file):
                    student_file = default_file
                    logger.info(f"[donotlazy] 尝试使用默认名单文件: {default_file}")
                else:
                    logger.error(f"[donotlazy] 默认名单文件也不存在: {default_file}")
                    return {}
            
            # 检查文件大小
            file_size = os.path.getsize(student_file)
            logger.info(f"[donotlazy] 学生名单文件大小: {file_size} 字节")
            
            # 读取JSON文件
            with open(student_file, "r", encoding="utf-8") as f:
                file_content = f.read()
                logger.info(f"[donotlazy] 文件内容前100个字符: {file_content[:100]}")
                
                # 解析JSON
                data = json.loads(file_content)
                logger.info(f"[donotlazy] 成功解析JSON，数据结构: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                
            # 解析学生数据
            if "students" in data and isinstance(data["students"], list):
                student_list = data["students"]
                for student in student_list:
                    if "name" in student and "id" in student:
                        students[student["name"]] = student["id"]
                        
            # 记录加载结果
            count = len(students)
            logger.info(f"[donotlazy] 成功从文件加载了 {count} 名学生")
            if count > 0:
                logger.info(f"[donotlazy] 部分学生名单: {list(students.keys())[:5]}...")
            else:
                logger.warning(f"[donotlazy] 从文件加载的学生名单为空")
            
            return students
        except Exception as e:
            logger.error(f"[donotlazy] 加载学生名单异常: {e}")
            logger.exception(e)  # 打印完整堆栈
            return {}
    
    def init_database(self):
        """初始化数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 创建已读记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS read_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT,
                        student_name TEXT,
                        read_time TEXT,
                        create_date TEXT,
                        UNIQUE(group_id, student_name, create_date)
                    )
                ''')
                # 创建消息记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT,
                        message_content TEXT,
                        create_time TEXT,
                        create_date TEXT,
                        other_user_nickname TEXT
                    )
                ''')
                conn.commit()
                logger.info("[donotlazy] 数据库初始化成功")
        except Exception as e:
            logger.error(f"[donotlazy] 数据库初始化异常：{e}")
    
    def on_handle_context(self, e_context: EventContext):
        """处理用户命令"""
        if e_context["context"].type not in [ContextType.TEXT]:
            return
            
        msg: ChatMessage = e_context["context"]["msg"]
        content = e_context["context"].content.strip()
        
        # 群消息特殊处理：添加当前群组到白名单
        if e_context["context"]["isgroup"] and content == "添加本群到白名单":
            self._handle_add_current_group(e_context, msg)
            return
            
        # 群消息特殊处理：从白名单中删除当前群组
        if e_context["context"]["isgroup"] and content == "从白名单删除本群":
            self._handle_remove_current_group(e_context, msg)
            return
        
        # 检查是否为群消息，以及是否在白名单中
        if e_context["context"]["isgroup"]:
            # 如果白名单不为空，且当前群组不在白名单中，则不处理
            if self.white_group_list and msg.other_user_id not in self.white_group_list:
                logger.info(f"[donotlazy] 群组 {msg.other_user_id} 不在白名单中，跳过处理")
                return
        
        # 查询已读同学
        if content == "查询已读同学":
            self._handle_query_read(e_context, msg)
        # 查询未读同学
        elif content == "查询未读同学":
            self._handle_query_unread(e_context, msg)
        # 重置记录
        elif content == "重置记录":
            self._handle_reset_confirm(e_context, msg)
        # 确认重置
        elif content == "确认重置":
            self._handle_reset_records(e_context, msg)
        # 查看学生名单
        elif content == "查看学生名单":
            self._handle_show_students(e_context, msg)
        # 更新学生名单
        elif content == "更新学生名单":
            self._handle_reload_students(e_context, msg)
        # 测试记录命令
        elif content == "测试记录同学24":
            self._handle_test_record(e_context, msg, "同学24")
        # 显示白名单
        elif content == "显示白名单":
            self._handle_show_whitelist(e_context, msg)
        # 添加白名单
        elif content.startswith("添加白名单"):
            self._handle_add_whitelist(e_context, msg, content[5:].strip())
        # 删除白名单
        elif content.startswith("删除白名单"):
            self._handle_remove_whitelist(e_context, msg, content[5:].strip())
        # 清空白名单
        elif content == "清空白名单":
            self._handle_clear_whitelist(e_context, msg)
        # 白名单帮助
        elif content == "白名单帮助":
            self._handle_whitelist_help(e_context, msg)
    
    def _handle_query_read(self, e_context, msg):
        """处理查询已读同学命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 获取查询日期范围（今天和7天前）
            today = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=self.max_record_days-1)).strftime('%Y-%m-%d')
            
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 记录请求日志
            logger.info(f"[donotlazy] 查询已读同学, 群组ID: {group_id}, 群名: {group_name}, 日期范围: {start_date} 至 {today}")
            
            # 检查学生名单是否为空
            if not self.students:
                reply.content = f"未能加载学生名单，请检查配置。"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            logger.info(f"[donotlazy] 已加载学生名单，共 {len(self.students)} 人")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查数据库是否有记录
                cursor.execute("SELECT COUNT(*) FROM read_records")
                total_records = cursor.fetchone()[0]
                logger.info(f"[donotlazy] 数据库中共有 {total_records} 条已读记录")
                
                # 查询记录 - 在私聊中查询所有记录而不仅是私聊的记录
                if e_context["context"]["isgroup"]:
                    # 群聊中只查询该群的记录
                    cursor.execute('''
                        SELECT student_name, read_time, create_date, group_id
                        FROM read_records
                        WHERE group_id = ? AND create_date BETWEEN ? AND ?
                        ORDER BY create_date DESC, read_time ASC
                    ''', (group_id, start_date, today))
                else:
                    # 私聊中查询所有记录
                    cursor.execute('''
                        SELECT student_name, read_time, create_date, group_id
                        FROM read_records
                        WHERE create_date BETWEEN ? AND ?
                        ORDER BY create_date DESC, read_time ASC
                    ''', (start_date, today))
                
                records = cursor.fetchall()
                logger.info(f"[donotlazy] 查询到 {len(records)} 条符合条件的记录")
            
            if not records:
                reply.content = f"在 {start_date} 至 {today} 期间，{group_name} 没有记录到已读信息。"
            else:
                # 按日期分组
                date_groups = {}
                group_info = {}
                
                # 获取群组名称映射
                if not e_context["context"]["isgroup"]:
                    unique_group_ids = set(record[3] for record in records if record[3] != "私聊")
                    for unique_id in unique_group_ids:
                        group_info[unique_id] = "未知群组"  # 默认名称
                
                for record in records:
                    student_name, read_time, create_date, record_group_id = record
                    if create_date not in date_groups:
                        date_groups[create_date] = []
                    
                    # 在私聊模式下，添加群组信息
                    if not e_context["context"]["isgroup"]:
                        date_groups[create_date].append((student_name, read_time, record_group_id))
                    else:
                        date_groups[create_date].append((student_name, read_time))
                
                # 构建回复内容
                result = f"已读情况统计（{start_date} 至 {today}）\n\n"
                
                # 先显示今天的已读情况
                if today in date_groups:
                    today_students = date_groups[today]
                    result += f"今日（{today}）已读情况：\n"
                    
                    if not e_context["context"]["isgroup"]:
                        # 私聊中显示群组信息
                        for i, (name, time, record_group_id) in enumerate(today_students):
                            # 使用群名称替代群ID
                            group_display = ""
                            if record_group_id != "私聊":
                                # 尝试从数据库或者其他方式获取群名称
                                group_name = self._get_group_name(record_group_id)
                                group_display = f"[{group_name}]"
                            
                            # 标记不在名单中的用户
                            name_display = name
                            if name not in self.students:
                                name_display = f"{name}(未在同学名单)"
                                
                            result += f"{i+1}. {name_display}{group_display}（{time}）\n"
                        
                        # 今日统计（私聊模式下不显示未读人数，因为跨群了）
                        result += f"今日已读：{len(today_students)}人\n\n"
                    else:
                        # 群聊中的显示方式
                        for i, (name, time) in enumerate(today_students):
                            # 标记不在名单中的用户
                            name_display = name
                            if name not in self.students:
                                name_display = f"{name}(未在同学名单)"
                                
                            result += f"{i+1}. {name_display}（{time}）\n"
                        
                        # 计算名单中的未读人数
                        in_list_count = 0
                        for name in self.students:
                            if not any(student[0] == name for student in today_students):
                                in_list_count += 1
                        
                        result += f"今日已读：{len(today_students)}人，未读：{in_list_count}人\n\n"
                
                # 显示历史记录
                result += "历史已读记录：\n"
                for date, students in sorted(date_groups.items(), reverse=True):
                    if date == today:  # 今天的已经显示过了
                        continue
                    
                    if not e_context["context"]["isgroup"]:
                        # 按日期和群组汇总
                        group_students = {}
                        for name, read_time, record_group_id in students:
                            if record_group_id not in group_students:
                                group_students[record_group_id] = []
                            group_students[record_group_id].append((name, read_time))
                        
                        result += f"日期：{date} - 总计{len(students)}人已读\n"
                        # 显示每个群的情况，包括具体人名
                        for group_id, student_list in group_students.items():
                            if group_id != "私聊":
                                group_name = self._get_group_name(group_id)
                                group_display = f"[{group_name}]"
                            else:
                                group_display = "[私聊]"
                            result += f"  {group_display}: {len(student_list)}人\n"
                            
                            # 显示具体的学生名单和阅读时间
                            for i, (name, time) in enumerate(student_list):
                                # 标记不在名单中的用户
                                name_display = name
                                if name not in self.students:
                                    name_display = f"{name}(未在同学名单)"
                                    
                                result += f"    {i+1}. {name_display}（{time}）\n"
                    else:
                        # 群聊中显示具体人名
                        result += f"日期：{date} - {len(students)}人已读\n"
                        # 显示具体学生名单
                        for i, (name, time) in enumerate(students):
                            # 标记不在名单中的用户
                            name_display = name
                            if name not in self.students:
                                name_display = f"{name}(未在同学名单)"
                                
                            result += f"  {i+1}. {name_display}（{time}）\n"
                
                reply.content = result.strip()
        except Exception as e:
            logger.error(f"[donotlazy] 查询已读同学异常：{e}")
            reply.content = f"查询失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_query_unread(self, e_context, msg):
        """处理查询未读同学命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 获取当前日期
            today = datetime.now().strftime('%Y-%m-%d')
            
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 在私聊中查询所有群组的未读情况
            if e_context["context"]["isgroup"]:
                # 获取今日该群已读学生
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT student_name
                        FROM read_records
                        WHERE group_id = ? AND create_date = ?
                    ''', (group_id, today))
                    
                    all_read_users = [record[0] for record in cursor.fetchall()]
                
                # 分类已读用户：在名单中和不在名单中的
                read_students_in_list = []
                read_students_not_in_list = []
                
                for name in all_read_users:
                    if name in self.students:
                        read_students_in_list.append(name)
                    else:
                        read_students_not_in_list.append(name)
                
                # 找出未读的学生
                unread_students = []
                for name in self.students.keys():
                    if name not in all_read_users:
                        unread_students.append(name)
                
                if not unread_students:
                    result = f"在 {today}，{group_name} 所有名单内的同学均已阅读。\n\n"
                else:
                    result = f"未读情况统计（{today}）\n\n"
                    result += f"在名单中的已读人数：{len(read_students_in_list)}人\n"
                    result += f"未在同学名单中但已读人数：{len(read_students_not_in_list)}人\n"
                    result += f"未读人数：{len(unread_students)}人\n\n"
                
                # 显示在名单中的已读学生
                if len(read_students_in_list) > 0:
                    result += f"在名单中的已读同学：\n"
                    # 只显示前10个已读学生，如果太多的话
                    display_limit = min(10, len(read_students_in_list))
                    for i in range(display_limit):
                        student_name = read_students_in_list[i]
                        student_id = self.students.get(student_name, "")
                        result += f"  {i+1}. {student_name}（学号：{student_id}）\n"
                    
                    if len(read_students_in_list) > display_limit:
                        result += f"  ...等共 {len(read_students_in_list)} 人已读\n"
                    
                    result += "\n"
                
                # 显示不在名单中但已读的用户
                if len(read_students_not_in_list) > 0:
                    result += f"未在同学名单中但已读的用户：\n"
                    for i, name in enumerate(read_students_not_in_list):
                        result += f"  {i+1}. {name}\n"
                    
                    result += "\n"
                
                # 显示未读学生名单
                if len(unread_students) > 0:
                    result += f"未读同学名单：\n"
                    for i, name in enumerate(unread_students):
                        student_id = self.students.get(name, "")
                        result += f"  {i+1}. {name}（学号：{student_id}）\n"
                
                reply.content = result.strip()
            else:
                # 私聊模式：获取所有群组的阅读情况
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 获取所有活跃的群组
                    cursor.execute('''
                        SELECT DISTINCT group_id 
                        FROM read_records 
                        WHERE create_date = ? AND group_id != '私聊'
                    ''', (today,))
                    
                    active_groups = [record[0] for record in cursor.fetchall()]
                    
                    if not active_groups:
                        reply.content = f"在 {today}，没有任何群组的已读记录。"
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                    
                    result = f"未读情况统计（{today}）\n\n"
                    
                    # 获取每个群的已读情况
                    for group_id in active_groups:
                        cursor.execute('''
                            SELECT student_name
                            FROM read_records
                            WHERE group_id = ? AND create_date = ?
                        ''', (group_id, today))
                        
                        all_read_users = [record[0] for record in cursor.fetchall()]
                        
                        # 分类已读用户：在名单中和不在名单中的
                        read_students_in_list = []
                        read_students_not_in_list = []
                        
                        for name in all_read_users:
                            if name in self.students:
                                read_students_in_list.append(name)
                            else:
                                read_students_not_in_list.append(name)
                        
                        # 找出未读的学生
                        unread_students = []
                        for name in self.students.keys():
                            if name not in all_read_users:
                                unread_students.append(name)
                        
                        # 获取群名称
                        group_name = self._get_group_name(group_id)
                        result += f"【群组: {group_name}】\n"
                        result += f"在名单中的已读人数：{len(read_students_in_list)}人\n"
                        result += f"未在同学名单中但已读人数：{len(read_students_not_in_list)}人\n"
                        result += f"未读人数：{len(unread_students)}人\n"
                        
                        # 显示在名单中的已读学生
                        if len(read_students_in_list) > 0:
                            result += f"在名单中的已读同学：\n"
                            # 只显示前10个已读学生，如果太多的话
                            display_limit = min(10, len(read_students_in_list))
                            for i in range(display_limit):
                                student_name = read_students_in_list[i]
                                student_id = self.students.get(student_name, "")
                                result += f"  {i+1}. {student_name}（学号：{student_id}）\n"
                            
                            if len(read_students_in_list) > display_limit:
                                result += f"  ...等共 {len(read_students_in_list)} 人已读\n"
                            
                            result += "\n"
                        
                        # 显示不在名单中但已读的用户
                        if len(read_students_not_in_list) > 0:
                            result += f"未在同学名单中但已读的用户：\n"
                            for i, name in enumerate(read_students_not_in_list):
                                result += f"  {i+1}. {name}\n"
                            
                            result += "\n"
                        
                        # 显示未读学生名单
                        if len(unread_students) > 0:
                            result += f"未读同学名单：\n"
                            # 只显示前10个未读学生，如果太多的话
                            display_limit = min(10, len(unread_students))
                            for i in range(display_limit):
                                student_id = self.students.get(unread_students[i], "")
                                result += f"  {i+1}. {unread_students[i]}（学号：{student_id}）\n"
                            
                            if len(unread_students) > display_limit:
                                result += f"  ...等共 {len(unread_students)} 人未读\n"
                        
                        result += "\n"
                    
                    reply.content = result.strip()
        except Exception as e:
            logger.error(f"[donotlazy] 查询未读同学异常：{e}")
            reply.content = f"查询失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reset_confirm(self, e_context, msg):
        """处理重置记录确认"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 查询当天记录数量
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM read_records
                    WHERE group_id = ? AND create_date = ?
                ''', (group_id, today))
                
                count = cursor.fetchone()[0]
            
            if count == 0:
                reply.content = f"当前没有 {today} 的已读记录，无需重置。"
            else:
                reply.content = f"确认要重置 {today} 的已读记录吗？将删除 {count} 条记录。\n如果确认，请回复「确认重置」"
            
        except Exception as e:
            logger.error(f"[donotlazy] 重置确认异常：{e}")
            reply.content = f"操作失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reset_records(self, e_context, msg):
        """处理重置记录命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            today = datetime.now().strftime('%Y-%m-%d')
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM read_records
                    WHERE group_id = ? AND create_date = ?
                ''', (group_id, today))
                conn.commit()
                
                deleted_count = cursor.rowcount
            
            reply.content = f"已重置{today}的阅读记录，共删除 {deleted_count} 条记录。"
        except Exception as e:
            logger.error(f"[donotlazy] 重置记录异常：{e}")
            reply.content = f"重置失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_show_students(self, e_context, msg):
        """显示当前加载的学生名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            if not self.students:
                reply.content = "当前未加载任何学生信息。"
            else:
                result = f"当前已加载 {len(self.students)} 名学生信息：\n\n"
                for i, (name, student_id) in enumerate(self.students.items()):
                    result += f"{i+1}. {name}（学号：{student_id}）\n"
                    
                # 检查是否包含特定学生
                if "同学24" in self.students:
                    result += f"\n同学24在名单中，学号为：{self.students['同学24']}"
                else:
                    result += f"\n注意：同学24不在名单中"
                    
                reply.content = result
        except Exception as e:
            logger.error(f"[donotlazy] 显示学生名单异常：{e}")
            reply.content = f"获取学生名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def on_receive_message(self, e_context: EventContext):
        """处理接收到的消息"""
        try:
            # 检查是否有消息对象
            if not hasattr(e_context["context"], "msg"):
                # 尝试直接从context中获取msg内容
                if "msg" in e_context["context"]:
                    msg = e_context["context"]["msg"]
                else:
                    logger.info(f"[donotlazy] 未找到消息对象，跳过处理")
                    return
            else:
                msg = e_context["context"]["msg"]
            
            # 记录消息类型信息
            msg_type = getattr(msg, "msg_type", 0)
            logger.info(f"[donotlazy] 接收到消息，类型: {msg_type}, 发送者: {getattr(msg, 'actual_user_nickname', 'unknown')}")
            
            # 不是群消息则跳过
            is_group = getattr(msg, "is_group", False) or e_context["context"].get("isgroup", False)
            if not is_group:
                logger.info(f"[donotlazy] 不是群消息，跳过处理")
                return
            
            # 如果白名单不为空，且当前群组不在白名单中，则不处理
            if hasattr(msg, "other_user_id") and self.white_group_list and msg.other_user_id not in self.white_group_list:
                logger.info(f"[donotlazy] 群组 {msg.other_user_id} 不在白名单中，跳过处理")
                return
            
            # 自动清理过期数据
            self._clean_expired_records()
            
            # 优先检查消息类型
            if msg_type == 43:
                # 处理视频消息（类型43）
                logger.info(f"[donotlazy] 处理视频消息，发送者: {getattr(msg, 'actual_user_nickname', 'unknown')}")
                self._process_non_text_message(msg)
                return
            elif msg_type in [3, 47, 49]:
                # 处理其他已知消息类型（3:图片, 47:表情, 49:链接）
                logger.info(f"[donotlazy] 处理其他类型消息({msg_type})，发送者: {getattr(msg, 'actual_user_nickname', 'unknown')}")
                self._process_non_text_message(msg)
                return
            
            # 根据context类型处理
            if e_context["context"].type == ContextType.TEXT:
                # 处理文本消息
                content = e_context["context"].content.strip()
                # 记录群消息
                self._record_message(msg)
                # 优化已读消息识别
                self._process_read_message(msg, content)
            elif msg_type == 1:
                # 处理文本消息但不是通过context检测到的
                if hasattr(msg, "content"):
                    content = msg.content.strip()
                    self._record_message(msg)
                    self._process_read_message(msg, content)
                else:
                    logger.warning(f"[donotlazy] 文本消息缺少content属性")
            else:
                # 未知消息类型，尝试作为非文本消息处理
                logger.info(f"[donotlazy] 收到未处理的消息类型: {msg_type}，尝试作为非文本消息处理")
                self._process_non_text_message(msg)
        except Exception as e:
            logger.error(f"[donotlazy] 处理消息异常: {e}")
            logger.exception(e)
    
    def _process_read_message(self, msg, content):
        """处理可能的已读消息"""
        try:
            logger.info(f"[donotlazy] 处理消息: {content}, 发送者: {msg.actual_user_nickname}")
            
            # 直接发送"已读"的情况
            if content == self.read_keyword:
                student_name = msg.actual_user_nickname
                logger.info(f"[donotlazy] 检测到纯已读消息，发送者: {student_name}")
                # 不再检查学生是否在名单中，直接记录
                self._record_read_status(msg, student_name)
                return
            
            # "XXX已读"的情况
            if self.read_keyword in content:
                logger.info(f"[donotlazy] 检测到可能包含已读的消息: {content}")
                
                # 先尝试精确匹配 "某某已读"
                found_match = False
                for name in self.students.keys():
                    pattern = f"{name}{self.read_keyword}"
                    if pattern in content:
                        logger.info(f"[donotlazy] 从消息中精确匹配到学生: {name}")
                        self._record_read_status(msg, name)
                        found_match = True
                        break
                
                if found_match:
                    return
                    
                # 尝试匹配发送者，如果发送包含已读关键词的消息
                student_name = msg.actual_user_nickname
                if self.read_keyword in content:
                    logger.info(f"[donotlazy] 发送者消息包含已读关键词: {student_name}")
                    self._record_read_status(msg, student_name)
                    return
                
                # 尝试更宽松的匹配
                for name in content.replace(self.read_keyword, "").strip().split():
                    if name and len(name) > 1:  # 避免记录单个字符
                        # 检查名字在已读关键词之前
                        if name in content and content.find(name) < content.find(self.read_keyword):
                            logger.info(f"[donotlazy] 从消息中提取可能的名字: {name}")
                            self._record_read_status(msg, name)
                            return
        except Exception as e:
            logger.error(f"[donotlazy] 处理已读消息异常: {e}")
            logger.exception(e)
    
    def _record_message(self, msg):
        """记录群消息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now()
                time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                date_str = now.strftime('%Y-%m-%d')
                
                # 检查message_records表是否有other_user_nickname列
                cursor.execute("PRAGMA table_info(message_records)")
                columns = [info[1] for info in cursor.fetchall()]
                
                # 如果没有other_user_nickname列，则添加
                if "other_user_nickname" not in columns:
                    cursor.execute('''
                        ALTER TABLE message_records 
                        ADD COLUMN other_user_nickname TEXT
                    ''')
                    logger.info("[donotlazy] 已为message_records表添加other_user_nickname列")
                
                # 插入记录，包含群名称
                cursor.execute('''
                    INSERT INTO message_records 
                    (group_id, message_content, create_time, create_date, other_user_nickname)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    msg.other_user_id,
                    msg.content,
                    time_str,
                    date_str,
                    msg.other_user_nickname
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"[donotlazy] 记录群消息异常：{e}")
    
    def _record_read_status(self, msg, student_name):
        """记录学生已读状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now()
                time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                date_str = now.strftime('%Y-%m-%d')
                
                group_id = msg.other_user_id
                
                # 检查该学生今日是否已记录
                cursor.execute('''
                    SELECT id FROM read_records 
                    WHERE group_id = ? AND student_name = ? AND create_date = ?
                ''', (group_id, student_name, date_str))
                record = cursor.fetchone()
                
                if record:
                    logger.info(f"[donotlazy] 学生 {student_name} 今日已有记录，更新时间")
                    cursor.execute('''
                        UPDATE read_records 
                        SET read_time = ? 
                        WHERE group_id = ? AND student_name = ? AND create_date = ?
                    ''', (time_str, group_id, student_name, date_str))
                else:
                    logger.info(f"[donotlazy] 新增学生 {student_name} 的已读记录")
                    cursor.execute('''
                        INSERT INTO read_records (group_id, student_name, read_time, create_date)
                        VALUES (?, ?, ?, ?)
                    ''', (group_id, student_name, time_str, date_str))
                
                conn.commit()
                logger.info(f"[donotlazy] 成功记录 {student_name} 的已读状态, 群组ID: {group_id}, 日期: {date_str}")
        except Exception as e:
            logger.error(f"[donotlazy] 记录已读状态异常：{e}")
    
    def _clean_expired_records(self):
        """清理过期记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                expire_date = (datetime.now() - timedelta(days=self.max_record_days)).strftime('%Y-%m-%d')
                
                # 清理已读记录
                cursor.execute('''
                    DELETE FROM read_records
                    WHERE create_date < ?
                ''', (expire_date,))
                
                # 清理消息记录
                cursor.execute('''
                    DELETE FROM message_records
                    WHERE create_date < ?
                ''', (expire_date,))
                
                conn.commit()
        except Exception as e:
            logger.error(f"[donotlazy] 清理过期记录异常：{e}")
    
    def get_help_text(self, **kwargs):
        help_text = "【不要偷懒】插件使用说明：\n"
        help_text += "1. 发送「已读」即可记录已读状态\n"
        help_text += "2. 发送「查询已读同学」查看已读情况\n"
        help_text += "3. 发送「查询未读同学」查看未读情况\n"
        help_text += "4. 发送「重置记录」清空当日记录\n"
        help_text += "5. 发送「查看学生名单」查看当前加载的学生名单\n"
        help_text += "6. 发送「更新学生名单」手动重新加载学生名单\n"
        help_text += "7. 学生可以直接发送「XXX已读」记录指定学生已读状态\n"
        help_text += "8. 发送「测试记录同学24」测试记录功能\n"
        help_text += "9. 发送「显示白名单」查看白名单\n"
        help_text += "10. 发送「添加白名单 群组名称」添加白名单群组\n"
        help_text += "11. 发送「删除白名单 群组名称」删除白名单群组\n"
        help_text += "12. 发送「清空白名单」清空所有白名单群组\n"
        help_text += "13. 发送「白名单帮助」获取白名单帮助\n"
        return help_text
    
    def _load_config_template(self):
        logger.info("[donotlazy] 使用配置模板")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
            return {}
        except Exception as e:
            logger.exception(e)
            return {}
    
    def _handle_test_record(self, e_context, msg, student_name):
        """测试记录指定学生的已读状态"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            self._record_read_status(msg, student_name)
            
            # 检查是否在学生名单中
            if student_name in self.students:
                reply.content = f"已成功记录 {student_name} 的已读状态。该用户在学生名单中，学号：{self.students[student_name]}"
            else:
                reply.content = f"已成功记录 {student_name} 的已读状态。注意：该用户未在同学名单中。"
        except Exception as e:
            logger.error(f"[donotlazy] 测试记录异常：{e}")
            reply.content = f"测试记录失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reload_students(self, e_context, msg):
        """重新加载学生名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 如果是群消息，检查是否在白名单中
            if e_context["context"]["isgroup"]:
                if self.white_group_list and msg.other_user_id not in self.white_group_list:
                    reply.content = "当前群组不在白名单中，无法执行此操作。"
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
            
            # 记录之前的学生数量
            old_count = len(self.students)
            old_students = list(self.students.keys())[:5]
            
            # 重新加载学生名单
            self.students = self.load_students()
            
            # 计算新增学生
            new_count = len(self.students)
            
            if new_count == 0:
                reply.content = "学生名单加载失败，当前没有学生信息。"
            else:
                reply.content = f"学生名单已更新。之前有 {old_count} 名学生，现在有 {new_count} 名学生。\n"
                reply.content += f"之前的前5名学生: {old_students}\n"
                reply.content += f"现在的前5名学生: {list(self.students.keys())[:5]}"
                
                # 检查同学24是否在名单中
                if "同学24" in self.students:
                    reply.content += f"\n同学24在名单中，学号为: {self.students['同学24']}"
        except Exception as e:
            logger.error(f"[donotlazy] 重新加载学生名单异常: {e}")
            reply.content = f"更新学生名单失败: {str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _get_group_name(self, group_id):
        """根据群ID获取群名称"""
        try:
            # 尝试从数据库获取群名称
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 首先尝试从other_user_nickname字段中获取群名称
                cursor.execute('''
                    SELECT other_user_nickname 
                    FROM message_records 
                    WHERE group_id = ? AND other_user_nickname IS NOT NULL
                    ORDER BY create_time DESC
                    LIMIT 1
                ''', (group_id,))
                
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
                
                # 如果没有找到，尝试旧方法
                cursor.execute('''
                    SELECT DISTINCT other_user_nickname 
                    FROM message_records 
                    WHERE group_id = ? 
                    LIMIT 1
                ''', (group_id,))
                
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
            
            # 如果找不到群名称，则返回群ID的前10个字符 + "..."
            if len(group_id) > 10:
                return group_id[:10] + "..."
            return group_id
        except Exception as e:
            logger.error(f"[donotlazy] 获取群名称异常：{e}")
            return group_id
    
    def _handle_show_whitelist(self, e_context, msg):
        """显示白名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            if not self.white_group_list:
                reply.content = "当前没有设置白名单，插件会响应所有群组消息。"
            else:
                result = f"当前白名单群组({len(self.white_group_list)}个)：\n\n"
                # 读取数据库获取群组名称
                group_names = {}
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    for group_id in self.white_group_list:
                        cursor.execute('''
                            SELECT other_user_nickname 
                            FROM message_records 
                            WHERE group_id = ? AND other_user_nickname IS NOT NULL
                            ORDER BY create_time DESC
                            LIMIT 1
                        ''', (group_id,))
                        
                        record = cursor.fetchone()
                        if record and record[0]:
                            group_names[group_id] = record[0]
                        else:
                            group_names[group_id] = "未知群名"
                
                # 显示群组列表
                for i, group_id in enumerate(self.white_group_list):
                    group_name = group_names.get(group_id, "未知群名")
                    result += f"{i+1}. {group_id} ({group_name})\n"
                
                result += "\n说明：插件只会响应白名单中的群组消息。如需修改，请编辑配置文件。"
                reply.content = result.strip()
        except Exception as e:
            logger.error(f"[donotlazy] 显示白名单异常：{e}")
            logger.exception(e)
            reply.content = f"获取白名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_add_whitelist(self, e_context, msg, group_id_or_name):
        """添加白名单群组"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        # 只允许在私聊中管理白名单
        if e_context["context"]["isgroup"]:
            reply.content = "只能在私聊中管理白名单。"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        try:
            if not group_id_or_name:
                reply.content = "请指定要添加的群组ID或群名称。格式：添加白名单 群组名称"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 判断是否为纯数字ID
            if group_id_or_name.isdigit():
                # 按ID处理
                group_id = group_id_or_name
                if group_id in self.white_group_list:
                    reply.content = f"群组ID {group_id} 已在白名单中。"
                else:
                    self.white_group_list.append(group_id)
                    # 保存配置
                    self._save_config()
                    
                    # 尝试获取群名称
                    group_name = self._get_group_name(group_id)
                    if group_name != group_id:
                        reply.content = f"已成功将群组 {group_id}（{group_name}）添加到白名单。"
                    else:
                        reply.content = f"已成功将群组ID {group_id} 添加到白名单。"
            else:
                # 按名称处理，搜索匹配的群组
                matched_groups = self._find_group_by_name(group_id_or_name)
                
                if not matched_groups:
                    reply.content = f"未找到名称包含「{group_id_or_name}」的群组，请确认群名称是否正确，或者使用群ID添加。"
                elif len(matched_groups) == 1:
                    # 只有一个匹配，直接添加
                    group_id, group_name = matched_groups[0]
                    if group_id in self.white_group_list:
                        reply.content = f"群组「{group_name}」(ID: {group_id}) 已在白名单中。"
                    else:
                        self.white_group_list.append(group_id)
                        # 保存配置
                        self._save_config()
                        reply.content = f"已成功将群组「{group_name}」(ID: {group_id}) 添加到白名单。"
                else:
                    # 多个匹配，列出所有匹配项
                    result = f"找到多个匹配「{group_id_or_name}」的群组，请使用群ID添加或者提供更精确的群名称：\n\n"
                    for i, (gid, gname) in enumerate(matched_groups):
                        status = "（已在白名单中）" if gid in self.white_group_list else ""
                        result += f"{i+1}. {gname} (ID: {gid}) {status}\n"
                    
                    result += "\n添加格式：添加白名单 群组名称"
                    reply.content = result
                    
        except Exception as e:
            logger.error(f"[donotlazy] 添加白名单异常：{e}")
            logger.exception(e)
            reply.content = f"添加白名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_remove_whitelist(self, e_context, msg, group_id_or_name):
        """删除白名单群组"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        # 只允许在私聊中管理白名单
        if e_context["context"]["isgroup"]:
            reply.content = "只能在私聊中管理白名单。"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        try:
            if not group_id_or_name:
                reply.content = "请指定要删除的群组ID或群名称。格式：删除白名单 群组名称"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 判断是否为纯数字ID
            if group_id_or_name.isdigit():
                # 按ID处理
                group_id = group_id_or_name
                if group_id not in self.white_group_list:
                    reply.content = f"群组ID {group_id} 不在白名单中。"
                else:
                    self.white_group_list.remove(group_id)
                    # 保存配置
                    self._save_config()
                    
                    # 尝试获取群名称
                    group_name = self._get_group_name(group_id)
                    if group_name != group_id:
                        reply.content = f"已成功将群组 {group_id}（{group_name}）从白名单中删除。"
                    else:
                        reply.content = f"已成功将群组ID {group_id} 从白名单中删除。"
            else:
                # 按名称处理，搜索匹配的群组
                matched_groups = self._find_group_by_name(group_id_or_name)
                
                if not matched_groups:
                    reply.content = f"未找到名称包含「{group_id_or_name}」的群组，请确认群名称是否正确，或者使用群ID删除。"
                elif len(matched_groups) == 1:
                    # 只有一个匹配，检查是否在白名单中
                    group_id, group_name = matched_groups[0]
                    if group_id not in self.white_group_list:
                        reply.content = f"群组「{group_name}」(ID: {group_id}) 不在白名单中。"
                    else:
                        self.white_group_list.remove(group_id)
                        # 保存配置
                        self._save_config()
                        reply.content = f"已成功将群组「{group_name}」(ID: {group_id}) 从白名单中删除。"
                else:
                    # 多个匹配，筛选出在白名单中的群组
                    whitelist_matches = [(gid, gname) for gid, gname in matched_groups if gid in self.white_group_list]
                    
                    if not whitelist_matches:
                        reply.content = f"找到多个匹配「{group_id_or_name}」的群组，但它们都不在白名单中。"
                    elif len(whitelist_matches) == 1:
                        # 只有一个在白名单中的匹配，直接删除
                        group_id, group_name = whitelist_matches[0]
                        self.white_group_list.remove(group_id)
                        # 保存配置
                        self._save_config()
                        reply.content = f"已成功将群组「{group_name}」(ID: {group_id}) 从白名单中删除。"
                    else:
                        # 多个在白名单中的匹配，列出所有匹配项
                        result = f"找到多个匹配「{group_id_or_name}」且在白名单中的群组，请使用群ID删除或者提供更精确的群名称：\n\n"
                        for i, (gid, gname) in enumerate(whitelist_matches):
                            result += f"{i+1}. {gname} (ID: {gid})\n"
                        
                        result += "\n删除格式：删除白名单 群组名称"
                        reply.content = result
                    
        except Exception as e:
            logger.error(f"[donotlazy] 删除白名单异常：{e}")
            logger.exception(e)
            reply.content = f"删除白名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _save_config(self):
        """保存配置到文件"""
        try:
            # 更新配置
            self.config["white_group_list"] = self.white_group_list
            
            # 保存到文件
            config_path = os.path.join(self.curdir, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            
            logger.info(f"[donotlazy] 配置已保存，白名单: {self.white_group_list}")
            return True
        except Exception as e:
            logger.error(f"[donotlazy] 保存配置异常：{e}")
            logger.exception(e)
            return False
    
    def _handle_clear_whitelist(self, e_context, msg):
        """清空白名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            self.white_group_list = []
            # 保存配置
            self._save_config()
            reply.content = "已成功清空白名单。"
        except Exception as e:
            logger.error(f"[donotlazy] 清空白名单异常：{e}")
            logger.exception(e)
            reply.content = f"清空白名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_whitelist_help(self, e_context, msg):
        """获取白名单帮助"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        help_text = "白名单帮助：\n\n"
        help_text += "白名单功能简介：\n"
        help_text += "- 当设置了白名单后，插件只会处理白名单中群组的消息\n"
        help_text += "- 如果白名单为空，则会处理所有群组的消息\n\n"
        
        help_text += "私聊命令：\n"
        help_text += "1. 显示白名单：查看当前白名单群组\n"
        help_text += "2. 添加白名单 群组名称：添加指定群组到白名单（支持群名称或群ID）\n"
        help_text += "3. 删除白名单 群组名称：从白名单中删除指定群组（支持群名称或群ID）\n"
        help_text += "4. 清空白名单：清空所有白名单群组\n\n"
        
        help_text += "群聊命令：\n"
        help_text += "1. 添加本群到白名单：将当前群组添加到白名单\n"
        help_text += "2. 从白名单删除本群：将当前群组从白名单中删除\n\n"
        
        help_text += "使用提示：\n"
        help_text += "- 使用群名称添加时，如果找到多个匹配项，会列出所有匹配的群组\n"
        help_text += "- 使用群名称删除时，如果找到多个匹配项，会优先显示在白名单中的群组\n"
        help_text += "- 如果群名称不唯一或模糊，可以使用群ID进行精确添加或删除\n"
        
        reply.content = help_text.strip()
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_add_current_group(self, e_context, msg):
        """添加当前群组到白名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            group_id = msg.other_user_id
            group_name = msg.other_user_nickname
            
            if group_id in self.white_group_list:
                reply.content = f"群组「{group_name}」已在白名单中。"
            else:
                self.white_group_list.append(group_id)
                # 保存配置
                self._save_config()
                reply.content = f"已成功将群组「{group_name}」(ID: {group_id}) 添加到白名单。"
        except Exception as e:
            logger.error(f"[donotlazy] 添加当前群组异常：{e}")
            logger.exception(e)
            reply.content = f"添加当前群组失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_remove_current_group(self, e_context, msg):
        """从白名单中删除当前群组"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            group_id = msg.other_user_id
            group_name = msg.other_user_nickname
            
            if group_id not in self.white_group_list:
                reply.content = f"群组「{group_name}」不在白名单中。"
            else:
                self.white_group_list.remove(group_id)
                # 保存配置
                self._save_config()
                reply.content = f"已成功将群组「{group_name}」(ID: {group_id}) 从白名单中删除。"
        except Exception as e:
            logger.error(f"[donotlazy] 删除当前群组异常：{e}")
            logger.exception(e)
            reply.content = f"删除当前群组失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _find_group_by_name(self, group_name):
        """根据群名称查找对应的群ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 使用LIKE进行模糊匹配
                cursor.execute('''
                    SELECT DISTINCT group_id, other_user_nickname
                    FROM message_records 
                    WHERE other_user_nickname LIKE ?
                    ORDER BY create_time DESC
                ''', (f'%{group_name}%',))
                
                matched_groups = cursor.fetchall()
                
                if matched_groups:
                    # 返回匹配到的群组ID和名称列表
                    return [(group_id, name) for group_id, name in matched_groups]
                else:
                    return []
        except Exception as e:
            logger.error(f"[donotlazy] 根据群名称查找群ID异常：{e}")
            logger.exception(e)
            return []
    
    def _process_non_text_message(self, msg):
        """处理非文本消息，如视频消息等"""
        try:
            msg_type = getattr(msg, "msg_type", "unknown")
            sender_name = getattr(msg, "actual_user_nickname", "unknown")
            logger.info(f"[donotlazy] 处理非文本消息，类型: {msg_type}, 发送者: {sender_name}")
            
            # 确保消息有必要的属性
            if not hasattr(msg, 'other_user_id'):
                logger.error(f"[donotlazy] 消息对象缺少other_user_id属性，无法处理")
                return
                
            # 不是群消息则跳过
            if not getattr(msg, "is_group", False) and not hasattr(msg, "is_group"):
                logger.info(f"[donotlazy] 不是群消息，跳过处理")
                return
                
            # 如果白名单不为空，且当前群组不在白名单中，则不处理
            if self.white_group_list and msg.other_user_id not in self.white_group_list:
                logger.info(f"[donotlazy] 群组 {msg.other_user_id} 不在白名单中，跳过处理")
                return
                
            # 自动清理过期数据
            self._clean_expired_records()
            
            # 记录非文本消息
            group_id = msg.other_user_id
            
            # 记录消息到数据库
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                    date_str = now.strftime('%Y-%m-%d')
                    
                    # 构建消息内容
                    if msg_type == 43:
                        content = f"[视频消息]"
                    elif msg_type == 3:
                        content = f"[图片消息]"
                    elif msg_type == 47:
                        content = f"[表情消息]"
                    elif msg_type == 49:
                        content = f"[链接消息]"
                    else:
                        content = f"[未知类型消息: {msg_type}]"
                    
                    # 插入记录，包含群名称
                    cursor.execute('''
                        INSERT INTO message_records 
                        (group_id, message_content, create_time, create_date, other_user_nickname)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        group_id,
                        content,
                        time_str,
                        date_str,
                        getattr(msg, 'other_user_nickname', '')
                    ))
                    conn.commit()
                    logger.info(f"[donotlazy] 已记录非文本消息，群组: {group_id}, 发送者: {sender_name}, 类型: {content}")
            except Exception as e:
                logger.error(f"[donotlazy] 记录非文本消息异常: {e}")
                logger.exception(e)
            
            # 记录发送者已读状态
            logger.info(f"[donotlazy] 将非文本消息发送者 {sender_name} 标记为已读")
            self._record_read_status(msg, sender_name)
            
        except Exception as e:
            logger.error(f"[donotlazy] 处理非文本消息异常: {e}")
            logger.exception(e) 
