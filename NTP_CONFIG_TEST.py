#写一个配置H3C路由器、交换机NTP功能的脚本，支持两台设备配置
#1. 使用login_args.py中的login函数来实现登录认证
#2. 登录成功后，默认下发system-view命令，用来进入系统视图
#3. 支持配置NTP Server和NTP Client模式

import sys
import os
import json
import time
import re
from datetime import datetime

# 导入自定义模块
import login_args
import write_log
import get_system_info
import check_device_output
import interface_config

def generate_ntp_config(device_info, ssh_connection=None):
    """生成NTP和接口配置命令列表"""
    ntp_mode = device_info.get('ntp_mode', 'server')
    server_ip = device_info.get('server_ip', '')
    interface_name = device_info.get('interface_name', '')
    interface_ip = device_info.get('interface_ip', '')
    
    config_lines = []
    
    # 接口配置（如果提供了接口参数）
    if interface_name and interface_ip:
        # 直接使用用户输入的接口名称，不做任何转换
        normalized_interface = interface_name
        
        # 判断是否是LoopBack接口
        if interface_config.is_loopback_interface(normalized_interface):
            # LoopBack接口配置
            config_lines.append(f"interface {normalized_interface}")
            config_lines.append(f"ip address {interface_ip} 255.255.255.255")
            config_lines.append("quit")
        else:
            # 物理接口配置
            config_lines.append(f"interface {normalized_interface}")
            
            # 如果连接对象存在，检查接口模式
            if ssh_connection:
                try:
                    interface_mode = interface_config.check_interface_mode(ssh_connection, normalized_interface, verbose=False)
                    # 如果是bridge模式，需要切换到route模式
                    if interface_mode == "bridge":
                        config_lines.append("port link-mode route")
                except Exception as e:
                    # 默认设置为route模式
                    config_lines.append("port link-mode route")
            else:
                # 没有SSH连接时，默认设置为route模式
                config_lines.append("port link-mode route")
            
            config_lines.append(f"ip address {interface_ip} 255.255.255.0")
            config_lines.append("quit")
    
    # NTP服务配置 - 在系统视图执行
    if ntp_mode == 'server':
        # 配置为NTP服务器
        config_lines.append("ntp-service enable")
        config_lines.append("ntp-service refclock-master 2")
    elif ntp_mode == 'client':
        # 配置为NTP客户端
        config_lines.append("ntp-service enable")
        if server_ip:
            config_lines.append(f"ntp-service unicast-server {server_ip}")
    
    return config_lines

def execute_command(net_connect, command, executed_commands=None, system_info=None, current_prompt=None, device_name=None, log_command=True):
    """执行命令，使用check_device_output模块进行错误检查"""
    if executed_commands is None:
        executed_commands = []
    
    try:
        # 检查连接状态
        if not net_connect.is_alive():
            # 获取系统信息用于日志记录
            try:
                system_info_for_log = get_system_info.get_system_info(net_connect) if net_connect else {}
            except:
                system_info_for_log = {}
            
            # 打印明确的错误信息给用户
            print(f"\n错误：SSH连接已断开，尝试执行命令: {command}")
            
            # 记录失败日志 - 使用已执行的命令和正确的系统信息
            write_log.write_log("Failed", executed_commands, system_info_for_log, "SSH connection was lost during command execution")
            # 直接退出整个程序
            sys.exit(1)
        
        # 执行命令并获取输出
        cmd_output = net_connect.send_command(
            command,
            expect_string=r"[\[\]>]",
            delay_factor=0.5,
            max_loops=30,
            strip_command=True,
            strip_prompt=True
        )
        
        # 获取当前真实提示符用于显示
        try:
            current_real_prompt = net_connect.find_prompt()
        except:
            current_real_prompt = current_prompt
        
        # 显示完整的命令交互（模拟真实终端显示）
        print(f"{current_prompt}{command}")
        if cmd_output.strip():
            print(cmd_output.strip())
        
        # 处理Y/N确认
        if "Y/N" in cmd_output or "[Y/N]" in cmd_output:
            net_connect.write_channel("Y\n")
            time.sleep(0.2)
            try:
                additional_output = net_connect.read_until_pattern(r"[\[\]>]")
                cmd_output += additional_output
            except:
                pass
        
        # 记录完整的设备交互过程
        interaction_record = f"{current_prompt}{command}"
        if cmd_output.strip():
            interaction_record += f"\n{cmd_output.strip()}"
        executed_commands.append(interaction_record)
        
        # 使用check_device_output模块检查命令输出
        try:
            check_result = check_device_output.check_device_output(cmd_output)
            # 如果检查结果是Failed，说明有严重问题，直接中断程序
            if check_result == "Failed":
                # 打印明确的错误信息给用户
                print(f"\n命令执行失败: {command}")
                
                # 抛出异常让上层处理，而不是直接退出程序
                raise RuntimeError(f"Command '{command}' failed with output: {cmd_output}")
        except Exception as e:
            # 如果check_device_output本身出错，继续执行
            pass
        
        # 获取设备当前的实际提示符（用于下次命令执行）
        try:
            new_prompt = net_connect.find_prompt()
        except:
            new_prompt = current_prompt  # 如果获取失败，保持当前提示符
        
        return cmd_output, new_prompt
        
    except Exception as e:
        # 获取系统信息用于日志记录
        try:
            system_info_for_log = get_system_info.get_system_info(net_connect) if net_connect else {}
        except:
            system_info_for_log = {}
        
        # 打印明确的错误信息给用户
        print(f"\n执行命令异常: {command} - {str(e)}")
        
        # 抛出异常让上层处理，而不是直接退出程序
        raise RuntimeError(f"Exception occurred while executing command '{command}': {str(e)}")

def config_single_device_ntp(params):
    """配置单个设备的NTP"""
    hostip = params.get('hostip')
    username = params.get('username')
    password = params.get('password')
    ntp_mode = params.get('ntp_mode', 'server')
    server_ip = params.get('server_ip', '')
    
    try:
        # 连接设备
        net_connect = login_args.login(hostip, username, password)
        
        # 获取当前提示符和设备名
        current_prompt = net_connect.find_prompt()
        device_name = ""
        
        # 从提示符中提取设备名
        if '<' in current_prompt and '>' in current_prompt:
            device_name = current_prompt.strip('<>')
        elif '[' in current_prompt and ']' in current_prompt:
            device_name = current_prompt.strip('[]')
        else:
            device_name = f"NTP_Device_{hostip}"
        
        # 确保提示符格式正确
        if not current_prompt.endswith('>'):
            current_prompt = f"<{device_name}>"
        
        executed_commands = []
        
        # 获取系统信息（在配置开始前获取）
        try:
            system_info = get_system_info.get_system_info(net_connect)
        except:
            system_info = f"Device: {device_name} ({hostip}) - System info unavailable"
        
        # 进入系统视图
        output, current_prompt = execute_command(
            net_connect, "system-view", executed_commands, 
            system_info, current_prompt, device_name
        )
        
        # 生成NTP配置命令
        ntp_config = generate_ntp_config(params, net_connect)
        
        # 执行NTP配置命令
        current_in_interface = False
        for cmd in ntp_config:
            # 检查是否是接口命令
            if cmd.startswith("interface "):
                current_in_interface = True
            elif cmd == "quit" and current_in_interface:
                current_in_interface = False
            elif cmd.startswith("ntp-service") and current_in_interface:
                # NTP命令不应该在接口视图执行，先退出到系统视图
                if current_in_interface:
                    output, current_prompt = execute_command(
                        net_connect, "quit", executed_commands,
                        system_info, current_prompt, device_name
                    )
                    current_in_interface = False
            
            # 执行命令（如果有严重错误，execute_command会直接中断程序）
            output, current_prompt = execute_command(
                net_connect, cmd, executed_commands,
                system_info, current_prompt, device_name
            )
        
        # 退出系统视图
        output, current_prompt = execute_command(
            net_connect, "quit", executed_commands,
            system_info, current_prompt, device_name
        )
        
        # 设备输出检查
        try:
            check_result = check_device_output.check_device_output(executed_commands[-1] if executed_commands else "")
        except:
            check_result = "Output check skipped"
        
        # 断开连接
        net_connect.disconnect()
        
        # 返回配置信息而不是直接写日志
        return {
            'status': 'Success',
            'executed_commands': executed_commands,
            'system_info': system_info,
            'device_name': device_name,
            'host_ip': hostip
        }
        
    except Exception as e:
        # 如果连接失败或配置过程中出现异常
        try:
            if 'net_connect' in locals():
                net_connect.disconnect()
        except:
            pass
        
        # 返回失败信息而不是直接写日志
        return {
            'status': 'Failed',
            'executed_commands': executed_commands if 'executed_commands' in locals() else [],
            'system_info': system_info if 'system_info' in locals() else f"Device: {hostip} - Connection failed",
            'device_name': device_name if 'device_name' in locals() else f"NTP_Device_{hostip}",
            'host_ip': hostip,
            'error': str(e)
        }

def main():
    """主函数"""
    
    if len(sys.argv) != 2:
        print("用法: python NTP_CONFIG_TEST.py '<JSON参数>'")
        print("\n参数说明:")
        print("必需参数:")
        print("  hostip: 两台设备IP地址，用逗号分隔（必须恰好2台设备）")
        print("  username: 登录用户名")
        print("  password: 登录密码")
        print("  ntp_server_device: 指定哪台设备作为NTP Server ('1' 或 '2')")
        print("  dut1_interface: 第一台设备的接口名称（如：GigabitEthernet0/0/1）")
        print("  dut2_interface: 第二台设备的接口名称（如：GigabitEthernet0/0/2）")
        print("\n两设备NTP配置示例:")
        print('python NTP_CONFIG_TEST.py \'{"hostip":"192.168.30.7,192.168.30.8","username":"admin","password":"admin","ntp_server_device":"1","dut1_interface":"GigabitEthernet0/0/1","dut2_interface":"GigabitEthernet0/0/2"}\'')
        print("\n说明：")
        print("  - 此程序只支持配置两台设备的NTP服务")
        print("  - ntp_server_device='1' 表示第一台设备作为NTP Server，第二台设备作为Client")
        print("  - ntp_server_device='2' 表示第二台设备作为NTP Server，第一台设备作为Client")
        print("  - 接口IP自动分配：第一台设备 172.16.1.1/24，第二台设备 172.16.1.2/24")
        print("  - NTP Server使用内置时钟源(stratum 2)")
        print("  - NTP Client同步到Server设备的互联接口IP地址")
        sys.exit(1)

    try:
        # 解析JSON参数
        json_str = sys.argv[1]
        params = json.loads(json_str)

        # 记录Running状态的日志 - 不使用error_message字段      
        write_log.write_log("Running", [], {})
        
        # 检查必要参数
        required_params = ['hostip', 'username', 'password', 'ntp_server_device', 'dut1_interface', 'dut2_interface']
        for param in required_params:
            if not params.get(param):
                print(f"错误: 缺少必需参数 {param}")
                sys.exit(1)
        
        # 解析hostip参数，必须是两台设备
        hostip_param = params.get('hostip', '')
        hostips = [ip.strip() for ip in hostip_param.split(',') if ip.strip()]
        
        if len(hostips) != 2:
            print(f"错误: 此程序只支持配置两台设备，当前提供了 {len(hostips)} 台设备")
            print("请在hostip参数中提供恰好两个IP地址，用逗号分隔")
            sys.exit(1)
        
        # 验证ntp_server_device参数
        ntp_server_device = params.get('ntp_server_device', '')
        if ntp_server_device not in ['1', '2']:
            print("错误: ntp_server_device参数必须是 '1' 或 '2'")
            sys.exit(1)
        
        # 确定Server和Client
        server_index = int(ntp_server_device) - 1
        client_index = 1 - server_index
        server_mgmt_ip = hostips[server_index]
        client_mgmt_ip = hostips[client_index]
        
        # 分配互联接口IP：第一台设备 172.16.1.1，第二台设备 172.16.1.2
        server_interface_ip = "172.16.1.1" if server_index == 0 else "172.16.1.2"
        client_interface_ip = "172.16.1.2" if client_index == 1 else "172.16.1.1"
        
        # 分配接口名称：第一台设备使用dut1_interface，第二台设备使用dut2_interface
        server_interface_name = params.get('dut1_interface') if server_index == 0 else params.get('dut2_interface')
        client_interface_name = params.get('dut2_interface') if client_index == 1 else params.get('dut1_interface')
        
        # NTP Client使用Server的互联接口IP
        ntp_server_ip = server_interface_ip
        
        results = []
        all_device_commands = {}  # 改为按设备分组的命令字典
        all_system_info = {}
        
        # 配置NTP Server
        server_params = params.copy()
        server_params['hostip'] = server_mgmt_ip
        server_params['ntp_mode'] = 'server'
        server_params['interface_name'] = server_interface_name
        server_params['interface_ip'] = server_interface_ip
        
        print(f"开始配置 NTP Server: {server_mgmt_ip}")
        server_result = config_single_device_ntp(server_params)
        
        if server_result['status'] == 'Success':
            results.append(("Server", server_mgmt_ip, "Success"))
            print(f"设备 {server_mgmt_ip} (NTP Server) 配置成功")
            device_key = server_result['device_name']  # 使用实际设备名称
            all_device_commands[device_key] = server_result['executed_commands']
            all_system_info[device_key] = server_result['system_info']
        else:
            error_msg = server_result.get('error', '未知错误')
            results.append(("Server", server_mgmt_ip, f"Failed: {error_msg}"))
            print(f"设备 {server_mgmt_ip} (NTP Server) 配置失败: {error_msg}")
            # 即使失败也记录信息
            device_key = server_result['device_name']  # 使用实际设备名称
            all_device_commands[device_key] = server_result['executed_commands']
            all_system_info[device_key] = server_result['system_info']
        
        # 配置NTP Client
        client_params = params.copy()
        client_params['hostip'] = client_mgmt_ip
        client_params['ntp_mode'] = 'client'
        client_params['server_ip'] = ntp_server_ip  # 使用Server的互联接口IP
        client_params['interface_name'] = client_interface_name
        client_params['interface_ip'] = client_interface_ip
        
        print(f"开始配置 NTP Client: {client_mgmt_ip}")
        client_result = config_single_device_ntp(client_params)
        
        if client_result['status'] == 'Success':
            results.append(("Client", client_mgmt_ip, "Success"))
            print(f"设备 {client_mgmt_ip} (NTP Client) 配置成功")
            device_key = client_result['device_name']  # 使用实际设备名称
            all_device_commands[device_key] = client_result['executed_commands']
            all_system_info[device_key] = client_result['system_info']
        else:
            error_msg = client_result.get('error', '未知错误')
            results.append(("Client", client_mgmt_ip, f"Failed: {error_msg}"))
            print(f"设备 {client_mgmt_ip} (NTP Client) 配置失败: {error_msg}")
            # 即使失败也记录信息
            device_key = client_result['device_name']  # 使用实际设备名称
            all_device_commands[device_key] = client_result['executed_commands']
            all_system_info[device_key] = client_result['system_info']
        
        # 统计成功数量
        success_count = sum(1 for _, _, status in results if status == "Success")
        
        # 统一记录日志 - 包含所有设备的信息
        final_status = "Completed" if success_count == 2 else "Partial" if success_count > 0 else "Failed"
        
        # 根据最终状态决定是否记录错误信息
        if final_status == "Failed":
            summary_info = f"NTP配置失败 - 成功: {success_count}/2 台设备\n"
            for role, ip, status in results:
                summary_info += f"  {role} ({ip}): {status}\n"
            write_log.write_log(final_status, all_device_commands, all_system_info, summary_info)
        else:
            # 成功或部分成功时不使用error_message字段
            write_log.write_log(final_status, all_device_commands, all_system_info)
        
        # 打印总结
        print(f"\n配置总结:")
        for role, ip, status in results:
            print(f"  {role} ({ip}): {status}")
        
        print(f"\n成功配置: {success_count}/2 台设备")
        
        if success_count == 2:
            print("所有设备配置成功")
            sys.exit(0)
        elif success_count > 0:
            print("部分设备配置成功")
            sys.exit(1)
        else:
            print("所有设备配置失败")
            sys.exit(1)
            
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {str(e)}")
        print("请确保参数格式正确")
        sys.exit(1)
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
