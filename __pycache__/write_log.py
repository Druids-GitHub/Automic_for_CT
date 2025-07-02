import json
import sys
from datetime import datetime
import os

def write_log(status, commands, system_info):
    """
    写入执行日志
    Args:
        status (str): 执行状态 ("succeed" 或 "Failed")
        commands (list): 执行的命令列表
        system_info (str): 设备版本信息
    """
    try:
        # 获取调用此函数的脚本文件名
        frame = sys._getframe(1)
        calling_script = os.path.basename(frame.f_code.co_filename)
        module_name = os.path.splitext(calling_script)[0]
        
        # 确保logs目录存在
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 构建日志数据
        log_data = {
            "status": status,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "result": commands,
            "system_info": system_info
        }
        
        # 生成日志文件名（使用调用模块的名称）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = os.path.join(log_dir, f"{module_name}_{timestamp}.log")
        
        # 写入日志文件
        with open(log_filename, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=4, ensure_ascii=False)
            
        print(f"\n日志已保存至: {log_filename}")
        
    except Exception as e:
        print(f"\n写入日志失败: {str(e)}")