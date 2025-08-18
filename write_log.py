import json
import sys
import inspect
from datetime import datetime
import os
import re

class PrettyJSONEncoder(json.JSONEncoder):
    """自定义JSON编码器，确保正确序列化输出内容"""
    def default(self, obj):
        """处理特殊对象的序列化"""
        return super(PrettyJSONEncoder, self).default(obj)
    
    def encode(self, obj):
        """确保换行符和特殊字符正确序列化"""
        return super().encode(obj)

def extract_device_name_from_prompt(prompt):
    """
    从提示符中提取设备名，优先获取<设备名>格式中的名称
    Args:
        prompt (str): 设备提示符
    Returns:
        str: 提取的设备名称，如果无法提取则返回config
    """
    # 优先从<设备名>格式提取
    if '<' in prompt and '>' in prompt:
        try:
            # 提取<>之间的内容
            device_name = prompt.split('<')[1].split('>')[0]
            return device_name
        except:
            pass
    
    # 如果没有<设备名>格式，则返回config作为默认值
    return "config"

def write_log(status, commands, system_info, error_message=None, device_name=None, file_suffix=None, 
             isis_peer_status=None, ospf_peer_status=None, vrrp_status=None, ping_connectivity=None, bgp_peer_status=None,
             vxlan_tunnel_status=None, vxlan_connectivity=None, dhcp_functionality=None):
    """
    写入执行日志
    Args:
        status (str): 执行状态
        commands (dict/str/list): 执行命令的回显结果
        system_info (dict/str): 设备系统信息
        error_message (str, optional): 程序运行返回的具体错误信息
        device_name (str, optional): 当commands或system_info不是字典时使用的设备标识
        file_suffix (str, optional): 指定文件名后缀，默认使用status值
        isis_peer_status (str, optional): ISIS邻居状态
        ospf_peer_status (str, optional): OSPF邻居状态  # 新增参数说明
        vrrp_status (str, optional): VRRP状态
        ping_connectivity (dict, optional): PING连通性测试结果
        bgp_peer_status (str, optional): BGP邻居状态
        vxlan_tunnel_status (str, optional): VXLAN隧道状态
        vxlan_connectivity (dict, optional): VXLAN连通性测试结果
        dhcp_functionality (str, optional): DHCP功能状态
    """
    try:
        # 状态值转换 - 将老的"succeed"状态转换为新的"Completed"状态
        if status.lower() == "succeed":
            status = "Completed"
        
        # 确保状态值为合法值
        valid_statuses = ["Running", "Completed", "Failed"]
        if status not in valid_statuses:
            print(f"警告: 无效的状态值 '{status}'，使用 'Running' 代替")
            status = "Running"
        
        # 获取设备标识 - 修改后的逻辑
        if device_name is None:
            # 尝试从调用者参数中获取设备标识
            frame = sys._getframe(1)
            try:
                args_info = inspect.getargvalues(frame)
                
                # 先查找SSH连接对象，尝试从提示符中提取设备名
                if 'ssh' in args_info.locals and args_info.locals['ssh']:
                    ssh = args_info.locals['ssh']
                    prompt = ssh.find_prompt()
                    extracted_name = extract_device_name_from_prompt(prompt)
                    if extracted_name:
                        device_name = extracted_name
                        # 找到后直接使用，不继续查找
                        
                # 如果没有从提示符提取到，再查找net_connect对象
                elif not device_name and 'net_connect' in args_info.locals and args_info.locals['net_connect']:
                    net_connect = args_info.locals['net_connect']
                    prompt = net_connect.find_prompt()
                    extracted_name = extract_device_name_from_prompt(prompt)
                    if extracted_name:
                        device_name = extracted_name
                
                # 如果仍未找到，尝试使用hostip或host参数
                if not device_name:
                    if 'hostip' in args_info.locals:
                        device_name = args_info.locals['hostip']
                    elif 'host' in args_info.locals:
                        device_name = args_info.locals['host']
                    else:
                        device_name = "config"  # 修改默认值为config
            except:
                device_name = "config"
        
        # 处理commands参数 - 转换为字典格式
        result_dict = {}

        if isinstance(commands, dict):
            # 如果已经是字典格式，处理每个值
            for key, value in commands.items():
                if isinstance(value, str) and '\n' in value:
                    # 将包含换行符的字符串转换为列表 - 增加智能过滤和提示符保留
                    lines = value.split('\n')
                    filtered_lines = []
                    
                    # 定义模式：只包含提示符的行
                    empty_prompt_pattern = r'^\s*(\[[\w\-\.]+(?:\-[\w\/\.]+)?\]|<[\w\-\.]+>)\s*$'
                    # 定义模式：有效的命令行(带提示符)
                    command_pattern = r'^\s*(\[[\w\-\.]+(?:\-[\w\/\.]+)?\]|<[\w\-\.]+>)(.*?)$'
                    
                    current_prompt = ""  # 记录当前提示符
                    
                    for line in lines:
                        # 跳过空行
                        if not line.strip():
                            continue
                            
                        # 检查是否是只包含提示符的行
                        if re.match(empty_prompt_pattern, line):
                            current_prompt = line.strip()  # 记录当前提示符，但不添加到结果中
                            continue
                            
                        # 检查是否是带提示符的命令行
                        cmd_match = re.match(command_pattern, line)
                        if cmd_match:
                            # 如果是带提示符的命令行，直接添加
                            filtered_lines.append(line.strip())
                            # 更新当前提示符
                            current_prompt = cmd_match.group(1)
                            continue
                            
                        # 如果是普通命令行(不带提示符)，但我们有之前保存的提示符
                        if current_prompt and not re.search(r'^\s*(\[|\<)', line):
                            # 为命令加上提示符
                            filtered_lines.append(f"{current_prompt}{line.strip()}")
                        else:
                            # 其他情况，保留原始行
                            filtered_lines.append(line.strip())
                    
                    result_dict[key] = filtered_lines
                else:
                    result_dict[key] = value
        elif isinstance(commands, list):
            # 处理列表类型命令集合
            filtered_commands = []
            prompt_pattern = r'^\s*(\[[\w\-\.]+(?:\-[\w\/\.]+)?\]|<[\w\-\.]+>)\s*$'
            
            for cmd in commands:
                # 处理字典格式的命令（包含command和output）
                if isinstance(cmd, dict):
                    if 'output' in cmd:
                        cmd_text = cmd['output']
                    elif 'command' in cmd:
                        cmd_text = cmd['command']
                    else:
                        cmd_text = str(cmd)
                else:
                    # 处理字符串格式的命令
                    cmd_text = cmd
                
                # 检查是否为空或None
                if not cmd_text or (isinstance(cmd_text, str) and not cmd_text.strip()):
                    continue
                    
                # 如果是字符串，检查是否只包含提示符
                if isinstance(cmd_text, str) and re.match(prompt_pattern, cmd_text.strip()):
                    continue
                    
                filtered_commands.append(cmd_text)
            
            result_dict[device_name] = filtered_commands
        else:
            # 字符串或其他类型，使用设备名称作为键
            if isinstance(commands, str) and '\n' in commands:
                # 将包含换行符的字符串转换为列表 - 增加过滤逻辑
                lines = commands.split('\n')
                filtered_lines = []
                prompt_pattern = r'^\s*(\[[\w\-\.]+(?:\-[\w\/\.]+)?\]|<[\w\-\.]+>)\s*$'
                
                for line in lines:
                    # 跳过空行
                    if not line.strip():
                        continue
                    # 跳过只包含提示符的行
                    if re.match(prompt_pattern, line):
                        continue
                    filtered_lines.append(line)
                
                result_dict[device_name] = filtered_lines
            else:
                result_dict[device_name] = commands
        
        # 处理system_info参数 - 转换为字典格式，同时处理字符串转列表
        system_info_dict = {}
        
        if isinstance(system_info, dict):
            # 如果已经是字典格式，处理每个值
            for key, value in system_info.items():
                if isinstance(value, str) and '\n' in value:
                    # 将包含换行符的字符串转换为列表 - 过滤空行
                    system_info_dict[key] = [line for line in value.split('\n') if line.strip()]
                else:
                    system_info_dict[key] = value
        else:
            # 字符串或其他类型，使用设备名称作为键
            if isinstance(system_info, str) and '\n' in system_info:
                # 将包含换行符的字符串转换为列表 - 过滤空行
                system_info_dict[device_name] = [line for line in system_info.split('\n') if line.strip()]
            else:
                system_info_dict[device_name] = system_info
        
        # 构建日志数据
        log_data = {
            "status": status,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "result": result_dict,
            "system_info": system_info_dict
        }

        # 如果提供了错误信息，将其添加到result字典作为独立的键值对
        if error_message:
            # 直接作为一个新的键值对添加到result字典中
            result_dict["error_message"] = error_message

        # 处理BGP邻居状态
        if bgp_peer_status is not None:
            result_dict["bgp_peer_status"] = bgp_peer_status
        
        # 处理OSPF邻居状态
        if ospf_peer_status is not None:
            result_dict["ospf_peer_status"] = ospf_peer_status
            
        # 如果提供了isis_peer_status，将其添加到result字典作为独立的键值对
        if isis_peer_status is not None:
            result_dict["isis_peer_status"] = isis_peer_status
            # print(f"✓ 已添加isis_peer_status到result_dict: {isis_peer_status}")

        if ping_connectivity is not None:
                if isinstance(ping_connectivity, dict):
                    result_dict["ping_connectivity"] = ping_connectivity
        #     print(f"✓ (write_log) 已添加ping_connectivity到result_dict: '{ping_connectivity}'")
        # elif ping_connectivity is None:
        #     print(f"✗ (write_log) ping_connectivity 参数值为 None，未添加到result_dict")
        # elif ping_connectivity == "":
        #     print(f"✗ (write_log) ping_connectivity 参数值为空字符串，未添加到result_dict")
        # else:
        #     # 理论上不应该到这里，但作为备用
        #     print(f"✗ (write_log) ping_connectivity 参数值 ('{ping_connectivity}') 未满足添加条件，未添加到result_dict")

        if vrrp_status is not None:
            result_dict["vrrp_status"] = vrrp_status
            # print(f"✓ 已添加vrrp_status到result_dict: {vrrp_status}")

        # 处理VXLAN隧道状态
        if vxlan_tunnel_status is not None:
            result_dict["vxlan_tunnel_status"] = vxlan_tunnel_status
            
        # 处理VXLAN连通性测试结果
        if vxlan_connectivity is not None:
            result_dict["vxlan_connectivity"] = vxlan_connectivity

        # 处理DHCP功能状态
        if dhcp_functionality is not None:
            result_dict["dhcp_functionality"] = dhcp_functionality

        # print(f"最终result_dict的键: {list(result_dict.keys())}")
        # if 'ping_connectivity' in result_dict:
        #     print(f"result_dict中的ping_connectivity值: {result_dict['ping_connectivity']}")

        # 获取调用链中的主模块（不是库模块的最外层调用者）
        frame = sys._getframe(1)
        module_name = None
        
        # 向上遍历调用栈，找到第一个不是标准库和不是我们自己工具库的模块
        while frame:
            calling_script = os.path.basename(frame.f_code.co_filename)
            current_module = os.path.splitext(calling_script)[0]
            
            # 过滤掉无效的模块名
            if current_module == "<string>" or current_module == "<stdin>":
                frame = frame.f_back
                continue
            
            # 如果是主调用脚本，使用它的名称
            if current_module.endswith("_TEST") or frame.f_globals.get('__name__') == '__main__':
                module_name = current_module
                break
                
            # 尝试查找上一级调用
            frame = frame.f_back
            
        # 如果没有找到主模块，就使用直接调用者
        if not module_name:
            frame = sys._getframe(1)
            calling_script = os.path.basename(frame.f_code.co_filename)
            current_module = os.path.splitext(calling_script)[0]
            
            # 如果仍然是无效的模块名，使用默认值
            if current_module in ["<string>", "<stdin>", ""]:
                module_name = "write_log_test"
            else:
                module_name = current_module
        
        # 日志目录为 result\temp
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result", "temp")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 统一日志文件名格式 - 始终使用{模块名}_status.log格式
        log_filename = os.path.join(log_dir, f"{module_name}_status.log")
        
        # 使用JSON格式保存，确保字符串正确序列化
        with open(log_filename, "w", encoding="utf-8") as f:
            # 直接使用json.dump而不是转换后写入
            json.dump(log_data, f, indent=4, ensure_ascii=False, cls=PrettyJSONEncoder)
            
        if status != "Running":
            print(f"\n日志已保存至: {log_filename}")
            
        return log_filename
        
    except Exception as e:
        print(f"\n写入日志失败: {str(e)}")
        return None