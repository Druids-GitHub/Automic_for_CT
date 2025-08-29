#写一个通过NETCONF协议配置H3C路由器、交换机的脚本。
#1. 使用NETCONF协议连接设备
#2. 通过XML格式发送配置命令
#3. 支持多种配置操作：接口配置、VLAN配置等

import sys
import os
import json
import time
import re
from datetime import datetime
import xml.etree.ElementTree as ET

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
import login_args
from write_log import write_log

def sanitize_description(description):
    """清理和转换描述文本，确保H3C设备兼容"""
    if not description:
        return description
    
    # 汉字到英文的映射
    chinese_to_english = {
        '配置': 'Config',
        '测试': 'Test',
        '简化版': 'Simple', 
        '简化': 'Simple',
        '版': 'Ver',
        '接口': 'Interface',
        '描述': 'Description',
        '网络': 'Network',
        '设备': 'Device',
        '管理': 'Management',
        '服务': 'Service',
        '连接': 'Connection',
        '端口': 'Port',
        '交换机': 'Switch',
        '路由器': 'Router'
    }
    
    # 替换汉字
    sanitized = description
    for chinese, english in chinese_to_english.items():
        sanitized = sanitized.replace(chinese, english)
    
    # 移除或替换特殊字符
    special_chars = {
        '（': '(',
        '）': ')',
        '，': ',',
        '。': '.',
        '：': ':',
        '；': ';',
        '！': '!',
        '？': '?',
        '【': '[',
        '】': ']',
        '"': '"',
        '"': '"',
        ''': "'",
        ''': "'"
    }
    
    for chinese_char, english_char in special_chars.items():
        sanitized = sanitized.replace(chinese_char, english_char)
    
    # 确保只包含ASCII字符
    try:
        sanitized.encode('ascii')
        print(f"📝 描述已转换: '{description}' -> '{sanitized}'")
        return sanitized
    except UnicodeEncodeError:
        # 如果仍有非ASCII字符，使用通用描述
        fallback = f"NETCONF-Config-{hash(description) % 10000:04d}"
        print(f"⚠️  描述包含特殊字符，使用备用描述: '{description}' -> '{fallback}'")
        return fallback

def interface_name_to_ifindex(interface_name):
    """
    将H3C接口名称转换为IfIndex - 改进版
    
    基于H3C设备的实际规律进行映射：
    - 不同接口类型有不同的起始范围
    - 支持更多H3C接口类型
    - 更精确的映射算法
    """
    if not interface_name:
        return 1
    
    # 标准化接口名称
    interface_name = interface_name.strip().lower()
    
    # H3C接口类型映射表（基于实际设备观察）
    interface_type_mapping = {
        # 以太网接口
        'gigabitethernet': {'base': 1, 'multiplier': 1},
        'ge': {'base': 1, 'multiplier': 1},
        
        # 万兆以太网
        'tengigabitethernet': {'base': 25, 'multiplier': 1},
        'xge': {'base': 25, 'multiplier': 1},
        
        # H3C特有命名
        'wge': {'base': 25, 'multiplier': 1},  # 万兆以太网
        
        # 四万兆以太网
        'fortygigabitethernet': {'base': 49, 'multiplier': 1}, 
        'fortygige': {'base': 49, 'multiplier': 1},
        'xle': {'base': 49, 'multiplier': 1},
        
        # 百兆以太网
        'hundredgige': {'base': 53, 'multiplier': 1},
        'cxp': {'base': 53, 'multiplier': 1},
        
        # 管理接口
        'management': {'base': 127, 'multiplier': 1},
        'mgmt': {'base': 127, 'multiplier': 1},
        
        # VLAN接口
        'vlan-interface': {'base': 128, 'multiplier': 1},
        'vlan': {'base': 128, 'multiplier': 1},
    }
    
    # 找到匹配的接口类型
    matched_type = None
    for type_name, config in interface_type_mapping.items():
        if interface_name.startswith(type_name):
            matched_type = type_name
            break
    
    if not matched_type:
        print(f"⚠️  未识别的接口类型: {interface_name}, 使用默认IfIndex=1")
        return 1
    
    # 解析端口号部分
    try:
        port_part = interface_name[len(matched_type):]
        
        # 处理不同的端口号格式
        if '/' in port_part:
            # 格式: 1/0/1 或 1/1 
            parts = [int(p) for p in port_part.split('/')]
            if len(parts) == 3:
                # 槽位/子槽位/端口
                slot, subslot, port = parts
                ifindex = interface_type_mapping[matched_type]['base'] + (slot - 1) * 8 + port - 1
            elif len(parts) == 2:
                # 槽位/端口
                slot, port = parts
                ifindex = interface_type_mapping[matched_type]['base'] + (slot - 1) * 8 + port - 1
            else:
                ifindex = interface_type_mapping[matched_type]['base']
        else:
            # 简单数字端口
            port_num = int(port_part) if port_part.isdigit() else 1
            ifindex = interface_type_mapping[matched_type]['base'] + port_num - 1
        
        print(f"🔢 接口映射: {interface_name} -> IfIndex: {ifindex} (类型: {matched_type})")
        return ifindex
        
    except (ValueError, IndexError) as e:
        print(f"⚠️  解析接口号失败: {interface_name}, 错误: {e}, 使用默认IfIndex=1")
        return 1

def build_h3c_interface_config_xml_ifindex_only(ifindex, description=None, admin_status=None):
    """
    构建仅使用IfIndex的H3C接口配置XML
    这是H3C设备最可靠的配置方式
    
    Args:
        ifindex: 接口索引
        description: 接口描述
        admin_status: 接口管理状态 ("shutdown"/"undo shutdown")
    """
    print(f"📝 使用原始描述: '{description}'")
    if admin_status:
        print(f"🔧 接口状态操作: {admin_status}")
    
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <IfIndex>{ifindex}</IfIndex>'''
    
    if description:
        config += f'''
          <Description>{description}</Description>'''
    
    # H3C设备的AdminStatus字段含义 (基于实际设备测试)
    if admin_status:
        if admin_status.lower() == "shutdown":
            # H3C设备: AdminStatus=2表示administratively down
            config += '''
          <AdminStatus>2</AdminStatus>'''
            print("🔒 配置接口为管理关闭状态 (AdminStatus=2)")
        elif admin_status.lower() == "undo shutdown":
            # H3C设备: AdminStatus=1表示up
            config += '''
          <AdminStatus>1</AdminStatus>'''
            print("� 配置接口为管理开启状态 (AdminStatus=1)")
        else:
            print(f"⚠️  无效的接口状态: {admin_status}，忽略该配置")
            print("⚠️  支持的状态: shutdown, undo shutdown")
    
    config += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def build_h3c_interface_shutdown_xml(ifindex):
    """
    专门构建H3C接口关闭的XML配置
    分离接口状态控制，提高成功率
    """
    print(f"🔒 构建接口{ifindex}的关闭配置XML")
    
    # 方法1: 只设置AdminStatus=2
    config1 = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <IfIndex>{ifindex}</IfIndex>
          <AdminStatus>2</AdminStatus>
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config1

def build_h3c_interface_no_shutdown_xml(ifindex):
    """
    专门构建H3C接口开启的XML配置
    """
    print(f"🔓 构建接口{ifindex}的开启配置XML")
    
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <IfIndex>{ifindex}</IfIndex>
          <AdminStatus>1</AdminStatus>
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def build_h3c_interface_config_xml_by_name(interface_name, description=None):
    """
    构建使用接口全名的H3C接口配置XML
    支持正确的H3C接口类型转换
    """
    print(f"📝 使用原始描述: '{description}'")
    
    # H3C接口名称标准化映射
    interface_mapping = {
        'ge': 'GigabitEthernet',           # 千兆以太网
        'gigabitethernet': 'GigabitEthernet',
        'xge': 'TenGigabitEthernet',       # 万兆以太网 10G
        'tengigabitethernet': 'TenGigabitEthernet',
        'wge': 'Twenty-FiveGigE',          # 二十五兆以太网 25G
        'twenty-fivegige': 'Twenty-FiveGigE',
        'fortygige': 'FortyGigE',          # 四十兆以太网 40G
        'fortygigabitethernet': 'FortyGigE',
        'hundredgige': 'HundredGigE',      # 百兆以太网 100G
        'hundredgigabitethernet': 'HundredGigE',
    }
    
    # 解析接口类型
    interface_name_lower = interface_name.lower()
    full_interface_name = interface_name
    
    for short_name, full_name in interface_mapping.items():
        if interface_name_lower.startswith(short_name):
            # 替换接口类型前缀
            port_part = interface_name[len(short_name):]
            full_interface_name = full_name + port_part
            break
    
    print(f"🔧 接口名称转换: {interface_name} -> {full_interface_name}")
    
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <Name>{full_interface_name}</Name>'''
    
    if description:
        config += f'''
          <Description>{description}</Description>'''
    
    config += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def build_h3c_interface_config_xml_by_abbrev_name(interface_name, description=None):
    """
    构建使用接口缩写名的H3C接口配置XML
    支持正确的H3C接口缩写转换
    """
    print(f"📝 使用原始描述: '{description}'")
    
    # H3C接口缩写映射
    abbrev_mapping = {
        'gigabitethernet': 'GE',
        'ge': 'GE',
        'tengigabitethernet': 'XGE', 
        'xge': 'XGE',
        'wge': 'WGE',                    # 25G保持WGE缩写
        'twenty-fivegige': 'WGE',
        'fortygige': 'FGE',
        'hundredgige': 'HGE',
    }
    
    # 解析接口类型
    interface_name_lower = interface_name.lower()
    abbrev_interface_name = interface_name.upper()  # 默认大写
    
    for long_name, abbrev in abbrev_mapping.items():
        if interface_name_lower.startswith(long_name):
            port_part = interface_name[len(long_name):]
            abbrev_interface_name = abbrev + port_part
            break
    
    print(f"🔧 接口缩写转换: {interface_name} -> {abbrev_interface_name}")
    
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <AbbreviatedName>{abbrev_interface_name}</AbbreviatedName>'''
    
    if description:
        config += f'''
          <Description>{description}</Description>'''
    
    config += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def convert_to_abbreviated_name(interface_name):
    """
    将接口名称转换为H3C缩写格式
    """
    if not interface_name:
        return interface_name
        
    # 标准化
    name = interface_name.lower()
    
    # 转换映射
    abbrev_mapping = {
        'gigabitethernet': 'GE',
        'tengigabitethernet': 'XGE',
        'wge': 'WGE',  # 万兆以太网可能保持不变
        'xge': 'XGE',
        'fortygigabitethernet': 'FortyGigE',
        'fortygige': 'FortyGigE',
        'hundredgige': 'HundredGigE',
        'management': 'M-GigabitEthernet',
        'vlan-interface': 'Vlan-interface',
    }
    
    # 查找匹配的前缀
    for full_name, abbrev in abbrev_mapping.items():
        if name.startswith(full_name):
            port_part = interface_name[len(full_name):]
            return f"{abbrev}{port_part}"
    
    # 如果没有匹配，返回原名称
    return interface_name

def convert_to_full_name(interface_name):
    """
    将接口名称转换为H3C全名格式
    """
    if not interface_name:
        return interface_name
        
    # 标准化
    name = interface_name.lower()
    
    # 转换映射
    full_mapping = {
        'ge': 'GigabitEthernet',
        'wge': 'TenGigabitEthernet',  # H3C万兆以太网的标准名称
        'xge': 'TenGigabitEthernet',
        'fortygige': 'FortyGigabitEthernet',
        'hundredgige': 'HundredGigabitEthernet',
    }
    
    # 查找匹配的前缀
    for abbrev, full_name in full_mapping.items():
        if name.startswith(abbrev):
            port_part = interface_name[len(abbrev):]
            return f"{full_name}{port_part}"
    
    # 如果已经是全名格式，返回标准化版本
    if 'ethernet' in name:
        # 首字母大写
        return ''.join(word.capitalize() for word in interface_name.split())
    
    # 如果没有匹配，返回原名称
    return interface_name

def build_h3c_interface_config_xml_simple(interface_name, description=None):
    """构建最简单的H3C接口配置XML - 自动尝试多种格式"""
    # 清理描述文本
    safe_description = description
    
    # 首先尝试使用接口名称
    print(f"� 尝试使用接口名称: {interface_name}")
    
    # 方式1: 使用接口名称
    config_by_name = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <Name>{interface_name}</Name>'''
    
    if safe_description:
        config_by_name += f'''
          <Description>{safe_description}</Description>'''
    
    config_by_name += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config_by_name
    """构建最简单的H3C接口配置XML - 移除Name元素"""
    # H3C设备不支持Name元素，只使用IfIndex
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <IfIndex>1</IfIndex>'''
    
    if description:
        config += f'''
          <Description>{description}</Description>'''
    
    config += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def build_h3c_interface_config_xml_ifindex(interface_name, description=None, ifindex=1):
    """构建使用IfIndex的H3C接口配置XML"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Ifmgr>
      <Interfaces>
        <Interface>
          <IfIndex>{ifindex}</IfIndex>'''
    
    if description:
        config += f'''
          <Description>{description}</Description>'''
    
    config += '''
        </Interface>
      </Interfaces>
    </Ifmgr>
  </top>
</config>'''
    
    return config

def build_generic_interface_config_xml(interface_name, description=None):
    """构建通用接口配置XML"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <interfaces>
    <interface>
      <name>{interface_name}</name>'''
    
    if description:
        config += f'''
      <description>{description}</description>'''
    
    config += '''
    </interface>
  </interfaces>
</config>'''
    
    return config

def build_ietf_interface_config_xml(interface_name, description=None):
    """构建IETF标准接口配置XML"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <interfaces xmlns="urn:ietf:params:xml:ns:yang:ietf-interfaces">
    <interface>
      <name>{interface_name}</name>'''
    
    if description:
        config += f'''
      <description>{description}</description>'''
    
    config += '''
    </interface>
  </interfaces>
</config>'''
    
    return config

def build_h3c_vlan_config_xml_correct(vlan_id):
    """构建正确的H3C VLAN配置XML - 基于真实设备结构，移除operation属性"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <VLAN>
      <VLANs>
        <VLANID>
          <ID>{vlan_id}</ID>
        </VLANID>
      </VLANs>
    </VLAN>
  </top>
</config>'''
    
    return config

def build_h3c_hostname_config_xml(hostname):
    """构建H3C主机名配置XML - 基于真实设备结构"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <top xmlns="http://www.h3c.com/netconf/config:1.0">
    <Device>
      <Base>
        <HostName>{hostname}</HostName>
      </Base>
    </Device>
  </top>
</config>'''
    
    return config

def build_interface_config_xml(interface_name, ip_address=None, description=None):
    """构建接口配置XML（保持兼容性）"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <interface-configurations xmlns="http://cisco.com/ns/yang/Cisco-IOS-XR-ifmgr-cfg">
    <interface-configuration>
      <active>act</active>
      <interface-name>{interface_name}</interface-name>'''
    
    if description:
        config += f'''
      <description>{description}</description>'''
    
    if ip_address:
        config += f'''
      <ipv4-network xmlns="http://cisco.com/ns/yang/Cisco-IOS-XR-ipv4-io-cfg">
        <addresses>
          <primary>
            <address>{ip_address}</address>
            <netmask>255.255.255.0</netmask>
          </primary>
        </addresses>
      </ipv4-network>'''
    
    config += '''
    </interface-configuration>
  </interface-configurations>
</config>'''
    
    return config

def build_vlan_config_xml(vlan_id, vlan_name=None):
    """构建VLAN配置XML"""
    config = f'''<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <vlans xmlns="http://openconfig.net/yang/vlan">
    <vlan>
      <vlan-id>{vlan_id}</vlan-id>
      <config>
        <vlan-id>{vlan_id}</vlan-id>'''
    
    if vlan_name:
        config += f'''
        <name>{vlan_name}</name>'''
    
    config += '''
      </config>
    </vlan>
  </vlans>
</config>'''
    
    return config

def parse_config_json(config_string_or_file):
    """解析配置JSON - 支持文件路径或JSON字符串"""
    config_data = None
    
    # 判断是否是文件路径
    if config_string_or_file.endswith('.json') and os.path.exists(config_string_or_file):
        print(f"📁 从文件读取配置: {config_string_or_file}")
        try:
            with open(config_string_or_file, 'r', encoding='utf-8') as f:
                config_data = f.read()
        except Exception as e:
            raise Exception(f"读取配置文件失败: {e}")
    else:
        # 直接使用字符串
        config_data = config_string_or_file
    
    return config_data

def get_device_capabilities(host, username, password, port=830):
    """获取设备支持的NETCONF capabilities"""
    try:
        with manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=30,
            device_params={'name': 'h3c'},  # H3C设备特定参数
            hostkey_verify=False,
            look_for_keys=False,
            allow_agent=False
        ) as m:
            print(f"🔗 已连接到设备: {host}")
            print(f"📋 设备支持的NETCONF功能 (共{len(m.server_capabilities)}项):")
            
            for i, capability in enumerate(m.server_capabilities, 1):
                print(f"  {i:3d}. {capability}")
            
            return list(m.server_capabilities)
            
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return None

def explore_device_config(host, username, password, port=830):
    """探索设备的配置结构"""
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
            print(f"🔍 正在探索设备配置结构: {host}")
            
            # 获取整个配置
            try:
                result = m.get_config(source='running')
                config_xml = result.data_xml
                
                print(f"✅ 成功获取设备配置 (长度: {len(config_xml)} 字符)")
                
                # 保存到文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"device_config_sample.xml"
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(config_xml)
                
                print(f"💾 配置已保存到: {output_file}")
                
                # 分析根元素和命名空间
                try:
                    root = ET.fromstring(config_xml)
                    print(f"🏗️  根元素: {root.tag}")
                    print(f"📦 命名空间属性: {root.attrib}")
                    
                    # 显示前几级子元素
                    print(f"📂 主要配置模块:")
                    for child in root:
                        print(f"  - {child.tag} (子元素: {len(list(child))})")
                        
                except ET.ParseError as e:
                    print(f"⚠️  XML解析错误: {e}")
                
                return config_xml
                
            except Exception as e:
                print(f"❌ 获取配置失败: {e}")
                return None
            
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return None

def enable_netconf_via_ssh(host, username, password):
    """通过SSH连接启用H3C设备的NETCONF功能"""
    try:
        print(f"🔧 通过SSH启用NETCONF功能: {host}")
        
        # 使用login_args模块建立SSH连接
        device_params = {
            'hostip': host,
            'username': username,
            'password': password
        }
        
        net_connect = login_args.run_script(device_params)
        if not net_connect:
            print(f"❌ SSH连接失败")
            return False
            
        try:
            # 进入系统视图
            output = net_connect.send_command("system-view", expect_string=r'[>#\]\[]')
            print(f"📋 进入系统视图: {output.strip()}")
            
            # 启用NETCONF服务
            commands = [
                "netconf ssh server enable",  # 启用NETCONF SSH服务
                "ssh server enable",          # 确保SSH服务启用
                "ssh server port 830",        # 设置NETCONF端口
            ]
            
            for cmd in commands:
                try:
                    output = net_connect.send_command(cmd, expect_string=r'[>#\]\[]')
                    print(f"✅ 执行命令 '{cmd}': {output.strip()}")
                except Exception as e:
                    print(f"⚠️  命令 '{cmd}' 可能已配置或不支持: {e}")
            
            # 保存配置
            try:
                output = net_connect.send_command("save force", expect_string=r'[>#\]\[]')
                print(f"💾 保存配置: {output.strip()}")
            except Exception as e:
                print(f"⚠️  保存配置警告: {e}")
            
            net_connect.disconnect()
            print(f"✅ SSH配置完成，等待5秒让NETCONF服务启动...")
            time.sleep(5)  # 等待服务启动
            return True
            
        except Exception as e:
            print(f"❌ SSH配置失败: {e}")
            net_connect.disconnect()
            return False
            
    except Exception as e:
        print(f"❌ SSH连接启用NETCONF失败: {e}")
        return False

def test_netconf_connection(host, username, password, port=830):
    """测试NETCONF连接"""
    try:
        with manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=60,  # 增加超时时间到60秒
            device_params={'name': 'h3c'},  # H3C设备特定参数
            hostkey_verify=False,
            look_for_keys=False,
            allow_agent=False,
            ssh_config=None  # 禁用SSH配置文件
        ) as m:
            print(f"✅ NETCONF连接成功: {host}:{port}")
            print(f"📡 会话ID: {m.session_id}")
            print(f"🔧 支持的操作:")
            
            # 测试基本操作
            if ':base:1.0' in str(m.server_capabilities):
                print("  - ✅ 基础NETCONF 1.0")
            if ':base:1.1' in str(m.server_capabilities):
                print("  - ✅ 基础NETCONF 1.1")
            if ':candidate' in str(m.server_capabilities):
                print("  - ✅ Candidate配置")
            if ':startup' in str(m.server_capabilities):
                print("  - ✅ Startup配置")
            if ':rollback-on-error' in str(m.server_capabilities):
                print("  - ✅ 回滚支持")
                
            return True
            
    except Exception as e:
        print(f"❌ NETCONF连接失败: {e}")
        
        # 如果连接失败，尝试通过SSH启用NETCONF
        if "timed out" in str(e).lower() or "connection" in str(e).lower():
            print(f"🔄 尝试通过SSH启用NETCONF服务...")
            if enable_netconf_via_ssh(host, username, password):
                # 重试NETCONF连接
                try:
                    with manager.connect(
                        host=host,
                        port=port,
                        username=username,
                        password=password,
                        timeout=60,  # 增加重连超时时间
                        device_params={'name': 'h3c'},
                        hostkey_verify=False,
                        look_for_keys=False,
                        allow_agent=False,
                        ssh_config=None
                    ) as m:
                        print(f"✅ NETCONF重连成功: {host}:{port}")
                        return True
                except Exception as retry_e:
                    print(f"❌ NETCONF重连仍然失败: {retry_e}")
                    return False
            else:
                print(f"❌ 无法通过SSH启用NETCONF")
                return False
        else:
            return False

def netconf_configure_interface(host, username, password, config_data, port=830):
    """通过NETCONF配置接口"""
    try:
        # 解析配置数据
        config_data = parse_config_json(config_data)
        
        with manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=60,  # 增加接口配置超时时间
            device_params={'name': 'h3c'},  # H3C设备特定参数
            hostkey_verify=False,
            look_for_keys=False,
            allow_agent=False,
            ssh_config=None
        ) as m:
            print(f"🔗 NETCONF连接成功: {host}")
            
            # 判断是否是探索模式
            if 'explore_device' in config_data:
                explore_config = json.loads(config_data)
                if explore_config.get('explore_device', False):
                    print("🔍 启动设备探索模式...")
                    return explore_device_config(host, username, password, port)
            
            # 解析接口配置
            if config_data.strip().startswith('{') and 'ifindex' in config_data:
                # JSON配置格式 - 使用接口索引
                interface_config = json.loads(config_data)
                ifindex = interface_config.get('ifindex')
                description = interface_config.get('description')
                admin_status = interface_config.get('admin_status')  # 新增接口状态参数
                
                if not ifindex:
                    raise Exception("必须提供接口索引(ifindex)参数")
                
                print(f"📋 接口配置参数:")
                print(f"  - 接口索引(IfIndex): {ifindex}")
                print(f"  - 描述: {description or '未设置'}")
                print(f"  - 接口状态: {admin_status or '未设置'}")
                
                # 验证admin_status参数
                if admin_status and admin_status not in ["shutdown", "undo shutdown"]:
                    raise Exception(f"无效的接口状态参数: {admin_status}，只支持 'shutdown' 或 'undo shutdown'")
                
                # 直接使用IfIndex格式（H3C设备最可靠的方式）
                print("🔧 使用IfIndex格式配置接口...")
                print("📤 正在发送配置到设备，请耐心等待...")
                
                config_xml = build_h3c_interface_config_xml_ifindex_only(ifindex, description, admin_status)
                
                reply = m.edit_config(
                    target='running', 
                    config=config_xml
                )
                
                if reply.ok:
                    status_msg = f"接口索引{ifindex}配置成功"
                    if admin_status:
                        status_action = "关闭" if admin_status == "shutdown" else "开启"
                        status_msg += f" (接口已{status_action})"
                    print(f"✅ {status_msg}!")
                    print(f"📋 配置响应: {reply}")
                    # 返回成功状态和XML配置内容
                    return True, {
                        "status": "配置成功",
                        "ifindex": ifindex,
                        "description": description,
                        "admin_status": admin_status,
                        "xml_config": config_xml,
                        "response": str(reply)
                    }
                else:
                    print(f"❌ 接口索引{ifindex}主配置失败: {reply}")
                    
                    # 如果主配置失败且有admin_status，尝试分离配置
                    if admin_status:
                        print("🔄 尝试分离的接口状态配置...")
                        try:
                            if admin_status == "shutdown":
                                status_config_xml = build_h3c_interface_shutdown_xml(ifindex)
                            else:  # undo shutdown
                                status_config_xml = build_h3c_interface_no_shutdown_xml(ifindex)
                            
                            status_reply = m.edit_config(target='running', config=status_config_xml)
                            
                            if status_reply.ok:
                                status_action = "关闭" if admin_status == "shutdown" else "开启"
                                print(f"✅ 接口{ifindex}状态配置成功 (接口已{status_action})!")
                                
                                # 如果有描述，尝试单独配置描述
                                if description:
                                    print("🔄 尝试单独配置描述...")
                                    desc_config_xml = build_h3c_interface_config_xml_ifindex_only(ifindex, description, None)
                                    desc_reply = m.edit_config(target='running', config=desc_config_xml)
                                    if desc_reply.ok:
                                        print(f"✅ 接口{ifindex}描述配置成功!")
                                    else:
                                        print(f"⚠️  接口{ifindex}描述配置失败: {desc_reply}")
                                
                                return True, {
                                    "status": "分离配置成功",
                                    "ifindex": ifindex,
                                    "description": description,
                                    "admin_status": admin_status,
                                    "xml_config": status_config_xml,
                                    "response": str(status_reply)
                                }
                            else:
                                print(f"❌ 接口{ifindex}状态配置也失败: {status_reply}")
                                return False, f"主配置和状态配置都失败: 主配置({reply}), 状态配置({status_reply})"
                        except Exception as status_e:
                            print(f"❌ 分离状态配置异常: {status_e}")
                            return False, f"主配置失败({reply}), 状态配置异常({status_e})"
                    else:
                        return False, f"配置失败: {reply}"
                    
    except Exception as e:
        error_msg = f"连接或配置错误: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg
        error_msg = f"连接或配置错误: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg

def netconf_configure_vlan(host, username, password, vlan_config, port=830):
    """通过NETCONF配置VLAN"""
    try:
        with manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=60,  # 增加VLAN配置超时时间
            device_params={'name': 'h3c'},
            hostkey_verify=False,
            look_for_keys=False,
            allow_agent=False,
            ssh_config=None
        ) as m:
            print(f"🔗 NETCONF连接成功: {host}")
            
            # 解析VLAN配置
            vlan_data = json.loads(vlan_config)
            vlan_id = vlan_data.get('vlan_id')
            vlan_name = vlan_data.get('vlan_name')
            
            print(f"📋 VLAN配置参数:")
            print(f"  - VLAN ID: {vlan_id}")
            print(f"  - VLAN名称: {vlan_name or '未设置'}")
            
            # 构建配置XML - 使用正确的H3C格式
            config_xml = build_h3c_vlan_config_xml_correct(vlan_id)
            
            print("📤 发送VLAN配置到设备...")
            print(f"📝 配置XML:\n{config_xml}")
            
            # 发送配置
            reply = m.edit_config(target='running', config=config_xml)
            
            if reply.ok:
                print("✅ VLAN配置成功!")
                return True, "VLAN配置成功"
            else:
                error_msg = f"VLAN配置失败: {reply}"
                print(f"❌ {error_msg}")
                return False, error_msg
                
    except Exception as e:
        error_msg = f"VLAN配置错误: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg

def main():
    """主函数"""
    print("=" * 60)
    print("🌐 H3C设备NETCONF配置工具")
    print("=" * 60)
    
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python NETCONF_CONFIG_TEST.py <JSON配置参数>")
        print()
        print("JSON参数格式:")
        print('{')
        print('  "hostip": "192.168.56.10",')
        print('  "username": "admin",') 
        print('  "password": "h3c.com123",')
        print('  "operation": "interface|vlan|test|capabilities|explore",')
        print('  "ifindex": 25,                            # 接口配置时需要(接口索引)')
        print('  "description": "测试接口",                # 可选')
        print('  "admin_status": "shutdown|undo shutdown", # 可选(接口管理状态)')
        print('  "vlan_id": 100,                           # VLAN配置时需要')
        print('  "vlan_name": "测试VLAN"                   # 可选')
        print('}')
        print()
        print("示例:")
        print('# 测试连接')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"test"}\'')
        print()
        print('# 配置接口 (使用接口索引)')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"interface","ifindex":25,"description":"NETCONF测试接口"}\'')
        print()
        print('# 配置接口并关闭 (shutdown)')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"interface","ifindex":48,"description":"测试关闭接口","admin_status":"shutdown"}\'')
        print()
        print('# 配置接口并开启 (undo shutdown)') 
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"interface","ifindex":48,"description":"测试开启接口","admin_status":"undo shutdown"}\'')
        print()
        print('# 配置接口说明:')
        print('# ifindex=1: 通常是第一个GE接口')
        print('# ifindex=25: 通常是第一个10GE接口') 
        print('# ifindex=49: 通常是第一个40GE接口')
        print('# 具体索引值请查看设备接口配置')
        print('# admin_status="shutdown": 管理关闭接口 (AdminStatus=2)')
        print('# admin_status="undo shutdown": 管理开启接口 (AdminStatus=1)')
        print('# 配置VLAN')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"vlan","vlan_id":100,"vlan_name":"测试VLAN"}\'')
        print()
        print('# 查看设备功能')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"capabilities"}\'')
        print()
        print('# 探索设备配置')
        print('python NETCONF_CONFIG_TEST.py \'{"hostip":"192.168.56.10","username":"admin","password":"h3c.com123","operation":"explore"}\'')
        return
    
    # 解析JSON参数 - 支持多个参数合并
    try:
        # 将所有参数合并为一个字符串（处理PowerShell参数分割问题）
        json_str = ' '.join(sys.argv[1:])
        print(f"📝 合并的参数: {json_str}")
        
        # 检查是否是文件路径
        if json_str.endswith('.json') and os.path.exists(json_str):
            print(f"📁 从文件读取参数: {json_str}")
            with open(json_str, 'r', encoding='utf-8') as f:
                params = json.load(f)
        else:
            # 直接解析JSON字符串
            if json_str.startswith("'") and json_str.endswith("'"):
                json_str = json_str[1:-1]
            params = json.loads(json_str)
        
        # 提取参数
        hostip = params.get('hostip')
        username = params.get('username')
        password = params.get('password')
        operation = params.get('operation', 'test').lower()
        
        # 验证必需参数
        if not all([hostip, username, password]):
            print("❌ 缺少必需参数: hostip, username, password")
            return
            
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
        return
    except Exception as e:
        print(f"❌ 参数解析失败: {e}")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print(f"\n🎯 正在处理设备: {hostip}")
    print("-" * 50)
    
    try:
        if operation == 'test':
            # 测试连接
            print("🚀 开始NETCONF连接测试...")
            write_log("Running", None, None, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
            
            success = test_netconf_connection(hostip, username, password)
            status = "Completed" if success else "Failed"
            write_log(status, f"NETCONF连接测试", hostip, f"NETCONF_CONFIG_TEST_{timestamp}.log")
            
        elif operation == 'capabilities':
            # 查看设备功能
            print("🚀 开始查询设备功能...")
            write_log("Running", None, None, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
            
            capabilities = get_device_capabilities(hostip, username, password)
            if capabilities:
                write_log("Completed", f"设备功能查询", hostip, f"NETCONF_CONFIG_TEST_{timestamp}.log")
            else:
                write_log("Failed", f"设备功能查询", hostip, f"NETCONF_CONFIG_TEST_{timestamp}.log")
                
        elif operation == 'explore':
            # 探索设备配置
            print("🚀 开始探索设备配置...")
            write_log("Running", None, None, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
            
            config_xml = explore_device_config(hostip, username, password)
            if config_xml:
                write_log("Completed", f"设备配置探索", hostip, f"NETCONF_CONFIG_TEST_{timestamp}.log")
            else:
                write_log("Failed", f"设备配置探索", hostip, f"NETCONF_CONFIG_TEST_{timestamp}.log")
                
        elif operation == 'interface':
            # 配置接口 - 使用接口索引
            interface_config = {
                'ifindex': params.get('ifindex'),
                'description': params.get('description'),
                'admin_status': params.get('admin_status')  # 修复：添加缺失的admin_status参数
            }
            
            if not interface_config['ifindex']:
                print("❌ 接口配置缺少ifindex参数(接口索引)")
                return
                
            # 先获取设备系统信息
            print("🔍 获取设备系统信息...")
            try:
                ssh = login_args.login(hostip, username, password)
                if ssh:
                    from get_system_info import get_system_info
                    
                    # 1. 优先从SSH提示符获取真实的设备名（hostname）
                    device_name = "Unknown_Device"
                    try:
                        prompt = ssh.find_prompt()
                        print(f"🔍 SSH提示符: {prompt}")
                        
                        # 从提示符中提取设备名 <设备名> 或 [设备名]
                        import re
                        if '<' in prompt and '>' in prompt:
                            match = re.search(r'<([^>]+)>', prompt)
                            if match:
                                device_name = match.group(1)
                                print(f"✅ 从提示符提取设备名: {device_name}")
                        elif '[' in prompt and ']' in prompt:
                            match = re.search(r'\[([^\]]+)\]', prompt)
                            if match:
                                device_name = match.group(1)
                                print(f"✅ 从提示符提取设备名: {device_name}")
                    except Exception as e:
                        print(f"⚠️  提示符解析失败: {e}")
                    
                    # 2. 如果提示符没有设备名，尝试执行sysname命令获取
                    if device_name == "Unknown_Device":
                        try:
                            print("🔍 尝试获取sysname...")
                            sysname_output = ssh.send_command("display current-configuration | include sysname", delay_factor=2)
                            if sysname_output and 'sysname' in sysname_output:
                                # 解析 sysname 配置行
                                for line in sysname_output.split('\n'):
                                    line = line.strip()
                                    if line.startswith('sysname '):
                                        device_name = line.replace('sysname ', '').strip()
                                        print(f"✅ 从sysname配置提取设备名: {device_name}")
                                        break
                        except Exception as e:
                            print(f"⚠️  sysname获取失败: {e}")
                    
                    # 3. 获取系统版本信息
                    raw_system_info = get_system_info(ssh)
                    
                    # 4. 如果仍然没有设备名，从系统信息中提取设备型号作为fallback
                    if device_name == "Unknown_Device" and isinstance(raw_system_info, str):
                        lines = raw_system_info.split('\n')
                        for line in lines:
                            line = line.strip()
                            # 使用正则表达式查找H3C后面的设备型号
                            pattern = r'H3C\s+([SM]\d+\w*(?:-\w+)*)'
                            match = re.search(pattern, line)
                            if match:
                                device_name = match.group(1)
                                print(f"⚠️  fallback到设备型号: {device_name}")
                                break
                    
                    # 清理系统信息，移除命令行和多余的空行
                    if isinstance(raw_system_info, str):
                        lines = raw_system_info.split('\n')
                        filtered_lines = []
                        for line in lines:
                            line = line.strip()
                            # 跳过空行和命令行
                            if not line or line.startswith('>') or line.startswith('<'):
                                continue
                            filtered_lines.append(line)
                        system_info = {device_name: '\n'.join(filtered_lines)}
                    else:
                        system_info = {device_name: raw_system_info}
                    
                    ssh.disconnect()
                    print(f"✅ 系统信息获取成功，设备: {device_name}")
                else:
                    print("⚠️  SSH连接失败，使用IP地址作为系统信息")
                    system_info = {hostip: f"SSH连接失败，设备IP: {hostip}"}
            except Exception as e:
                print(f"⚠️  获取系统信息失败: {e}")
                system_info = {hostip: f"系统信息获取失败，设备IP: {hostip}"}
                
            config_json = json.dumps(interface_config)
            
            # 开始执行NETCONF配置前，先记录Running状态
            print("🚀 开始执行NETCONF接口配置...")
            write_log("Running", None, None, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
            
            success, result = netconf_configure_interface(hostip, username, password, config_json)
            
            if success:
                # 成功情况：记录XML配置内容到commands字段（只记录核心配置和响应）
                write_log(
                    "Completed", 
                    {
                        "xml_config": result['xml_config'],
                        "netconf_response": result['response']
                    },
                    system_info,  # 使用实际的系统信息
                    error_message=None,
                    file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}"
                )
            else:
                # 失败情况：记录错误信息到error_message字段
                write_log(
                    "Failed", 
                    f"接口配置失败",
                    system_info,  # 使用实际的系统信息
                    error_message={
                        "error_message": result
                    },
                    file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}"
                )
            
        elif operation == 'vlan':
            # 配置VLAN
            vlan_config = {
                'vlan_id': params.get('vlan_id'),
                'vlan_name': params.get('vlan_name')
            }
            
            if not vlan_config['vlan_id']:
                print("❌ VLAN配置缺少vlan_id参数")
                return
                
            # 开始执行VLAN配置前，先记录Running状态
            print("🚀 开始执行NETCONF VLAN配置...")
            write_log("Running", None, None, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
                
            config_json = json.dumps(vlan_config)
            success, message = netconf_configure_vlan(hostip, username, password, config_json)
            write_log("Completed" if success else "Failed", f"VLAN配置", hostip, message, file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
            
        else:
            print(f"❌ 未知操作类型: {operation}")
            return
            
    except Exception as e:
        print(f"❌ 设备 {hostip} 处理失败: {e}")
        write_log("Failed", f"{operation}操作", hostip, str(e), file_suffix=f"NETCONF_CONFIG_TEST_{timestamp}")
        return
    
    print(f"\n✅ 设备处理完成! 日志文件: NETCONF_CONFIG_TEST_{timestamp}.log")

if __name__ == "__main__":
    main()