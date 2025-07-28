from jinja2 import Environment, FileSystemLoader
import os
import sys
import json
import time
import re

# 添加当前目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# 导入自定义模块
import login_args
import check_device_output
import get_system_info
import write_log

# 全局变量
log_recorded = False

def detect_loopback_interface(interface_name):
    """
    自动检测是否为环回口
    根据接口名称判断：以l、lo、loo、loop开头的都是环回口（不区分大小写）
    """
    interface_name_lower = interface_name.lower()
    loopback_prefixes = ['l', 'lo', 'loo', 'loop', 'loopback']
    
    for prefix in loopback_prefixes:
        if interface_name_lower.startswith(prefix):
            return True
    return False

def process_interfaces(interfaces):
    """
    处理接口列表，自动检测接口类型并添加is_loopback字段
    """
    processed_interfaces = []
    
    for intf in interfaces:
        # 创建接口副本，避免修改原始数据
        processed_intf = intf.copy()
        
        # 自动检测是否为环回口
        processed_intf['is_loopback'] = detect_loopback_interface(intf['name'])
        processed_interfaces.append(processed_intf)
    
    return processed_interfaces

def extract_device_name(net_connect):
    """从SSH连接中提取设备名，优先使用<设备名>格式"""
    if not net_connect:
        print("警告: SSH连接为空，无法提取设备名称，使用默认值'config'")
        return "config"
    
    try:
        prompt = net_connect.find_prompt()
        
        # 优先从<设备名>格式提取 - H3C设备常用格式
        if '<' in prompt and '>' in prompt:
            try:
                device_name = prompt.split('<')[1].split('>')[0]
                return device_name
            except Exception as e:
                print(f"从<设备名>格式提取设备名失败: {str(e)}")
        
        # 尝试从[设备名]格式提取 - 系统视图下的格式
        elif '[' in prompt and ']' in prompt:
            try:
                device_name = prompt.split('[')[1].split(']')[0]
                print(f"成功从[设备名]格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从[设备名]格式提取设备名失败: {str(e)}")
        
        # 尝试直接使用提示符作为设备名 - 去除特殊字符
        else:
            clean_prompt = prompt.strip('<>[]')
            if clean_prompt:
                print(f"未找到标准格式，尝试使用清理后的提示符: '{clean_prompt}'")
                if ':' in clean_prompt:
                    # 如果包含冒号，取冒号前的部分
                    device_name = clean_prompt.split(':')[0]
                    print(f"从提示符中提取设备名: '{device_name}'")
                    return device_name
                return clean_prompt
        
        # 如果所有方法都失败，使用config作为默认值
        print(f"警告: 无法从提示符'{prompt}'提取设备名，使用默认值'config'")
        return "config"
    except Exception as e:
        print(f"提取设备名时出现意外错误: {str(e)}")
        return "config"

def get_system_info_for_log(ssh_connection, device_name):
    """获取用于日志记录的系统信息，直接返回版本信息字符串"""
    try:
        ssh_connection.clear_buffer()
        version_output = get_system_info.get_system_info(ssh_connection)
        
        # 清理system_info中的多余设备名称
        cleaned_version_output = clean_system_info(version_output, device_name)
        
        return cleaned_version_output or "未能获取到版本信息"
    except Exception as e:
        return f"获取版本信息失败: {str(e)}"

def clean_system_info(system_info, device_name):
    """清理系统信息，移除多余的设备名称显示"""
    if isinstance(system_info, dict):
        cleaned_info = {}
        for key, value in system_info.items():
            if isinstance(value, str):
                # 移除多余的提示符和换行
                cleaned_value = re.sub(r'\n*<[^>]+>\n*', '', value)
                cleaned_value = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned_value)
                # 移除display version命令回显
                cleaned_value = re.sub(r'display\s+version\n*', '', cleaned_value, flags=re.IGNORECASE)
                # 移除多余的换行符
                cleaned_value = re.sub(r'\n+', '\n', cleaned_value)
                cleaned_value = cleaned_value.strip()
                if cleaned_value:  # 只保留非空内容
                    cleaned_info[key] = cleaned_value
        return cleaned_info
    elif isinstance(system_info, str):
        # 清理字符串格式
        cleaned = re.sub(r'\n*<[^>]+>\n*', '', system_info)
        cleaned = re.sub(r'\n*\[[^\]]+\]\n*', '', cleaned)
        # 移除display version命令回显
        cleaned = re.sub(r'display\s+version\n*', '', cleaned, flags=re.IGNORECASE)
        # 移除多余的换行符
        cleaned = re.sub(r'\n+', '\n', cleaned)
        
        return cleaned.strip()
    else:
        return system_info

def generate_interface_config(interface_vars):
    """生成接口IP配置"""
    parent_dir = os.path.dirname(os.path.dirname(__file__))
    templates_dir = os.path.join(parent_dir, 'templates')
    
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        cache_size=0,
        auto_reload=True
    )
    
    try:
        # 加载接口配置模板
        template = env.get_template('interface_base_config_template.j2')
        
        # 渲染模板
        result = template.render(**interface_vars)
        return result.rstrip()
    except Exception as e:
        print(f"接口配置渲染错误: {e}")
        import traceback
        traceback.print_exc()
        return f"接口配置渲染失败: {str(e)}"

def generate_ospf_config(ospf_vars):
    """生成OSPF配置""" 
    parent_dir = os.path.dirname(os.path.dirname(__file__))
    templates_dir = os.path.join(parent_dir, 'templates')
    
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        cache_size=0,
        auto_reload=True
    )
    
    try:
        # 加载OSPF配置模板
        template = env.get_template('ospf_base_config_template.j2')
        
        # 渲染模板
        result = template.render(**ospf_vars)
        return result.rstrip()
    except Exception as e:
        print(f"OSPF配置渲染错误: {e}")
        import traceback
        traceback.print_exc()
        return f"OSPF配置渲染失败: {str(e)}"

def generate_complete_config(all_vars):
    """生成完整的网络配置（接口 + OSPF）"""
    
    # 处理接口列表，自动检测接口类型
    processed_interfaces = process_interfaces(all_vars.get("interfaces", []))
    
    # 为接口模板准备参数
    interface_vars = {
        "interfaces": processed_interfaces,
        "ospf_stack": all_vars.get("ospf_stack")
    }
    
    # 为OSPF模板准备参数
    ospf_vars = {
        "process_id": all_vars.get("process_id"),
        "router_id": all_vars.get("router_id"),
        "area": all_vars.get("area"),
        "ospf_stack": all_vars.get("ospf_stack"),
        "interfaces": processed_interfaces
    }
    
    # 生成接口配置
    interface_config = generate_interface_config(interface_vars)
    
    # 生成OSPF配置
    ospf_config = generate_ospf_config(ospf_vars)
    
    # 智能合并配置，检查是否需要添加system-view
    if interface_config.strip().startswith('system-view'):
        # 接口模板已包含system-view，直接合并
        complete_config = interface_config + "\n\n" + ospf_config
    else:
        # 接口模板不包含system-view，需要添加
        complete_config = "system-view\n\n" + interface_config + "\n\n" + ospf_config
    
    return complete_config

def parse_json_input(json_string):
    """解析命令行传入的JSON字符串"""
    try:
        # 解析JSON字符串
        data = json.loads(json_string)
        
        return data
    except json.JSONDecodeError as e:
        print(f"JSON格式错误: {e}")
        print("请检查JSON字符串格式是否正确")
        return None

def create_template_vars_from_input(input_data):
    """根据输入数据创建模板变量"""

    # 获取hostip作为默认router_id
    default_router_id = input_data.get("hostip", "").split(',')[0].strip() if input_data.get("hostip") else None
    # 将输入数据转换为标准的模板变量格式
    template_vars = {
        "process_id": input_data.get("process_id", "100"),
        "router_id": input_data.get("router_id", default_router_id),
        "area": input_data.get("area", "0.0.0.0"),
        "ospf_stack": input_data.get("ospf_stack", "IPv4&IPv6"),
        "interfaces": input_data.get("interfaces", [])
    }
    
    return template_vars

def parse_connection_params(hostip, username, password):
    """解析连接参数，支持多设备"""
    try:
        # 分割IP地址、用户名和密码
        ips = [ip.strip() for ip in hostip.split(',')]
        usernames = [user.strip() for user in username.split(',')]
        passwords = [pwd.strip() for pwd in password.split(',')]
        
        # 参数数量检查
        if len(usernames) == 1:
            usernames = usernames * len(ips)
        if len(passwords) == 1:
            passwords = passwords * len(ips)
            
        if not (len(ips) == len(usernames) == len(passwords)):
            print("错误: IP地址、用户名、密码的数量不匹配")
            return None
        
        # 构建连接参数列表
        connection_params = []
        for i, ip in enumerate(ips):
            if not login_args.check_ip(ip):
                print(f"错误: IP地址格式不正确 - {ip}")
                continue
                
            connection_params.append({
                'hostip': ip,
                'username': usernames[i],
                'password': passwords[i]
            })
        
        return connection_params
        
    except Exception as e:
        print(f"解析连接参数时出错: {e}")
        return None

def get_device_prompt(net_connect):
    """获取设备的当前提示符"""
    try:
        # 发送空命令获取当前提示符
        prompt = net_connect.send_command('', expect_string=r'[<>\[\]#]', strip_prompt=False, strip_command=False)
        # 提取提示符（去除命令和多余的换行）
        lines = prompt.strip().split('\n')
        for line in reversed(lines):  # 从最后一行开始查找
            line = line.strip()
            # 检查是否包含设备提示符格式
            if line and (
                (line.startswith('<') and line.endswith('>')) or  # <H3C>
                (line.startswith('[') and line.endswith(']')) or  # [H3C] 或 [H3C-GigabitEthernet0/2]
                line.endswith('#')  # 特权模式
            ):
                return line
        return None
    except Exception as e:
        print(f"获取提示符失败: {e}")
        return None

def verify_login(connection_params):
    """验证登录，使用login_args模块"""
    login_results = []
    
    for params in connection_params:
        print(f"正在测试连接到 {params['hostip']}...")
        
        try:
            # 使用login_args.run_script进行登录测试
            net_connect = login_args.run_script(params)
            
            if net_connect:
                # 获取设备提示符和设备名
                device_prompt = get_device_prompt(net_connect)
                device_name = extract_device_name(net_connect)
                
                # 登录成功，立即断开连接
                net_connect.disconnect()
                
                login_results.append({
                    'host': params['hostip'],
                    'status': 'success',
                    'message': '登录成功',
                    'device_prompt': device_prompt,
                    'device_name': device_name
                })
            else:
                login_results.append({
                    'host': params['hostip'],
                    'status': 'failed',
                    'message': '登录失败'
                })
                
        except Exception as e:
            login_results.append({
                'host': params['hostip'],
                'status': 'failed',
                'message': f'连接异常: {str(e)}'
            })
    
    return login_results

def send_config_to_devices(config_commands, connection_params):
    """将配置下发到设备"""
    results = []
    
    for params in connection_params: 
        print(f"\n开始配置设备: {params['hostip']}")
        print("=" * 50)
        
        try:
            # 建立连接
            net_connect = login_args.run_script(params)
            
            if not net_connect:
                results.append({
                    'host': params['hostip'],
                    'status': 'failed',
                    'message': '无法建立连接'
                })
                continue
            
            try:
                # 获取设备提示符和设备名
                device_prompt = get_device_prompt(net_connect)
                device_name = extract_device_name(net_connect)
                
                if device_prompt:
                    print(f"设备名称: {device_name}")
              
                # 获取系统信息
                system_info = get_system_info_for_log(net_connect, device_name)
                
                # 将配置按行分割
                config_lines = config_commands.strip().split('\n')
                
                # 过滤掉空行
                config_lines = [line.strip() for line in config_lines if line.strip()]
                
                print(f"配置命令总数: {len(config_lines)}")
                print("-" * 50)
                
                # 执行命令记录列表
                executed_commands = []
                
                # 逐行发送配置
                success_commands = 0
                failed_commands = 0
                current_prompt = device_prompt  # 跟踪当前提示符
                
                for command in config_lines:
                    if command:
                        try:
                            # 发送命令并获取输出
                            output = net_connect.send_command(command, expect_string=r'[<>\[\]#]', strip_prompt=False, strip_command=False)
                            
                            # 显示命令（带提示符）
                            if current_prompt:
                                print(f"{current_prompt}{command}")
                            else:
                                print(f"{command}")
                            
                            # 检查命令执行结果
                            status = check_device_output.check_device_output(output)
                            if status == "Failed":
                                failed_commands += 1
                                error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"
                                print(f"\n错误: {error_message}")
                                
                                # 记录失败的命令
                                executed_commands.append({
                                    "command": command, 
                                    "output": f"{current_prompt}{command} {output.strip()}"
                                })
                                
                                # 断开连接并返回失败状态
                                if net_connect:
                                    net_connect.disconnect()
                                
                                results.append({
                                    'host': params['hostip'],
                                    'status': 'failed',
                                    'message': error_message,
                                    'success_count': success_commands,
                                    'failed_count': failed_commands,
                                    'total_count': len(config_lines),
                                    'device_prompt': device_prompt,
                                    'device_name': device_name,
                                    'executed_commands': executed_commands,
                                    'system_info': system_info
                                })
                                
                                return results
                            else:
                                success_commands += 1
                            
                            # 处理设备回显
                            if output.strip():
                                # 过滤掉命令本身和提示符，只显示有意义的回显
                                output_lines = output.strip().split('\n')
                                filtered_output = []
                                new_prompt = None
                                
                                for line in output_lines:
                                    line = line.strip()
                                    
                                    # 检查是否是新的提示符
                                    if line and (
                                        (line.startswith('<') and line.endswith('>')) or  # <H3C>
                                        (line.startswith('[') and line.endswith(']')) or  # [H3C] 或 [H3C-GigabitEthernet0/2]
                                        line.endswith('#')  # 特权模式
                                    ):
                                        new_prompt = line
                                        continue  # 跳过提示符，不显示
                                    
                                    # 跳过命令本身和空行
                                    if line and line != command and line != current_prompt:
                                        filtered_output.append(line)
                                
                                # 只显示有内容的回显
                                if filtered_output:
                                    print('\n'.join(filtered_output))
                                
                                # 更新当前提示符
                                if new_prompt:
                                    current_prompt = new_prompt
                                else:
                                    # 如果没有从输出中找到新提示符，尝试重新获取
                                    try:
                                        temp_prompt = get_device_prompt(net_connect)
                                        if temp_prompt:
                                            current_prompt = temp_prompt
                                    except:
                                        pass
                            
                            # 记录执行的命令
                            executed_commands.append({
                                "command": command, 
                                "output": f"{current_prompt if current_prompt else ''}{command}{' ' + ' '.join(filtered_output) if filtered_output else ''}"
                            })
                                
                        except Exception as cmd_e:
                            failed_commands += 1
                            if current_prompt:
                                print(f"{current_prompt}{command}")
                            else:
                                print(f"{command}")
                            print(f"命令执行异常: {str(cmd_e)}")
                            
                            executed_commands.append({
                                "command": command, 
                                "output": f"{current_prompt if current_prompt else ''}{command} - 执行异常: {str(cmd_e)}"
                            })
                
                print("-" * 50)
                
                # 记录结果
                if failed_commands == 0:
                    status_msg = f'配置下发成功 ({success_commands}/{len(config_lines)})'
                    status = 'success'
                elif success_commands > 0:
                    status_msg = f'部分配置下发成功 ({success_commands}/{len(config_lines)}，失败 {failed_commands})'
                    status = 'partial'
                else:
                    status_msg = f'配置下发失败 (失败 {failed_commands}/{len(config_lines)})'
                    status = 'failed'
                
                results.append({
                    'host': params['hostip'],
                    'status': status,
                    'message': status_msg,
                    'success_count': success_commands,
                    'failed_count': failed_commands,
                    'total_count': len(config_lines),
                    'device_prompt': device_prompt,
                    'device_name': device_name,
                    'executed_commands': executed_commands,
                    'system_info': system_info
                })
                
            except Exception as config_e:
                results.append({
                    'host': params['hostip'],
                    'status': 'failed',
                    'message': f'配置下发过程异常: {str(config_e)}'
                })
                print(f"配置下发异常: {str(config_e)}")
            
            finally:
                # 断开连接
                try:
                    net_connect.disconnect()
                except:
                    pass
                
        except Exception as e:
            results.append({
                'host': params['hostip'],
                'status': 'failed',
                'message': f'连接异常: {str(e)}'
            })
            print(f"连接异常: {str(e)}")
    
    return results

def process_ospf_deployment(input_data):
    """处理OSPF配置部署的完整流程"""
    global log_recorded
    
    print("OSPF配置生成与部署")
    
    hostip = input_data.get("hostip", "")
    username = input_data.get("username", "")
    password = input_data.get("password", "")
    
    if not all([hostip, username, password]):
        error_msg = "错误: 缺少必要的登录参数 (hostip, username, password)"
        print(error_msg)
        return False
    
    # 解析连接参数
    connection_params = parse_connection_params(hostip, username, password)
    
    if not connection_params:
        error_msg = "错误: 连接参数解析失败"
        print(error_msg)
        return False
    
    # 验证登录
    login_results = verify_login(connection_params)
    
    # 检查登录结果
    success_devices = []
    for result in login_results:
        if result['status'] == 'success':
            success_devices.append(result['host'])
            device_prompt = result.get('device_prompt', '未知')
            device_name = result.get('device_name', '未知')
            print(f"{result['host']} 登录成功，设备提示符: {device_prompt}，设备名: {device_name}")
        else:
            print(f"{result['host']} 登录失败: {result['message']}")
    
    if not success_devices:
        error_msg = "所有设备登录失败，终止操作"
        print(error_msg)
        return False
    
    # 过滤出成功登录的设备参数
    valid_connection_params = [params for params in connection_params 
                              if params['hostip'] in success_devices]
    
    # 生成配置
    print("生成OSPF配置")
    
    template_vars = create_template_vars_from_input(input_data)
    
    try:
        complete_config = generate_complete_config(template_vars)
        print("生成的完整配置:")
        print("=" * 50)
        print(complete_config)
        print("=" * 50)
        
    except Exception as e:
        error_msg = f"配置生成失败: {e}"
        print(error_msg)
        return False
    
    deploy_results = send_config_to_devices(complete_config, valid_connection_params)
    
    # 显示结果和记录日志
    all_success = True
    all_executed_commands = {}
    all_system_info = {}
    error_messages = []
    
    for result in deploy_results:
        if result['status'] == 'success':
            print(f"{result['host']}: 配置下发成功")
        elif result['status'] == 'partial':
            print(f"{result['host']}: 部分配置下发成功")
            all_success = False
        else:
            print(f"{result['host']}: 配置下发失败")
            all_success = False
            error_messages.append(f"{result['host']}: {result['message']}")
        
        # 收集执行命令和系统信息
        device_name = result.get('device_name', result['host'])
        if 'executed_commands' in result:
            all_executed_commands[device_name] = result['executed_commands']
        if 'system_info' in result:
            all_system_info[device_name] = result['system_info']
    
    # 格式化命令输出
    result_format = {}
    for device_name, commands in all_executed_commands.items():
        full_output = []
        for cmd_entry in commands:
            if isinstance(cmd_entry, dict):
                cmd_output = cmd_entry.get("output", "")
                if cmd_output:
                    full_output.append(cmd_output)
        
        if full_output:
            result_format[device_name] = "\n".join(full_output)
    
    # 记录最终日志 - 只记录一次
    final_status = "Completed" if all_success else "Failed"
    final_error_msg = "\n".join(error_messages) if error_messages else None
    
    try:
        log_path = write_log.write_log(
            final_status, 
            result_format, 
            all_system_info, 
            final_error_msg,
            file_suffix="ospf_config_status"
        )
        
        if log_path:
            print(f"\n日志已保存至: {log_path}")
    except Exception as log_e:
        print(f"日志记录失败: {log_e}")
    
    return all_success

def show_usage():
    """显示使用说明"""
    usage_example = '''
使用方法:
python OSPF_BASE_CONFIG_TEST.py '{"hostip":"192.168.56.10","username":"admin","password":"admin123","process_id":"100","area":"0.0.0.0","ospf_stack":"IPv4","interfaces":[{"name":"GigabitEthernet1/0/1","ip_address":"192.168.1.1","mask":"255.255.255.0","network_type":"p2p","ipv4_cost":"10"}]}'

自定义router_id示例:
python OSPF_BASE_CONFIG_TEST.py '{"hostip":"192.168.56.10","username":"admin","password":"admin123","process_id":"100","router_id":"10.10.10.10","area":"0.0.0.0","ospf_stack":"IPv4","interfaces":[{"name":"GigabitEthernet1/0/1","ip_address":"192.168.1.1","mask":"255.255.255.0","network_type":"p2p","ipv4_cost":"10"}]}'

多设备示例:
python OSPF_BASE_CONFIG_TEST.py '{
    "hostip": "192.168.56.10,192.168.56.11",
    "username": "admin,admin",
    "password": "admin123,admin456",
    "process_id": "100",
    "area": "0.0.0.0",
    "ospf_stack": "IPv4",
    "interfaces": [
        {
            "name": "GigabitEthernet1/0/1",
            "ip_address": "192.168.1.1",
            "mask": "255.255.255.0",
            "network_type": "p2p",
            "ipv4_cost": "10"
        },
        {
            "name": "LoopBack9",
            "ip_address": "11.11.11.11",
            "mask": "255.255.255.255",
            "ipv4_cost": "5"
        }
    ]
}'

参数说明:
登录参数:
- hostip: 设备IP地址，多个用逗号分隔
- username: 用户名，多个用逗号分隔
- password: 密码，多个用逗号分隔

OSPF参数:
- process_id: OSPF进程ID (默认: 100)
- router_id: 路由器ID (默认使用第一个hostip地址，可自定义)
- area: OSPF区域 (默认: 0.0.0.0)
- ospf_stack: 协议栈类型 (IPv4, IPv6, IPv4&IPv6，默认: IPv4&IPv6)
- interfaces: 接口列表，每个接口包含:
  - name: 接口名称
  - ip_address: IPv4地址
  - mask: 子网掩码
  - ipv6_address: IPv6地址
  - ipv6_prefix: IPv6前缀长度
  - network_type: 网络类型 (p2p, broadcast等)
  - ipv4_cost: IPv4 OSPF开销
  - ipv6_cost: IPv6 OSPF开销

注意: 如果不指定router_id，系统会自动使用第一个hostip作为router_id
'''
    print(usage_example)

if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("错误: 请提供JSON参数")
        show_usage()
        sys.exit(1)
    
    # 获取JSON字符串参数
    json_input = sys.argv[1]
    
    # 解析JSON输入
    input_data = parse_json_input(json_input)
    
    if input_data is None:
        print("参数解析失败，退出程序")
        sys.exit(1)
    
    # 执行完整的OSPF部署流程
    try:
        success = process_ospf_deployment(input_data)
        
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        error_msg = f"程序运行时发生错误: {str(e)}"
        print(error_msg)
        sys.exit(1)