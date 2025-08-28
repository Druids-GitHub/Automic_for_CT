#写一个配置H3C路由器、交换机MTU功能的脚本。
#1. 使用现成的login_args.py中的login函数来实现登录认证等功能
#2. 登录成功后，默认下发system-view命令，用来进入系统视图
#3. 配置两个接口的IP地址和MTU值

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

def validate_mtu_value(mtu_value):
    """验证MTU值是否有效"""
    valid_mtu_values = [256, 1546, 9000]
    try:
        mtu = int(mtu_value)
        if mtu in valid_mtu_values:
            return True, mtu
        else:
            return False, f"MTU值必须是以下之一: {', '.join(map(str, valid_mtu_values))}"
    except ValueError:
        return False, "MTU值必须是数字"

def normalize_interface_name(interface_name):
    """直接使用用户输入的接口名称，不进行任何转换"""
    # 用户最了解自己设备的接口命名规范，直接使用原始输入
    return interface_name.strip()

def smart_interface_config(net_connect, interface, ip_address, subnet_mask, mtu_value, executed_commands, system_info, current_prompt, device_name):
    """智能接口配置：自动检查并切换接口模式"""
    
    # 进入接口配置模式
    cmd_output, current_prompt = execute_command(
        net_connect, 
        f"interface {interface}", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    # 检查当前接口模式
    try:
        # 使用display this命令查看接口配置
        display_output = net_connect.send_command(
            "display this",
            expect_string=r"[>\]]",
            delay_factor=0.2,
            strip_command=True,
            strip_prompt=True
        )
        
        # 检查是否为bridge模式，如果是则切换到route模式
        if "link-mode bridge" in display_output.lower() or "bridge" in display_output.lower():
            # 执行模式切换，不显示额外提示
            cmd_output, current_prompt = execute_command(
                net_connect, 
                "port link-mode route", 
                executed_commands, 
                system_info, 
                current_prompt,
                device_name
            )
            # 等待模式切换完成
            time.sleep(2)
        elif not ("link-mode route" in display_output.lower() or "route" in display_output.lower()):
            # 模式未知，尝试切换到route模式
            cmd_output, current_prompt = execute_command(
                net_connect, 
                "port link-mode route", 
                executed_commands, 
                system_info, 
                current_prompt,
                device_name
            )
            time.sleep(2)
            
    except Exception as e:
        # 检查失败时直接尝试配置
        pass
    
    # 配置IP地址
    cmd_output, current_prompt = execute_command(
        net_connect, 
        f"ip address {ip_address} {subnet_mask}", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    # 配置MTU
    cmd_output, current_prompt = execute_command(
        net_connect, 
        f"ip mtu {mtu_value}", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    # 退出接口配置
    cmd_output, current_prompt = execute_command(
        net_connect, 
        "quit", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    return current_prompt

def execute_command(net_connect, command, executed_commands=None, system_info=None, current_prompt=None, device_name=None, log_command=True):
    """高速执行命令，优化网络交互，使用check_device_output模块检查错误"""
    if executed_commands is None:
        executed_commands = []
    
    try:
        # 打印命令（保持UI反馈）
        print(f"{current_prompt}{command}")
        
        # 使用优化的send_command
        cmd_output = net_connect.send_command(
            command,
            expect_string=r"[>\]]",  # 通用提示符匹配模式
            delay_factor=0.3,        # 增加延迟因子处理模式切换
            max_loops=50,            # 减少等待循环次数
            strip_command=True,      # 移除输出中的命令
            strip_prompt=True        # 移除输出中的提示符
        )
        
        # Y/N确认处理 - 静默处理，不显示额外提示
        if any(confirm_text in cmd_output for confirm_text in ["Y/N", "[Y/N]", "Continue? [Y/N]:", "choose 'YES' or 'NO'[Y/N]:"]):
            net_connect.write_channel("Y\n")
            time.sleep(0.5)
            try:
                additional_output = net_connect.read_until_pattern(r"[>\]]")
                cmd_output += "\n" + additional_output
            except:
                pass
        
        # 智能提示符处理
        new_prompt = current_prompt  # 默认保持当前提示符
        
        # 针对不同命令智能预测提示符变化
        if command == "system-view":
            # system-view命令始终进入系统视图
            if device_name and '<' in current_prompt:
                new_prompt = f"[{device_name}]"  # 直接构造新提示符
            else:
                try:
                    new_prompt = net_connect.find_prompt()
                except:
                    if device_name:
                        new_prompt = f"[{device_name}]"
            
            # 记录命令
            if log_command:
                interaction_record = f"{current_prompt}{command}"
                if cmd_output.strip():
                    interaction_record += f" {cmd_output.strip()}"
                executed_commands.append(interaction_record)
            
            return cmd_output, new_prompt
            
        elif command.startswith("interface "):
            # 进入接口配置视图
            interface_name = command.split(" ", 1)[1]
            if device_name:
                new_prompt = f"[{device_name}-{interface_name}]"
            
        elif command == "quit":
            # 退出当前视图
            if '[' in current_prompt and '-' in current_prompt and device_name:
                # 从接口视图退出到系统视图
                new_prompt = f"[{device_name}]"
            elif '[' in current_prompt and '<' not in current_prompt and device_name:
                # 从系统视图退出到用户视图
                new_prompt = f"<{device_name}>"
        
        # 显示输出
        if cmd_output.strip():
            print(cmd_output.strip())
        
        # 记录命令
        if log_command:
            interaction_record = f"{current_prompt}{command}"
            if cmd_output.strip():
                interaction_record += f" {cmd_output.strip()}"
            executed_commands.append(interaction_record)
        
        # 使用check_device_output模块检查错误
        status = check_device_output.check_device_output(cmd_output)
        if status == "Failed":
            raise Exception(f"执行命令 '{command}' 失败", device_name or "Unknown_Device")
        
        return cmd_output, new_prompt
        
    except Exception as e:
        if len(e.args) >= 2:
            raise e
        else:
            raise Exception(str(e), device_name or "Unknown_Device")

def check_current_view(prompt):
    """判断当前所处的视图"""
    if '[' in prompt and ']' in prompt:
        return "system_view"  # 系统视图或接口视图
    elif '<' in prompt and '>' in prompt:
        return "user_view"  # 用户视图
    else:
        return "unknown_view"

def mtu_config(hostip, username, password, interface1, interface2, mtu_value):
    """执行MTU配置"""
    device_executed_commands = []
    system_info = ""
    error_msg = ""
    device_name = ""
    
    try:
        # 验证MTU值
        is_valid, result = validate_mtu_value(mtu_value)
        if not is_valid:
            raise Exception(result, hostip)
        mtu_value = result
        
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
            device_name = current_prompt.strip('[]').split('-')[0]  # 处理接口视图的情况
        else:
            device_name = f"MTU_Device_{hostip}"

        # 获取真实系统信息
        try:
            system_info = get_system_info.get_system_info(net_connect)
        except Exception as e:
            print(f"获取系统信息时发生错误: {str(e)}")
            system_info = f"Device: {device_name} ({hostip}) - System info unavailable"
        
        # 检查当前视图并切换到系统视图
        current_view = check_current_view(current_prompt)

        if current_view == "user_view":
            cmd_output, current_prompt = execute_command(
                net_connect, 
                "system-view", 
                device_executed_commands, 
                system_info, 
                current_prompt,
                device_name
            )
        else:
            print("已经在系统视图中，无需切换视图")

        # 使用智能接口配置替代批量命令执行
        current_prompt = smart_interface_config(
            net_connect, interface1, "172.16.1.1", "255.255.255.0", 
            mtu_value, device_executed_commands, system_info, current_prompt, device_name
        )
        
        current_prompt = smart_interface_config(
            net_connect, interface2, "172.16.2.1", "255.255.255.0", 
            mtu_value, device_executed_commands, system_info, current_prompt, device_name
        )
        
        # 断开连接
        net_connect.disconnect()
        print(f"\nMTU配置完成，设备 {device_name} 已断开连接")
        
        return True, device_executed_commands, system_info, "", device_name
        
    except Exception as e:
        error_msg = str(e.args[0]) if e.args else str(e)
        device_key = str(e.args[1]) if len(e.args) >= 2 else device_name or hostip
        print(f"\nMTU配置失败: {error_msg}")
        
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
        print('"hostip":"192.168.1.1" (设备IP地址)')
        print('"username":"admin" (登录用户名)')
        print('"password":"password" (登录密码)')
        print('"interface1":"GigabitEthernet1/0/1" (第一个接口名称)')
        print('"interface2":"GigabitEthernet1/0/2" (第二个接口名称)')
        print('"mtu_value":"1546" (MTU值，可选值：256、1546、9000)')
        
        print("\n完整示例:")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","interface1":"GigabitEthernet1/0/1","interface2":"GigabitEthernet1/0/2","mtu_value":"1546"}}\'')
        
        print("\n说明:")
        print("- 接口1将自动配置IP地址：172.16.1.1/24")
        print("- 接口2将自动配置IP地址：172.16.2.1/24")
        print("- MTU值可选：256、1546、9000")
        print("- 接口名称请使用设备实际支持的格式：")
        print("  * GigabitEthernet1/0/1 或 Gi1/0/1")
        print("  * Ten-GigabitEthernet1/0/1 或 XGE1/0/1") 
        print("  * Twenty-FiveGigE1/0/1 或 25GE1/0/1")
        print("  * FortyGigE1/0/1 或 40GE1/0/1")
        print("  * HundredGigE1/0/1 或 100GE1/0/1")
        print("  * FourHundredGigE1/0/1 或 400GE1/0/1")
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
            file_suffix="mtu_config"
        )
        
        # 获取参数
        hostip = config.get('hostip', '').strip()
        username = config.get('username', '').strip()
        password = config.get('password', '').strip()
        interface1 = config.get('interface1', '').strip()
        interface2 = config.get('interface2', '').strip()
        mtu_value = config.get('mtu_value', '1546')
        
        # 检查必要参数
        missing = []
        if not hostip:
            missing.append('hostip')
        if not username:
            missing.append('username')
        if not password:
            missing.append('password')
        if not interface1:
            missing.append('interface1')
        if not interface2:
            missing.append('interface2')
        
        if missing:
            error_msg = f"缺少必要参数: {', '.join(missing)}"
            print(f"错误: {error_msg}")
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="mtu_config",
                error_message={"General": error_msg}
            )
            sys.exit(1)
        
        # 验证MTU值
        is_valid, result = validate_mtu_value(mtu_value)
        if not is_valid:
            print(f"错误: {result}")
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="mtu_config",
                error_message={"General": result}
            )
            sys.exit(1)
        
        # 初始化结果收集
        all_commands = {}
        all_system_info = {}
        final_status = "succeed"
        result = {"error_message": {}}
        
        # 执行MTU配置
        success, executed_commands, system_info, error_msg, device_name = mtu_config(
            hostip, username, password, interface1, interface2, mtu_value
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
            file_suffix="mtu_config",
            **result
        )
        
    except json.JSONDecodeError as e:
        print(f"JSON参数解析错误: {str(e)}")
        print("请检查参数格式是否正确")
        # 写入失败日志
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="mtu_config",
                error_message={"General": f"JSON参数解析错误: {str(e)}"}
            )
        except:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
        # 确保即使出错也写入日志
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="mtu_config",
                error_message={"General": str(e)}
            )
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
