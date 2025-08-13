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

def generate_interface_config(interface_vars):
    """生成接口配置"""
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
        template = env.get_template('bgp_interface_config_template.j2')
        result = template.render(**interface_vars)
        return result.rstrip()
    except Exception as e:
        print(f"接口配置渲染错误: {e}")
        import traceback
        traceback.print_exc()
        return f"接口配置渲染失败: {str(e)}"

def generate_loopback_config(loopback_vars):
    """生成环回口配置"""
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
        template = env.get_template('bgp_loopback_config_template.j2')
        result = template.render(**loopback_vars)
        return result.rstrip()
    except Exception as e:
        print(f"环回口配置渲染错误: {e}")
        import traceback
        traceback.print_exc()
        return f"环回口配置渲染失败: {str(e)}"

def generate_bgp_config(bgp_vars):
    """生成BGP配置"""
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
        template = env.get_template('bgp_base_config_template.j2')
        result = template.render(**bgp_vars)
        return result.rstrip()
    except Exception as e:
        print(f"BGP配置渲染错误: {e}")
        import traceback
        traceback.print_exc()
        return f"BGP配置渲染失败: {str(e)}"

def generate_complete_config(device_params):
    """生成完整的BGP配置（接口 + 环回口 + BGP）"""
    complete_config = "system-view\n\n"
    
    # 1. 生成接口配置
    if device_params.get('interfaces'):
        interface_vars = {
            "interfaces": device_params['interfaces']
        }
        interface_config = generate_interface_config(interface_vars)
        complete_config += interface_config + "\n\n"
    
    # 2. 生成环回口配置
    if device_params.get('create_loopback', True):
        loopback_vars = {
            "has_ipv4": device_params.get('has_ipv4', True),
            "has_ipv6": device_params.get('has_ipv6', False),
            "device_index": device_params.get('device_index', 0)
        }
        loopback_config = generate_loopback_config(loopback_vars)
        complete_config += loopback_config + "\n\n"
    
    # 3. 生成BGP配置
    bgp_vars = {
        "bgp_local_as": device_params.get('bgp_local_as', 100),
        "peer_ip": device_params.get('peer_ip'),
        "bgp_peer_as": device_params.get('bgp_peer_as', 100),
        "conn_interface": device_params.get('conn_interface'),
        "address_type": device_params.get('address_type'),
        "network_advertise": device_params.get('network_advertise'),
        "ipv6_peer_ip": device_params.get('ipv6_peer_ip'),
        "dual_stack": device_params.get('dual_stack', False)
    }
    bgp_config = generate_bgp_config(bgp_vars)
    complete_config += bgp_config + "\n\n"
    
    # 4. 退出系统视图
    complete_config += "quit"
    
    return complete_config

def extract_device_name(net_connect):
    """从SSH连接中提取设备名"""
    if not net_connect:
        print("警告: SSH连接为空，无法提取设备名称，使用默认值'config'")
        return "config"
    
    try:
        prompt = net_connect.find_prompt()
        print(f"正在从提示符提取设备名: '{prompt}'")
        
        if '<' in prompt and '>' in prompt:
            try:
                device_name = prompt.split('<')[1].split('>')[0]
                print(f"成功从<设备名>格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从<设备名>格式提取设备名失败: {str(e)}")
        
        elif '[' in prompt and ']' in prompt:
            try:
                device_name = prompt.split('[')[1].split(']')[0]
                print(f"成功从[设备名]格式提取到设备名: '{device_name}'")
                return device_name
            except Exception as e:
                print(f"从[设备名]格式提取设备名失败: {str(e)}")
        
        else:
            clean_prompt = prompt.strip('<>[]')
            if clean_prompt:
                print(f"未找到标准格式，尝试使用清理后的提示符: '{clean_prompt}'")
                if ':' in clean_prompt:
                    device_name = clean_prompt.split(':')[0]
                    print(f"从提示符中提取设备名: '{device_name}'")
                    return device_name
                return clean_prompt
        
        print(f"警告: 无法从提示符'{prompt}'提取设备名，使用默认值'config'")
        return "config"
    except Exception as e:
        print(f"提取设备名时出现意外错误: {str(e)}")
        return "config"

def get_system_info_for_log(ssh_connection, device_name):
    """获取用于日志记录的系统信息"""
    try:
        ssh_connection.clear_buffer()
        version_output = get_system_info.get_system_info(ssh_connection)
        return version_output or "未能获取到版本信息"
    except Exception as e:
        return f"获取版本信息失败: {str(e)}"

def process_interface_config(device_params):
    """处理接口配置参数（简化版，不自动生成IP）"""
    interfaces = []
    conn_interface = device_params.get('conn_interface')
    
    if conn_interface and conn_interface.strip():
        print(f"处理接口: {conn_interface}")
        
        # 获取用户提供的IP地址参数
        local_ip = device_params.get('local_ip')
        ipv6_local_ip = device_params.get('ipv6_local_ip')
        
        interface_config_dict = {
            "name": conn_interface,
            "is_physical": True,  # 默认为物理接口
            "is_loopback": False,
            "mode": "route"  # 默认为路由模式
        }
        
        # 只使用用户明确提供的IP地址，不自动生成
        if local_ip:
            interface_config_dict["ipv4_address"] = local_ip
            interface_config_dict["ipv4_mask"] = "255.255.255.0"  # 默认掩码
        
        if ipv6_local_ip:
            interface_config_dict["ipv6_address"] = ipv6_local_ip
            interface_config_dict["ipv6_prefix"] = "64"  # 默认前缀长度
        
        interfaces.append(interface_config_dict)
        print(f"接口配置已生成: {interface_config_dict}")
    
    return interfaces

def send_config_to_device(config_commands, device_params):
    """将配置下发到设备"""
    results = []
    
    print(f"\n开始配置设备: {device_params['hostip']}")
    print("=" * 50)
    
    try:
        # 建立连接
        net_connect = login_args.run_script(device_params)
        
        if not net_connect:
            results.append({
                'host': device_params['hostip'],
                'status': 'failed',
                'message': '无法建立连接'
            })
            return results
        
        try:
            # 获取设备名称
            device_name = extract_device_name(net_connect)
            print(f"设备名称: {device_name}")
            
            # 获取系统信息
            system_info = get_system_info_for_log(net_connect, device_name)
            
            # 将配置按行分割
            config_lines = config_commands.strip().split('\n')
            config_lines = [line.strip() for line in config_lines if line.strip()]
            
            print(f"配置命令总数: {len(config_lines)}")
            print("-" * 50)
            
            # 执行命令记录列表
            executed_commands = []
            
            # 逐行发送配置
            success_commands = 0
            failed_commands = 0
            
            for command in config_lines:
                if command:
                    try:
                        # 发送命令并获取输出
                        output = net_connect.send_command(
                            command, 
                            expect_string=r'[<>\[\]#]', 
                            strip_prompt=False, 
                            strip_command=False
                        )
                        
                        # 显示命令执行过程
                        print(f"{command}")
                        if output.strip():
                            print(output.strip())
                        
                        # 检查命令执行结果
                        status = check_device_output.check_device_output(output)
                        if status == "Failed":
                            failed_commands += 1
                            error_message = f"执行命令 '{command}' 失败，设备返回了错误信息"
                            print(f"\n错误: {error_message}")
                            
                            executed_commands.append({
                                "command": command, 
                                "output": f"{command}\n{output.strip()}"
                            })
                            
                            # 断开连接并返回失败状态
                            net_connect.disconnect()
                            
                            results.append({
                                'host': device_params['hostip'],
                                'status': 'failed',
                                'message': error_message,
                                'success_count': success_commands,
                                'failed_count': failed_commands,
                                'total_count': len(config_lines),
                                'device_name': device_name,
                                'executed_commands': executed_commands,
                                'system_info': system_info
                            })
                            
                            return results
                        else:
                            success_commands += 1
                        
                        # 记录执行的命令
                        executed_commands.append({
                            "command": command, 
                            "output": f"{command}\n{output.strip()}"
                        })
                            
                    except Exception as cmd_e:
                        failed_commands += 1
                        print(f"{command}")
                        print(f"命令执行异常: {str(cmd_e)}")
                        
                        executed_commands.append({
                            "command": command, 
                            "output": f"{command} - 执行异常: {str(cmd_e)}"
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
                'host': device_params['hostip'],
                'status': status,
                'message': status_msg,
                'success_count': success_commands,
                'failed_count': failed_commands,
                'total_count': len(config_lines),
                'device_name': device_name,
                'executed_commands': executed_commands,
                'system_info': system_info
            })
            
        except Exception as config_e:
            results.append({
                'host': device_params['hostip'],
                'status': 'failed',
                'message': f'配置下发过程异常: {str(config_e)}'
            })
            print(f"配置下发异常: {str(config_e)}")
        
        finally:
            try:
                net_connect.disconnect()
            except:
                pass
                
    except Exception as e:
        results.append({
            'host': device_params['hostip'],
            'status': 'failed',
            'message': f'连接异常: {str(e)}'
        })
        print(f"连接异常: {str(e)}")
    
    return results

def process_bgp_deployment(input_data):
    """处理BGP配置部署的完整流程（仅支持单设备）"""
    print("BGP配置生成与部署")
    
    hostip = input_data.get("hostip", "")
    username = input_data.get("username", "")
    password = input_data.get("password", "")
    
    if not all([hostip, username, password]):
        error_msg = "错误: 缺少必要的登录参数 (hostip, username, password)"
        print(error_msg)
        return False
    
    # 检查是否包含逗号（多设备）
    if "," in hostip:
        error_msg = "错误: 当前版本仅支持单设备配置，请提供单个设备IP地址"
        print(error_msg)
        return False
    
    # 创建设备参数
    device_params = {
        'hostip': hostip,
        'username': username,
        'password': password,
        'bgp_local_as': input_data.get('bgp_local_as', 100),
        'peer_ip': input_data.get('peer_ip'),
        'bgp_peer_as': input_data.get('bgp_peer_as', 100),
        'conn_interface': input_data.get('conn_interface'),
        'address_type': input_data.get('address_type'),
        'local_ip': input_data.get('local_ip'),
        'ipv6_local_ip': input_data.get('ipv6_local_ip'),
        'network_advertise': None
    }
    
    # 处理网络宣告参数
    if input_data.get('network') and input_data.get('prefix'):
        device_params['network_advertise'] = {
            'network': input_data.get('network'),
            'prefix': input_data.get('prefix')
        }
    
    # 处理接口配置
    interfaces = process_interface_config(device_params)
    device_params['interfaces'] = interfaces
    
    # 确定地址族特性
    address_type = device_params['address_type']
    device_params['has_ipv4'] = address_type in ['ipv4 unicast', 'vpnv4', 'l2vpn evpn']
    device_params['has_ipv6'] = address_type in ['ipv6 unicast', 'vpnv6', 'l2vpn evpn']
    device_params['dual_stack'] = address_type == 'l2vpn evpn'
    device_params['device_index'] = 0
    
    try:
        # 生成完整配置
        complete_config = generate_complete_config(device_params)
        print("生成的完整配置:")
        print("=" * 50)
        print(complete_config)
        print("=" * 50)
        
    except Exception as e:
        error_msg = f"配置生成失败: {e}"
        print(error_msg)
        return False
    
    # 下发配置
    deploy_results = send_config_to_device(complete_config, device_params)
    
    # 处理结果
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
    
    # 记录日志
    final_status = "Completed" if all_success else "Failed"
    final_error_msg = "\n".join(error_messages) if error_messages else None
    
    try:
        # 静默调用日志记录函数
        import os
        original_stdout = sys.stdout
        null_device = 'nul' if os.name == 'nt' else '/dev/null'
        
        with open(null_device, 'w') as devnull:
            sys.stdout = devnull
            log_path = write_log.write_log(
                final_status, 
                result_format, 
                all_system_info, 
                final_error_msg,
                file_suffix="bgp_config_status"
            )
        
        sys.stdout = original_stdout
        
        if log_path:
            print(f"\n日志已保存至: {log_path}")
                    
    except Exception as log_e:
        sys.stdout = original_stdout
        print(f"日志记录失败: {log_e}")
    
    return all_success

def parse_json_input(json_string):
    """解析命令行传入的JSON字符串"""
    try:
        data = json.loads(json_string)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON格式错误: {e}")
        print("请检查JSON字符串格式是否正确")
        return None

def show_usage():
    """显示使用说明"""
    usage_example = '''
使用方法:

单设备配置:
python BGP_BASE_CONFIG_TEST.py '{"hostip":"192.168.56.10","username":"admin","password":"admin123","bgp_local_as":"100","peer_ip":"172.16.1.2","bgp_peer_as":"200","conn_interface":"GigabitEthernet1/0/1","address_type":"ipv4 unicast","local_ip":"172.16.1.1","network":"192.168.1.0","prefix":"24"}'

参数说明:
登录参数:
- hostip: 设备IP地址（单个IP）
- username: 用户名
- password: 密码

BGP参数:
- bgp_local_as: 本地AS号 (默认: 100)
- peer_ip: 对等体IP地址 (必须)
- bgp_peer_as: 对等体AS号 (默认: 100)
- conn_interface: 连接接口
- address_type: 地址族类型 (ipv4 unicast, ipv6 unicast, vpnv4, vpnv6, l2vpn evpn)
- local_ip: 本地接口IPv4地址 (可选，不提供则不配置接口IP)
- ipv6_local_ip: 本地接口IPv6地址 (可选，不提供则不配置接口IPv6)
- network: 通告网络 (可选)
- prefix: 网络前缀 (可选)

注意: 
- 当前版本仅支持单设备配置
- 不会自动生成IP地址，需要用户明确提供local_ip和ipv6_local_ip参数
- 如果不提供IP地址参数，则不会配置接口IP地址
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
    
    # 执行BGP部署流程
    try:
        success = process_bgp_deployment(input_data)
        
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        error_msg = f"程序运行时发生错误: {str(e)}"
        print(error_msg)
        sys.exit(1)