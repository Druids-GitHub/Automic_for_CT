#!/usr/bin/env python3
"""测试NETCONF监控信息获取功能"""

import json
import os
from datetime import datetime

def test_netconf_info_operations():
    """测试各种NETCONF监控信息获取操作"""
    print("🌐 测试NETCONF监控信息获取功能")
    print("=" * 60)
    
    # 基础连接参数
    base_params = {
        "hostip": "192.168.56.10",
        "username": "admin",
        "password": "h3c.com123"
    }
    
    # 测试用例
    test_cases = [
        {
            "name": "获取全部NETCONF监控信息",
            "params": {"operation": "netconf-info"},
            "description": "不指定info_type，获取全部监控信息"
        },
        {
            "name": "获取NETCONF能力信息",
            "params": {"operation": "netconf-info", "info_type": "capabilities"},
            "description": "获取设备支持的NETCONF能力集"
        },
        {
            "name": "获取NETCONF会话信息",
            "params": {"operation": "netconf-info", "info_type": "sessions"},
            "description": "获取设备中的NETCONF会话信息"
        },
        {
            "name": "获取NETCONF数据存储信息", 
            "params": {"operation": "netconf-info", "info_type": "datastores"},
            "description": "获取设备中的数据库信息"
        },
        {
            "name": "获取NETCONF模式信息",
            "params": {"operation": "netconf-info", "info_type": "schemas"},
            "description": "获取设备中的YANG模式文件列表"
        },
        {
            "name": "获取NETCONF统计信息",
            "params": {"operation": "netconf-info", "info_type": "statistics"},
            "description": "获取NETCONF的统计信息"
        }
    ]
    
    # 创建测试参数文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}️⃣ 测试用例: {test_case['name']}")
        print(f"📝 描述: {test_case['description']}")
        
        # 合并参数
        params = {**base_params, **test_case['params']}
        
        # 创建参数文件
        param_file = f"netconf_test_{i}_{timestamp}.json"
        with open(param_file, 'w', encoding='utf-8') as f:
            json.dump(params, f, indent=2, ensure_ascii=False)
        
        print(f"📄 参数文件已创建: {param_file}")
        print(f"🔧 参数内容: {json.dumps(params, ensure_ascii=False)}")
        
        # 显示命令
        print(f"🚀 执行命令: python NETCONF_CONFIG_TEST.py {param_file}")
        
        print("-" * 50)
    
    print(f"\n✅ 测试参数文件创建完成!")
    print(f"💡 您可以依次执行上述命令来测试不同类型的NETCONF监控信息获取")
    print(f"📂 生成的XML文件将保存在当前目录")
    print(f"📋 日志文件将保存在 result/temp/ 目录")
    
    # 显示一个简单的批量测试脚本
    print(f"\n📜 批量测试脚本示例:")
    print("@echo off")
    for i in range(1, len(test_cases) + 1):
        print(f"echo 执行测试 {i}...")
        print(f"python NETCONF_CONFIG_TEST.py netconf_test_{i}_{timestamp}.json")
        print("echo.")
        print("pause")
        print()

if __name__ == "__main__":
    test_netconf_info_operations()
