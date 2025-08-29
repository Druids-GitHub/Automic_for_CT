# NETCONF工具拆分说明

为了更好地管理和使用NETCONF功能，我们将原来的 `NETCONF_CONFIG_TEST.py` 拆分为两个专门的工具：

## 1. NETCONF_Capability.py - Capabilities查询工具

**功能：**
- 专门用于获取设备支持的NETCONF capabilities
- 分析capabilities并提供操作建议
- 识别接口配置相关的YANG模型
- 提供具体的XML配置格式建议
- 自动保存结果到文件和日志

**用法：**
```bash
python NETCONF_Capability.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123"}'
```

**或者使用JSON文件：**
```bash
# 创建参数文件 params.json
{
  "hostip": "10.12.174.228",
  "username": "admin",
  "password": "H3c.com@123"
}

# 使用文件参数
python NETCONF_Capability.py params.json
```

**输出文件：**
- `capabilities_<IP>_<时间戳>.txt` - 原始capabilities列表
- `capabilities_analysis_<IP>_<时间戳>.md` - 分析报告
- `NETCONF_Capability_<时间戳>.log` - 执行日志

## 2. NETCONF_CONFIG_TEST.py - 配置执行工具

**功能：**
- 专门用于执行具体的NETCONF配置操作
- 支持接口配置、VLAN配置等
- 支持设备探索和NETCONF监控信息查询
- **注意：不再包含capabilities查询功能**

**主要操作：**
- `test` - 测试NETCONF连接
- `interface` - 接口配置（使用ifindex）
- `vlan` - VLAN配置
- `explore` - 探索设备配置结构
- `netconf-info` - 获取NETCONF监控信息

**接口配置示例：**
```bash
# 配置接口描述
python NETCONF_CONFIG_TEST.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123","operation":"interface","ifindex":25,"description":"测试接口"}'

# 配置接口并关闭
python NETCONF_CONFIG_TEST.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123","operation":"interface","ifindex":25,"description":"关闭接口","admin_status":"shutdown"}'

# 配置接口并开启
python NETCONF_CONFIG_TEST.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123","operation":"interface","ifindex":25,"description":"开启接口","admin_status":"undo shutdown"}'
```

## 使用建议的工作流程

### 第一步：查询设备capabilities
```bash
python NETCONF_Capability.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123"}'
```

查看生成的分析报告，了解：
- 设备支持的NETCONF功能
- 可用的YANG模型
- 配置建议和最佳实践

### 第二步：根据capabilities执行配置
基于第一步的分析结果，使用合适的配置方式：

```bash
# 测试连接
python NETCONF_CONFIG_TEST.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123","operation":"test"}'

# 执行具体配置
python NETCONF_CONFIG_TEST.py '{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123","operation":"interface","ifindex":25,"description":"配置测试"}'
```

## PowerShell参数格式处理

由于PowerShell会处理JSON参数中的双引号，两个工具都支持自动修复：

**原始格式（PowerShell处理后）：**
```
{hostip:10.12.174.228,username:admin,password:H3c.com@123}
```

**会自动修复为：**
```json
{"hostip":"10.12.174.228","username":"admin","password":"H3c.com@123"}
```

## 文件对比

| 功能 | NETCONF_Capability.py | NETCONF_CONFIG_TEST.py |
|------|----------------------|------------------------|
| Capabilities查询 | ✅ 专门功能 | ❌ 已移除 |
| 配置执行 | ❌ 不包含 | ✅ 专门功能 |
| 分析报告 | ✅ 详细分析 | ❌ 不包含 |
| 接口配置 | ❌ 不包含 | ✅ 完整支持 |
| VLAN配置 | ❌ 不包含 | ✅ 完整支持 |
| 设备探索 | ❌ 不包含 | ✅ 完整支持 |
| 文件生成 | ✅ 多种格式 | ✅ 日志记录 |

## 优势

1. **职责分离**：每个工具专注于特定功能
2. **使用简化**：capabilities查询不需要复杂参数
3. **输出优化**：capabilities工具生成专门的分析报告
4. **维护性好**：功能模块化，便于维护和扩展

---

*创建日期：2025年8月28日*
*适用于：H3C设备NETCONF操作*
