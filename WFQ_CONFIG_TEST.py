#写一个配置H3C交换机接口WFQ（Weighted Fair Queuing）功能的脚本。
#1. 使用现成的login_args.py中的login函数来实现登录认证等功能
#2. 登录成功后，默认下发system-view命令，用来进入系统视图
#3. 配置指定接口的WFQ队列权重

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

def validate_weight_value(weight_value):
    """验证权重值是否有效"""
    try:
        weight = int(weight_value)
        if 1 <= weight <= 127:
            return True, weight
        else:
            return False, "权重值必须在1-127之间"
    except ValueError:
        return False, "权重值必须是数字"

def normalize_interface_name(interface_name):
    """直接使用用户输入的接口名称，不进行任何转换"""
    # 用户最了解自己设备的接口命名规范，直接使用原始输入
    return interface_name.strip()

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
                    interaction_record += f"\n{cmd_output.strip()}"
                executed_commands.append(interaction_record)
        
        elif command.startswith("interface "):
            # 进入接口视图
            interface_name = command.replace("interface ", "")
            if device_name and '[' in current_prompt:
                new_prompt = f"[{device_name}-{interface_name}]"
            else:
                try:
                    new_prompt = net_connect.find_prompt()
                except:
                    if device_name:
                        new_prompt = f"[{device_name}-{interface_name}]"
            
            # 记录命令
            if log_command:
                interaction_record = f"{current_prompt}{command}"
                if cmd_output.strip():
                    interaction_record += f"\n{cmd_output.strip()}"
                executed_commands.append(interaction_record)
        
        elif command == "quit":
            # quit命令退出当前视图
            if device_name:
                if '-' in current_prompt:  # 从接口视图退出到系统视图
                    new_prompt = f"[{device_name}]"
                elif '[' in current_prompt:  # 从系统视图退出到用户视图
                    new_prompt = f"<{device_name}>"
            else:
                try:
                    new_prompt = net_connect.find_prompt()
                except:
                    new_prompt = current_prompt
            
            # 记录命令
            if log_command:
                interaction_record = f"{current_prompt}{command}"
                if cmd_output.strip():
                    interaction_record += f"\n{cmd_output.strip()}"
                executed_commands.append(interaction_record)
        
        else:
            # 其他命令不改变提示符
            try:
                # 尝试获取当前提示符（但不强制）
                temp_prompt = net_connect.find_prompt()
                if temp_prompt and len(temp_prompt) > 1:
                    new_prompt = temp_prompt
            except:
                pass
            
            # 记录命令
            if log_command:
                interaction_record = f"{current_prompt}{command}"
                if cmd_output.strip():
                    interaction_record += f"\n{cmd_output.strip()}"
                executed_commands.append(interaction_record)
        
        # 使用check_device_output模块检查错误
        status = check_device_output.check_device_output(cmd_output)
        if status == "Failed":
            # 找到错误但不中断，记录错误信息
            print(f"⚠️ 命令可能有问题: {command}")
            print(f"设备回显: {cmd_output}")
        
        return cmd_output, new_prompt
        
    except Exception as e:
        error_msg = f"执行命令失败: {command}, 错误: {str(e)}"
        print(f"❌ {error_msg}")
        if log_command:
            executed_commands.append(f"{current_prompt}{command} - ERROR: {str(e)}")
        raise Exception(error_msg)

def configure_wfq_interface(net_connect, interface, weights, executed_commands, system_info, current_prompt, device_name):
    """配置接口WFQ功能"""
    
    # 进入接口配置模式
    cmd_output, current_prompt = execute_command(
        net_connect, 
        f"interface {interface}", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    # 启用WFQ权重模式
    cmd_output, current_prompt = execute_command(
        net_connect, 
        "qos wfq weight", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    # 配置各个队列的权重
    queue_commands = [
        f"qos wfq be group 1 weight {weights['be']}",
        f"qos wfq af1 group 1 weight {weights['af1']}",
        f"qos wfq af2 group 1 weight {weights['af2']}",
        f"qos wfq af3 group 1 weight {weights['af3']}",
        f"qos wfq af4 group 1 weight {weights['af4']}",
        f"qos wfq ef group 1 weight {weights['ef']}",
        f"qos wfq cs6 group 1 weight {weights['cs6']}",
        f"qos wfq cs7 group 1 weight {weights['cs7']}"
    ]
    
    for queue_cmd in queue_commands:
        cmd_output, current_prompt = execute_command(
            net_connect, 
            queue_cmd, 
            executed_commands, 
            system_info, 
            current_prompt,
            device_name
        )
    
    # 退出接口配置模式
    cmd_output, current_prompt = execute_command(
        net_connect, 
        "quit", 
        executed_commands, 
        system_info, 
        current_prompt,
        device_name
    )
    
    return current_prompt

def wfq_config(hostip, username, password, interface, weights):
    """执行WFQ配置的主要逻辑"""
    print(f"\n开始配置设备 {hostip} 的WFQ功能...")
    print(f"目标接口: {interface}")
    print(f"权重配置: {weights}")
    
    executed_commands = []
    system_info = None
    device_name = None
    
    try:
        # 1. SSH登录
        print(f"\n正在连接设备 {hostip}...")
        ssh = login_args.login(hostip, username, password)
        if not ssh:
            return False, executed_commands, system_info, "SSH连接失败", hostip
        
        print("SSH连接成功!")
        
        # 2. 获取设备基本信息
        try:
            # 获取初始提示符
            current_prompt = ssh.find_prompt()
            print(f"当前提示符: {current_prompt}")
            
            # 尝试从提示符提取设备名
            if '<' in current_prompt and '>' in current_prompt:
                device_name = current_prompt.replace('<', '').replace('>', '')
            elif current_prompt.strip():
                device_name = current_prompt.strip()
            else:
                device_name = hostip
            
            print(f"设备名称: {device_name}")
            
            # 获取系统信息
            system_info = get_system_info.get_system_info(ssh)
            print("系统信息获取完成")
            
        except Exception as e:
            print(f"获取系统信息失败: {e}")
            device_name = hostip
            system_info = f"获取系统信息失败: {str(e)}"
        
        # 3. 进入系统视图
        print("\n进入系统视图...")
        cmd_output, current_prompt = execute_command(
            ssh, 
            "system-view", 
            executed_commands, 
            system_info, 
            current_prompt,
            device_name
        )
        
        # 4. 配置WFQ
        print(f"\n开始配置接口 {interface} 的WFQ功能...")
        current_prompt = configure_wfq_interface(
            ssh, 
            interface, 
            weights,
            executed_commands, 
            system_info, 
            current_prompt, 
            device_name
        )
        
        # 5. 退出
        cmd_output, current_prompt = execute_command(
            ssh, 
            "quit", 
            executed_commands, 
            system_info, 
            current_prompt,
            device_name
        )
        
        print(f"\n✅ 设备 {hostip} WFQ配置完成!")
        ssh.disconnect()
        return True, executed_commands, system_info, None, device_name
        
    except Exception as e:
        error_msg = f"配置过程中发生错误: {str(e)}"
        print(f"\n❌ {error_msg}")
        try:
            ssh.disconnect()
        except:
            pass
        return False, executed_commands, system_info, error_msg, device_name or hostip

def main():
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("使用方法:")
        print(f'python {os.path.basename(__file__)} \'{{参数}}\'')
        print("\n参数格式:")
        print('"hostip":"192.168.1.1" (设备IP地址)')
        print('"username":"admin" (登录用户名)')
        print('"password":"password" (登录密码)')
        print('"interface":"GigabitEthernet1/0/19" (接口名称)')
        print('"weight_be":"1" (BE队列权重，范围1-127)')
        print('"weight_af1":"2" (AF1队列权重，范围1-127)')
        print('"weight_af2":"2" (AF2队列权重，范围1-127)')
        print('"weight_af3":"2" (AF3队列权重，范围1-127)')
        print('"weight_af4":"2" (AF4队列权重，范围1-127)')
        print('"weight_ef":"2" (EF队列权重，范围1-127)')
        print('"weight_cs6":"2" (CS6队列权重，范围1-127)')
        print('"weight_cs7":"3" (CS7队列权重，范围1-127)')
        
        print("\n完整示例:")
        print(f'python {os.path.basename(__file__)} \'{{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","interface":"GigabitEthernet1/0/19","weight_be":"1","weight_af1":"2","weight_af2":"2","weight_af3":"2","weight_af4":"2","weight_ef":"2","weight_cs6":"2","weight_cs7":"3"}}\'')
        
        print("\n说明:")
        print("- 权重值范围：1-127")
        print("- 权重值越大，队列优先级越高")
        print("- 接口名称请使用设备实际支持的格式：")
        print("  * GigabitEthernet1/0/1 或 Gi1/0/1")
        print("  * Ten-GigabitEthernet1/0/1 或 XGE1/0/1") 
        print("  * Twenty-FiveGigE1/0/1 或 25GE1/0/1")
        print("  * FortyGigE1/0/1 或 40GE1/0/1")
        print("  * HundredGigE1/0/1 或 100GE1/0/1")
        print("- 队列说明:")
        print("  * BE: Best Effort（尽力而为）")
        print("  * AF1-AF4: Assured Forwarding（保证转发）")
        print("  * EF: Expedited Forwarding（加速转发）")
        print("  * CS6: Class Selector 6")
        print("  * CS7: Class Selector 7")
        sys.exit(1)
    
    # 解析JSON参数
    try:
        json_str = sys.argv[1]
        
        # 检查是否是文件路径
        if json_str.endswith('.json') and os.path.exists(json_str):
            print(f"📁 从文件读取参数: {json_str}")
            with open(json_str, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            # 处理命令行JSON字符串
            if json_str.startswith("'") and json_str.endswith("'"):
                json_str = json_str[1:-1]
            
            # PowerShell会移除双引号，我们需要修复JSON格式
            if not json_str.startswith('"') and ':' in json_str:
                # 看起来像是PowerShell处理后的格式，尝试修复
                import re
                # 为键添加双引号: key: -> "key":
                json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
                # 为字符串值添加双引号: :"value" -> :"value"（但不要影响数字）
                json_str = re.sub(r':\s*([a-zA-Z0-9._@/-]+)(?=\s*[,}])', r':"\1"', json_str)
            
            config = json.loads(json_str)
        
        # 在成功解析参数后立即记录Running状态的日志
        write_log.write_log(
            "Running", 
            {}, 
            {}, 
            file_suffix="wfq_config"
        )
        
        # 获取参数
        hostip = config.get('hostip', '').strip()
        username = config.get('username', '').strip()
        password = config.get('password', '').strip()
        interface = config.get('interface', '').strip()
        
        # 获取权重参数
        weights = {
            'be': config.get('weight_be', '1'),
            'af1': config.get('weight_af1', '2'),
            'af2': config.get('weight_af2', '2'),
            'af3': config.get('weight_af3', '2'),
            'af4': config.get('weight_af4', '2'),
            'ef': config.get('weight_ef', '2'),
            'cs6': config.get('weight_cs6', '2'),
            'cs7': config.get('weight_cs7', '3')
        }
        
        # 检查必要参数
        missing = []
        if not hostip:
            missing.append('hostip')
        if not username:
            missing.append('username')
        if not password:
            missing.append('password')
        if not interface:
            missing.append('interface')
        
        if missing:
            error_msg = f"缺少必要参数: {', '.join(missing)}"
            print(f"错误: {error_msg}")
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="wfq_config",
                error_message={"General": error_msg}
            )
            sys.exit(1)
        
        # 验证权重值
        for queue_name, weight_value in weights.items():
            is_valid, result = validate_weight_value(weight_value)
            if not is_valid:
                error_msg = f"队列 {queue_name} 的权重值无效: {result}"
                print(f"错误: {error_msg}")
                write_log.write_log(
                    "Failed", 
                    {}, 
                    {}, 
                    file_suffix="wfq_config",
                    error_message={"General": error_msg}
                )
                sys.exit(1)
            weights[queue_name] = result  # 使用验证后的数值
        
        # 初始化结果收集
        all_commands = {}
        all_system_info = {}
        final_status = "succeed"
        result = {"error_message": {}}
        
        # 执行WFQ配置
        success, executed_commands, system_info, error_msg, device_name = wfq_config(
            hostip, username, password, interface, weights
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
            file_suffix="wfq_config",
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
                file_suffix="wfq_config",
                error_message={"General": f"JSON参数解析错误: {str(e)}"}
            )
        except:
            pass
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="wfq_config",
                error_message={"General": "用户中断操作"}
            )
        except:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"程序执行错误: {str(e)}")
        try:
            write_log.write_log(
                "Failed", 
                {}, 
                {}, 
                file_suffix="wfq_config",
                error_message={"General": f"程序执行错误: {str(e)}"}
            )
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
