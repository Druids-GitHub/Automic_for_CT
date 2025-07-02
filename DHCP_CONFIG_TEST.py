import sys
import os
import json
import time
import re
from netmiko import ConnectHandler
from datetime import datetime

# 导入自定义模块
import login_args
import write_log
import get_system_info
import check_device_output

def generate_dhcp_config(device_info):
    """生成DHCP配置命令列表，但不默认添加system-view命令"""
    pool_name = device_info.get('pool_name')
    pool_network = device_info.get('pool_network')
    pool_mask = device_info.get('pool_mask')
    pool_gateway = device_info.get('pool_gateway')
    pool_dns = device_info.get('pool_dns', [])
    pool_expired_time = device_info.get('pool_expired_time', '7')
    forbidden_ip = device_info.get('forbidden_ip', [])
    
    # 初始化命令列表 - 不再添加system-view命令
    config_lines = []
    
    # 添加DHCP启用命令
    config_lines.append("dhcp enable")
    
    # 添加DHCP禁用IP地址命令
    if forbidden_ip:
        for ip in forbidden_ip:
            config_lines.append(f"dhcp server forbidden-ip {ip}")
    
    # 添加DHCP池配置命令
    config_lines.append(f"dhcp server ip-pool {pool_name}")
    config_lines.append(f"network {pool_network} mask {pool_mask}")
    config_lines.append(f"gateway-list {pool_gateway}")
    
    # 添加DNS服务器命令
    if pool_dns:
        for dns in pool_dns:
            config_lines.append(f"dns-list {dns}")
    
    # 添加租约配置
    config_lines.append(f"expired day {pool_expired_time}")
    
    # 添加退出命令
    config_lines.append("quit")
    
    return config_lines

def execute_command(net_connect, command, executed_commands=None, system_info=None, current_prompt=None, device_name=None, log_command=True):
    """高速执行命令，优化网络交互，使用check_device_output模块检查错误"""
    if executed_commands is None:
        executed_commands = []
    
    try:
        # 打印命令（保持UI反馈）
        print(f"{current_prompt}{command}")
        
        # 优化1: 使用更高效的send_command替代send_command_timing
        cmd_output = net_connect.send_command(
            command,
            expect_string=r"[>\]]",  # 通用提示符匹配模式
            delay_factor=0.1,        # 保持较低延迟
            max_loops=50,            # 减少等待循环次数
            strip_command=True,      # 移除输出中的命令
            strip_prompt=True        # 移除输出中的提示符
        )
        
        # 优化2: 更高效的Y/N确认处理
        if "Y/N" in cmd_output or "[Y/N]" in cmd_output:
            net_connect.write_channel("Y\n")
            # 减少等待时间
            time.sleep(0.1)
            cmd_output += net_connect.read_until_pattern(r"[>\]]")
        
        # 优化3: 智能提示符处理 - 不频繁查询设备
        new_prompt = current_prompt  # 默认保持当前提示符
        
        # 优化4: 针对不同命令智能预测提示符变化
        if command == "system-view":
            # system-view命令始终进入系统视图
            if device_name and '<' in current_prompt:
                new_prompt = f"[{device_name}]"  # 直接构造新提示符
            else:
                # 仅在必要时查询
                try:
                    new_prompt = net_connect.find_prompt()
                except:
                    if device_name:
                        new_prompt = f"[{device_name}]"
            
            # 记录命令
            if log_command:
                executed_commands.append(f"{current_prompt}{command}\n{cmd_output.strip()}")
            
            return cmd_output, new_prompt
            
        elif command.startswith("dhcp server ip-pool"):
            # 进入DHCP池视图
            pool_name = command.split()[-1]
            new_prompt = f"[{device_name}-dhcp-pool-{pool_name}]" if device_name else current_prompt
            
        elif command == "quit":
            # 退出当前视图
            if "-dhcp-pool-" in current_prompt and device_name:
                new_prompt = f"[{device_name}]"  # 回到系统视图
            elif '[' in current_prompt and '<' not in current_prompt and device_name:
                new_prompt = f"<{device_name}>"  # 退出到用户视图
        
        # 显示输出（保持UI反馈）
        if cmd_output.strip():
            print(cmd_output.strip())
        
        # 记录命令
        if log_command:
            executed_commands.append(f"{current_prompt}{command}\n{cmd_output.strip()}")
        
        # 正确使用check_device_output模块检查错误
        status = check_device_output.check_device_output(cmd_output)
        if status == "Failed":
            # 不要在异常信息中包含完整的输出内容，避免重复
            raise Exception(f"执行命令 '{command}' 失败", device_name or "Unknown_Device")
        
        return cmd_output, new_prompt
        
    except Exception as e:
        if len(e.args) >= 2:
            raise e
        else:
            raise Exception(str(e), device_name or "Unknown_Device")

def check_current_view(prompt):
    """判断当前所处的视图 - 增强识别能力"""
    # 增强系统视图的识别，更宽松的匹配
    if '[' in prompt and ']' in prompt:
        return "system_view"  # 系统视图 [设备名]
    # 用户视图识别
    elif '<' in prompt and '>' in prompt:
        return "user_view"  # 用户视图 <设备名>
    else:
        print("未知视图类型")
        return "unknown_view"

def dhcp_config(hostip, username, password, pool_name, pool_network, pool_mask, pool_gateway, pool_dns, pool_expired_time, forbidden_ip):
    """执行DHCP配置 - 高速版，但保持真实的命令回显体验"""
    device_executed_commands = []
    system_info = ""
    error_msg = ""
    device_name = ""
    
    try:
        # 使用login_args模块进行设备连接
        print(f"正在连接设备 {hostip}...")
        
        try:
            # 尝试通过login_args模块
            net_connect = login_args.login(hostip, username, password)
        except:
            # 如果不支持，直接创建连接
            from netmiko import ConnectHandler
            device = {
                'device_type': 'hp_comware',
                'host': hostip,
                'username': username,
                'password': password,
                'fast_cli': True
            }
            net_connect = ConnectHandler(**device)
        
        if net_connect is None:
            raise Exception(f"设备({hostip})登录失败", hostip)
        
        # 直接获取当前提示符
        current_prompt = net_connect.find_prompt()
        
        # 提取设备名称
        if '<' in current_prompt and '>' in current_prompt:
            device_name = current_prompt.strip('<>')
        elif '[' in current_prompt and ']' in current_prompt:
            device_name = current_prompt.strip('[]')
        else:
            device_name = f"DHCP_Server_{hostip}"
        
        print(f"提取到的设备名称: {device_name}")
        
        # 获取真实系统信息 - 恢复使用get_system_info模块
        try:
            system_info = get_system_info.get_system_info(net_connect)
        except Exception as e:
            print(f"获取系统信息时发生错误: {str(e)}")
            # 如果获取失败，使用简单版本备用
            system_info = f"Device: {device_name} ({hostip}) - System info unavailable"
        
        # 检查当前视图并切换到系统视图
        current_view = check_current_view(current_prompt)

        if current_view == "user_view":
            # 执行system-view命令并记录
            cmd_output, current_prompt = execute_command(
                net_connect, 
                "system-view", 
                device_executed_commands, 
                system_info, 
                current_prompt,
                device_name
            )
            
            # 这里不需要额外检查system-view是否被记录，因为execute_command函数会负责记录
            print("已切换到系统视图")
        else:
            print("已经在系统视图中，无需切换视图")

        # 生成DHCP配置命令 - 已修改的generate_dhcp_config不会自动添加system-view
        device_info = {
            "hostip": hostip,
            "pool_name": pool_name,
            "pool_network": pool_network,
            "pool_mask": pool_mask,
            "pool_gateway": pool_gateway,
            "pool_dns": pool_dns,
            "pool_expired_time": pool_expired_time,
            "forbidden_ip": forbidden_ip
        }
        config_lines = generate_dhcp_config(device_info)

        # 逐行执行配置命令
        for cmd in config_lines:
            if cmd.strip():
                _, current_prompt = execute_command(
                    net_connect, 
                    cmd.strip(), 
                    device_executed_commands, 
                    system_info, 
                    current_prompt,
                    device_name
                )
                # 确保输出即时显示
                sys.stdout.flush()
        
        # 断开连接
        net_connect.disconnect()
        print(f"\nDHCP配置完成，设备 {device_name} 已断开连接")
        
        return True, device_executed_commands, system_info, "", device_name
        
    except Exception as e:
        error_msg = str(e.args[0]) if e.args else str(e)
        device_key = str(e.args[1]) if len(e.args) >= 2 else device_name or hostip
        print(f"\nDHCP配置失败: {error_msg}")
        
        try:
            if 'net_connect' in locals() and net_connect:
                net_connect.disconnect()
        except:
            pass
        
        return False, device_executed_commands, system_info, error_msg, device_key

def main():
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("使用方法:")
        print(f'python {os.path.basename(__file__)} \'{{参数}}\'')
        print("\n参数格式:")
        print('"hostip":"192.168.1.1,192.168.1.2"')
        print('"username":"admin" (单个值将应用于所有设备)')
        print('"password":"password" (单个值将应用于所有设备)')
        print('"pool_name":"pool1,pool2" (DHCP地址池名称)')
        print('"pool_network":"192.168.1.0,192.168.2.0" (网络地址)')
        print('"pool_mask":"255.255.255.0,255.255.255.0" (子网掩码)')
        print('"pool_gateway":"192.168.1.1,192.168.2.1" (默认网关)')
        print('"pool_dns":["8.8.8.8","8.8.4.4"] (DNS服务器，可选)')
        print('"pool_expired_time":"7,7" (租约时间，天，可选，默认为7)')
        print('"forbidden_ip":["192.168.1.1","192.168.1.100"] (禁用IP，可选)')
        
        print("\n完整示例:")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.1.1","username":"admin","password":"password","pool_name":"pool1","pool_network":"192.168.1.0","pool_mask":"255.255.255.0","pool_gateway":"192.168.1.1","pool_dns":["8.8.8.8","8.8.4.4"],"pool_expired_time":"7","forbidden_ip":["192.168.1.1","192.168.1.100"]}}\'')
        sys.exit(1)
    
    # 解析JSON参数
    try:
        json_str = sys.argv[1]
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        config = json.loads(json_str)
        
        # 在成功解析参数后立即记录Running状态的日志
        write_log.write_log(
            "Running", 
            {}, 
            {}, 
            file_suffix="dhcp_config"
        )
        
        # 获取基本参数
        hostips = config.get('hostip', '').split(',')
        usernames = config.get('username', '').split(',')
        passwords = config.get('password', '').split(',')
        pool_names = config.get('pool_name', '').split(',')
        pool_networks = config.get('pool_network', '').split(',')
        pool_masks = config.get('pool_mask', '').split(',')
        pool_gateways = config.get('pool_gateway', '').split(',')
        pool_dns = config.get('pool_dns', [])  # 可选参数，默认为空列表
        pool_expired_times = config.get('pool_expired_time', '').split(',') if config.get('pool_expired_time') else []
        forbidden_ip = config.get('forbidden_ip', [])  # 可选参数，默认为空列表
        
        # 扩展单值参数到与设备数量匹配
        if len(usernames) == 1 and len(hostips) > 1:
            usernames = usernames * len(hostips)
        if len(passwords) == 1 and len(hostips) > 1:
            passwords = passwords * len(hostips)
        if len(pool_names) == 1 and len(hostips) > 1:
            pool_names = pool_names * len(hostips)
        if len(pool_networks) == 1 and len(hostips) > 1:
            pool_networks = pool_networks * len(hostips)
        if len(pool_masks) == 1 and len(hostips) > 1:
            pool_masks = pool_masks * len(hostips)
        if len(pool_gateways) == 1 and len(hostips) > 1:
            pool_gateways = pool_gateways * len(hostips)
        if len(pool_expired_times) == 1 and len(hostips) > 1:
            pool_expired_times = pool_expired_times * len(hostips)
        elif not pool_expired_times:
            pool_expired_times = ['7'] * len(hostips)  # 默认租约时间7天
        
        # 创建设备列表
        devices = []
        for i in range(len(hostips)):
            device = {
                'hostip': hostips[i].strip(),
                'username': usernames[i % len(usernames)].strip(),
                'password': passwords[i % len(passwords)].strip(),
                'pool_name': pool_names[i % len(pool_names)].strip(),
                'pool_network': pool_networks[i % len(pool_networks)].strip(),
                'pool_mask': pool_masks[i % len(pool_masks)].strip(),
                'pool_gateway': pool_gateways[i % len(pool_gateways)].strip(),
                'pool_dns': pool_dns,  # 所有设备使用相同的DNS设置
                'pool_expired_time': pool_expired_times[i % len(pool_expired_times)].strip(),
                'forbidden_ip': forbidden_ip  # 所有设备使用相同的forbidden_ip设置
            }
            devices.append(device)
        
        # 初始化结果收集
        all_commands = {}
        all_system_info = {}
        final_status = "succeed"
        result = {"error_message": {}}
        
        # 执行配置
        for i, device in enumerate(devices):
            hostip = device.get('hostip')
            username = device.get('username')
            password = device.get('password')
            pool_name = device.get('pool_name')
            pool_network = device.get('pool_network')
            pool_mask = device.get('pool_mask')
            pool_gateway = device.get('pool_gateway')
            device_pool_dns = device.get('pool_dns')
            pool_expired_time = device.get('pool_expired_time')
            device_forbidden_ip = device.get('forbidden_ip')
            
            # 检查必要参数
            missing = []
            if not hostip:
                missing.append('hostip')
            if not username:
                missing.append('username')
            if not password:
                missing.append('password')
            if not pool_name:
                missing.append('pool_name')
            if not pool_network:
                missing.append('pool_network')
            if not pool_mask:
                missing.append('pool_mask')
            if not pool_gateway:
                missing.append('pool_gateway')
            
            if missing:
                print(f"错误: 设备 {hostip if hostip else i+1} 缺少必要参数: {', '.join(missing)}")
                continue
            
            # 执行DHCP配置
            success, executed_commands, system_info, error_msg, device_name = dhcp_config(
                hostip, username, password, pool_name, pool_network, pool_mask, pool_gateway,
                device_pool_dns, pool_expired_time, device_forbidden_ip
            )
            
            # 使用设备名称作为键
            device_key = device_name if device_name else hostip
            
            # 收集设备结果
            all_commands[device_key] = executed_commands
            all_system_info[device_key] = system_info
            
            # 处理错误
            if not success:
                final_status = "Failed"
                if error_msg:
                    result["error_message"][device_key] = error_msg
        
        # 写入日志
        write_log.write_log(
            final_status, 
            all_commands, 
            all_system_info, 
            file_suffix="dhcp_config",
            **result
        )
        
    except json.JSONDecodeError as e:
        print(f"JSON参数解析错误: {str(e)}")
        print("请检查参数格式是否正确")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
        # 确保即使出错也写入日志
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="dhcp_config",
                error_message={"General": str(e)}
            )
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()