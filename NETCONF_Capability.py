#专门用于获取H3C设备NETCONF Capabilities的工具程序
#用法: python NETCONF_Capability.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123"}'

import sys
import os
import json
import time
from datetime import datetime

# 导入NETCONF相关模块
try:
    from ncclient import manager
    # 修复RPCError导入路径问题
    try:
        from ncclient.operations.errors import RPCError
    except ImportError:
        try:
            from ncclient.operations import RPCError
        except ImportError:
            from ncclient import NCClientError as RPCError
except ImportError:
    print("错误: 缺少ncclient模块，请安装: pip install ncclient")
    sys.exit(1)

# 导入项目模块
from write_log import write_log

def analyze_device_capabilities(capabilities):
    """分析设备capabilities并提供操作建议"""
    analysis = {
        "netconf_version": [],
        "datastores": [],
        "operations": [],
        "yang_models": [],
        "recommendations": []
    }
    
    # 分析NETCONF版本
    for cap in capabilities:
        if "netconf:base:1.0" in cap:
            analysis["netconf_version"].append("NETCONF 1.0")
        elif "netconf:base:1.1" in cap:
            analysis["netconf_version"].append("NETCONF 1.1")
    
    # 分析数据存储能力
    for cap in capabilities:
        if "candidate" in cap:
            analysis["datastores"].append("candidate")
            analysis["recommendations"].append("支持candidate配置，可以先验证配置再提交")
        elif "startup" in cap:
            analysis["datastores"].append("startup")
            analysis["recommendations"].append("支持startup配置，配置重启后生效")
        elif "rollback-on-error" in cap:
            analysis["operations"].append("rollback-on-error")
            analysis["recommendations"].append("支持错误自动回滚，配置更安全")
    
    # 分析YANG模型（重点关注H3C相关）
    h3c_models = []
    standard_models = []
    interface_models = []
    network_models = []
    
    for cap in capabilities:
        if "h3c.com" in cap.lower():
            # H3C私有模型
            model_name = cap.split('/')[-1] if '/' in cap else cap.split(':')[-1]
            h3c_models.append(model_name)
            
            # 特别标识接口相关模型
            if "interface" in cap.lower():
                interface_models.append(cap)
        elif "ietf" in cap and "yang" in cap:
            # IETF标准模型
            model_name = cap.split('/')[-1] if '/' in cap else cap.split(':')[-1]
            standard_models.append(model_name)
            
            # 标识接口和网络相关模型
            if "interface" in cap.lower() or "ip" in cap.lower():
                interface_models.append(cap)
            elif "routing" in cap.lower() or "bgp" in cap.lower() or "ospf" in cap.lower():
                network_models.append(cap)
    
    analysis["yang_models"] = {
        "h3c_private": h3c_models[:10],  # 只显示前10个
        "ietf_standard": standard_models[:10],
        "interface_related": interface_models[:5],
        "network_related": network_models[:5]
    }
    
    # 基于分析给出具体建议
    if "candidate" in analysis["datastores"]:
        analysis["recommendations"].append("建议使用candidate配置模式进行配置变更")
    
    if h3c_models:
        analysis["recommendations"].append("检测到H3C私有YANG模型，可以使用H3C特定的XML命名空间")
    
    if standard_models:
        analysis["recommendations"].append("支持IETF标准模型，可以尝试标准化配置方式")
    
    if interface_models:
        analysis["recommendations"].append("支持接口配置模型，可以进行接口IP地址、描述等配置")
    
    if network_models:
        analysis["recommendations"].append("支持网络协议模型，可以进行路由协议配置")
    
    return analysis

def suggest_configuration_methods(analysis):
    """根据capabilities分析结果建议配置方法"""
    suggestions = {
        "interface_config": [],
        "network_config": [],
        "best_practices": []
    }
    
    # 接口配置建议
    if analysis.get("yang_models", {}).get("interface_related"):
        suggestions["interface_config"].append("设备支持接口配置，可以配置IP地址、描述等")
        
        # 检查是否有IETF标准接口模型
        ietf_interface = False
        for model in analysis["yang_models"]["interface_related"]:
            if "ietf" in model.lower() and "interface" in model.lower():
                ietf_interface = True
                break
        
        if ietf_interface:
            suggestions["interface_config"].append("优先使用IETF标准接口模型进行配置")
            suggestions["interface_config"].append("XML格式: <interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'>")
        
        # 检查是否有H3C接口模型
        h3c_interface = False
        for model in analysis["yang_models"]["h3c_private"]:
            if "interface" in model.lower():
                h3c_interface = True
                break
        
        if h3c_interface:
            suggestions["interface_config"].append("备选使用H3C私有接口模型")
            suggestions["interface_config"].append("XML格式: <top xmlns='http://www.h3c.com/netconf/config:1.0'>")
    
    # 网络配置建议
    if analysis.get("yang_models", {}).get("network_related"):
        suggestions["network_config"].append("设备支持网络协议配置")
        for model in analysis["yang_models"]["network_related"][:3]:
            if "bgp" in model.lower():
                suggestions["network_config"].append("支持BGP协议配置")
            elif "ospf" in model.lower():
                suggestions["network_config"].append("支持OSPF协议配置")
            elif "routing" in model.lower():
                suggestions["network_config"].append("支持路由配置")
    
    # 最佳实践建议
    if "candidate" in analysis.get("datastores", []):
        suggestions["best_practices"].extend([
            "使用candidate数据存储进行安全配置",
            "配置流程: lock -> edit-config -> validate -> commit -> unlock",
            "出错时可以使用discard-changes回滚"
        ])
    else:
        suggestions["best_practices"].append("直接修改running配置，请谨慎操作")
    
    if "rollback-on-error" in analysis.get("operations", []):
        suggestions["best_practices"].append("支持错误自动回滚，可以安全尝试复杂配置")
    
    return suggestions

def get_device_capabilities_with_analysis(host, username, password, port=830):
    """获取设备capabilities并进行分析"""
    try:
        with manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=30,
            device_params={'name': 'h3c'},
            hostkey_verify=False,
            look_for_keys=False,
            allow_agent=False
        ) as m:
            print(f"🔗 已连接到设备: {host}")
            print(f"📋 设备支持的NETCONF功能 (共{len(m.server_capabilities)}项):")
            
            capabilities_list = []
            for i, capability in enumerate(m.server_capabilities, 1):
                capability_line = f"  {i:3d}. {capability}"
                print(capability_line)
                capabilities_list.append(capability_line)
            
            # 分析capabilities
            analysis = analyze_device_capabilities(list(m.server_capabilities))
            
            print(f"\n📊 Capabilities 分析结果:")
            print(f"🔧 NETCONF版本: {', '.join(analysis['netconf_version'])}")
            print(f"🗄️  数据存储: {', '.join(analysis['datastores'])}")
            print(f"⚙️  特殊操作: {', '.join(analysis['operations'])}")
            
            if analysis['yang_models']['h3c_private']:
                print(f"🏢 H3C私有模型: {len(analysis['yang_models']['h3c_private'])} 个")
                print(f"   前5个: {analysis['yang_models']['h3c_private'][:5]}")
            
            if analysis['yang_models']['ietf_standard']:
                print(f"📋 IETF标准模型: {len(analysis['yang_models']['ietf_standard'])} 个")
                print(f"   前5个: {analysis['yang_models']['ietf_standard'][:5]}")
            
            if analysis['yang_models']['interface_related']:
                print(f"🔌 接口相关模型: {len(analysis['yang_models']['interface_related'])} 个")
                for model in analysis['yang_models']['interface_related']:
                    print(f"   - {model}")
            
            if analysis['yang_models']['network_related']:
                print(f"🌐 网络协议模型: {len(analysis['yang_models']['network_related'])} 个")
                for model in analysis['yang_models']['network_related']:
                    print(f"   - {model}")
            
            print(f"\n💡 使用建议:")
            for i, recommendation in enumerate(analysis['recommendations'], 1):
                print(f"   {i}. {recommendation}")
            
            # 获取配置方法建议
            config_suggestions = suggest_configuration_methods(analysis)
            
            if config_suggestions['interface_config']:
                print(f"\n🔌 接口配置建议:")
                for i, suggestion in enumerate(config_suggestions['interface_config'], 1):
                    print(f"   {i}. {suggestion}")
            
            if config_suggestions['network_config']:
                print(f"\n🌐 网络配置建议:")
                for i, suggestion in enumerate(config_suggestions['network_config'], 1):
                    print(f"   {i}. {suggestion}")
            
            if config_suggestions['best_practices']:
                print(f"\n✅ 最佳实践建议:")
                for i, suggestion in enumerate(config_suggestions['best_practices'], 1):
                    print(f"   {i}. {suggestion}")
            
            return True, {
                "capabilities": list(m.server_capabilities),
                "capabilities_formatted": capabilities_list,
                "total_count": len(m.server_capabilities),
                "analysis": analysis,
                "configuration_suggestions": config_suggestions
            }
            
    except Exception as e:
        error_msg = f"连接失败: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg

def save_capabilities_to_files(host, result):
    """将capabilities结果保存到文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存原始capabilities列表
    capabilities_file = f"capabilities_{host.replace('.', '_')}_{timestamp}.txt"
    with open(capabilities_file, 'w', encoding='utf-8') as f:
        f.write(f"设备: {host}\n")
        f.write(f"时间: {timestamp}\n")
        f.write(f"总数: {result['total_count']}\n")
        f.write("=" * 80 + "\n\n")
        
        for cap_line in result['capabilities_formatted']:
            f.write(cap_line + "\n")
    
    print(f"💾 Capabilities列表已保存到: {capabilities_file}")
    
    # 保存分析报告
    analysis_file = f"capabilities_analysis_{host.replace('.', '_')}_{timestamp}.md"
    with open(analysis_file, 'w', encoding='utf-8') as f:
        f.write(f"# 设备 {host} NETCONF Capabilities 分析报告\n\n")
        f.write(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write(f"## 基本信息\n\n")
        f.write(f"- **设备地址:** {host}\n")
        f.write(f"- **总Capabilities数量:** {result['total_count']}\n")
        f.write(f"- **NETCONF版本:** {', '.join(result['analysis']['netconf_version'])}\n")
        f.write(f"- **数据存储:** {', '.join(result['analysis']['datastores'])}\n")
        f.write(f"- **特殊操作:** {', '.join(result['analysis']['operations'])}\n\n")
        
        f.write(f"## YANG模型分析\n\n")
        
        if result['analysis']['yang_models']['h3c_private']:
            f.write(f"### H3C私有模型 ({len(result['analysis']['yang_models']['h3c_private'])} 个)\n")
            for model in result['analysis']['yang_models']['h3c_private']:
                f.write(f"- {model}\n")
            f.write("\n")
        
        if result['analysis']['yang_models']['ietf_standard']:
            f.write(f"### IETF标准模型 ({len(result['analysis']['yang_models']['ietf_standard'])} 个)\n")
            for model in result['analysis']['yang_models']['ietf_standard']:
                f.write(f"- {model}\n")
            f.write("\n")
        
        if result['analysis']['yang_models']['interface_related']:
            f.write(f"### 接口相关模型 ({len(result['analysis']['yang_models']['interface_related'])} 个)\n")
            for model in result['analysis']['yang_models']['interface_related']:
                f.write(f"- {model}\n")
            f.write("\n")
        
        if result['analysis']['yang_models']['network_related']:
            f.write(f"### 网络协议模型 ({len(result['analysis']['yang_models']['network_related'])} 个)\n")
            for model in result['analysis']['yang_models']['network_related']:
                f.write(f"- {model}\n")
            f.write("\n")
        
        f.write(f"## 使用建议\n\n")
        for i, rec in enumerate(result['analysis']['recommendations'], 1):
            f.write(f"{i}. {rec}\n")
        f.write("\n")
        
        if 'configuration_suggestions' in result:
            config_suggestions = result['configuration_suggestions']
            
            if config_suggestions['interface_config']:
                f.write(f"## 接口配置建议\n\n")
                for i, suggestion in enumerate(config_suggestions['interface_config'], 1):
                    f.write(f"{i}. {suggestion}\n")
                f.write("\n")
            
            if config_suggestions['network_config']:
                f.write(f"## 网络配置建议\n\n")
                for i, suggestion in enumerate(config_suggestions['network_config'], 1):
                    f.write(f"{i}. {suggestion}\n")
                f.write("\n")
            
            if config_suggestions['best_practices']:
                f.write(f"## 最佳实践建议\n\n")
                for i, suggestion in enumerate(config_suggestions['best_practices'], 1):
                    f.write(f"{i}. {suggestion}\n")
                f.write("\n")
    
    print(f"📋 分析报告已保存到: {analysis_file}")
    
    return capabilities_file, analysis_file

def main():
    """主函数"""
    print("=" * 60)
    print("📋 H3C设备NETCONF Capabilities查询工具")
    print("=" * 60)
    
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python NETCONF_Capability.py <JSON配置参数>")
        print()
        print("JSON参数格式:")
        print('{')
        print('  "hostip": "10.12.174.228",')
        print('  "username": "admin",') 
        print('  "password": "H3c.com@123"')
        print('}')
        print()
        print("示例:")
        print('python NETCONF_Capability.py \'{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123"}\'')
        print()
        print("功能说明:")
        print("- 查询设备支持的所有NETCONF capabilities")
        print("- 分析capabilities并给出配置建议")  
        print("- 识别接口配置相关的YANG模型")
        print("- 提供具体的XML配置格式建议")
        print("- 自动保存结果到文件和日志")
        return
    
    # 解析JSON参数
    try:
        # 将所有参数合并为一个字符串（处理PowerShell参数分割问题）
        json_str = ' '.join(sys.argv[1:])
        print(f"📝 输入参数: {json_str}")
        
        # 检查是否是文件路径
        if json_str.endswith('.json') and os.path.exists(json_str):
            print(f"📁 从文件读取参数: {json_str}")
            with open(json_str, 'r', encoding='utf-8') as f:
                params = json.load(f)
        else:
            # 移除可能的引号
            if json_str.startswith("'") and json_str.endswith("'"):
                json_str = json_str[1:-1]
            
            # PowerShell会移除双引号，我们需要修复JSON格式
            if not json_str.startswith('"') and ':' in json_str:
                # 看起来像是PowerShell处理后的格式，尝试修复
                print("⚠️  检测到PowerShell处理的参数格式，尝试修复...")
                
                # 简单的JSON修复：添加双引号到键和字符串值
                import re
                # 为键添加双引号: key: -> "key":
                json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
                # 为字符串值添加双引号: :"value" -> :"value"（但不要影响数字）
                json_str = re.sub(r':\s*([a-zA-Z0-9._@-]+)(?=\s*[,}])', r':"\1"', json_str)
                
                print(f"🔧 修复后的JSON: {json_str}")
            
            params = json.loads(json_str)
        
        # 提取参数
        hostip = params.get('hostip')
        username = params.get('username') 
        password = params.get('password')
        port = params.get('port', 830)
        
        # 验证必需参数
        if not hostip:
            print("❌ 缺少必需参数: hostip")
            return
        if not username:
            print("❌ 缺少必需参数: username")
            return
        if not password:
            print("❌ 缺少必需参数: password")
            return
            
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
        print("请检查参数格式是否正确")
        return
    except Exception as e:
        print(f"❌ 参数解析失败: {e}")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print(f"\n🎯 正在查询设备capabilities: {hostip}")
    print("-" * 50)
    
    try:
        # 开始查询
        print("🚀 开始查询设备NETCONF capabilities...")
        write_log("Running", None, None, file_suffix=f"NETCONF_Capability_{timestamp}")
        
        success, result = get_device_capabilities_with_analysis(hostip, username, password, port)
        
        if success:
            print(f"\n✅ Capabilities查询完成!")
            
            # 保存结果到文件
            capabilities_file, analysis_file = save_capabilities_to_files(hostip, result)
            
            # 记录成功日志
            write_log(
                "Completed", 
                {
                    "netconf_capabilities": result['capabilities_formatted'],
                    "total_capabilities": result['total_count'],
                    "capabilities_analysis": result['analysis'],
                    "configuration_suggestions": result['configuration_suggestions'],
                    "output_files": {
                        "capabilities_file": capabilities_file,
                        "analysis_file": analysis_file
                    }
                },
                {hostip: f"设备支持{result['total_count']}个NETCONF能力"},
                file_suffix=f"NETCONF_Capability_{timestamp}"
            )
            
            print(f"\n📊 查询汇总:")
            print(f"   - 总capabilities数量: {result['total_count']}")
            print(f"   - NETCONF版本: {', '.join(result['analysis']['netconf_version'])}")
            print(f"   - 支持数据存储: {', '.join(result['analysis']['datastores'])}")
            print(f"   - H3C私有模型: {len(result['analysis']['yang_models']['h3c_private'])} 个")
            print(f"   - IETF标准模型: {len(result['analysis']['yang_models']['ietf_standard'])} 个")
            print(f"   - 接口相关模型: {len(result['analysis']['yang_models']['interface_related'])} 个")
            
        else:
            print(f"\n❌ Capabilities查询失败!")
            
            # 记录失败日志
            write_log(
                "Failed", 
                f"设备capabilities查询失败",
                {hostip: hostip},
                error_message={"error_message": result},
                file_suffix=f"NETCONF_Capability_{timestamp}"
            )
            
    except Exception as e:
        print(f"❌ 设备 {hostip} 查询失败: {e}")
        write_log("Failed", f"capabilities查询异常", hostip, str(e), file_suffix=f"NETCONF_Capability_{timestamp}")
        return
    
    print(f"\n✅ 查询完成! 日志文件: NETCONF_Capability_{timestamp}.log")

if __name__ == "__main__":
    main()
