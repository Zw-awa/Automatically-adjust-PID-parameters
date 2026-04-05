#!/usr/bin/env python3
"""
GitHub上传准备检查脚本
检查项目是否可以安全上传到GitHub
"""

import os
import json
import re
from pathlib import Path

def check_gitignore():
    """检查.gitignore配置"""
    print("🔍 检查.gitignore配置...")
    
    gitignore_path = Path(".gitignore")
    if not gitignore_path.exists():
        print("  ❌ 错误: .gitignore文件不存在")
        return False
    
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = {
        "Python编译产物": [
            r"__pycache__/",
            r"\*\.py\[codz\]",
            r"\*\.pyc",
            r"\*\.pyo",
            r"\*\.pyd"
        ],
        "构建产物": [
            r"dist/",
            r"build/",
            r"\*\.egg-info/",
            r"\*\.egg"
        ],
        "环境文件": [
            r"\.env",
            r"\.venv",
            r"venv/",
            r"env/"
        ],
        "IDE配置": [
            r"\.vscode/",
            r"\.idea/",
            r"\.claude/"
        ],
        "平台文件": [
            r"\.DS_Store",
            r"Thumbs\.db",
            r"Desktop\.ini"
        ]
    }
    
    all_passed = True
    for category, patterns in checks.items():
        passed = any(re.search(pattern, content) for pattern in patterns)
        status = "✅" if passed else "❌"
        print(f"  {status} {category}: {'通过' if passed else '未配置或配置不完整'}")
        if not passed:
            all_passed = False
    
    # 检查是否有错误的config.json忽略规则
    if "config.json" in content:
        print("  ⚠️  警告: .gitignore中包含了config.json，这可能会忽略项目配置文件")
        # 检查是否是注释掉的
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if "config.json" in line and not line.strip().startswith("#"):
                print(f"    ❌ 第{i}行: {line.strip()}")
                all_passed = False
    
    return all_passed

def check_sensitive_files():
    """检查敏感文件"""
    print("\n🔍 检查敏感文件...")
    
    sensitive_patterns = [
        r"\.env",
        r"\.key",
        r"\.pem",
        r"secret",
        r"password",
        r"token",
        r"api[_-]?key",
        r"private"
    ]
    
    found_sensitive = []
    for root, dirs, files in os.walk("."):
        # 跳过.git目录
        if ".git" in root:
            continue
            
        for file in files:
            file_lower = file.lower()
            if any(re.search(pattern, file_lower) for pattern in sensitive_patterns):
                rel_path = os.path.join(root, file)
                found_sensitive.append(rel_path)
    
    if found_sensitive:
        print("  ⚠️  发现可能敏感的文件:")
        for file in found_sensitive:
            print(f"    • {file}")
        return False
    else:
        print("  ✅ 未发现明显的敏感文件")
        return True

def check_config_json():
    """检查config.json中的API密钥"""
    print("\n🔍 检查config.json...")
    
    config_path = Path("config.json")
    if not config_path.exists():
        print("  ❌ 错误: config.json文件不存在")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查LLM API密钥
        llm_config = config.get("llm", {})
        api_key = llm_config.get("api_key", "")
        
        if not api_key:
            print("  ✅ API密钥为空（安全）")
            return True
        elif (api_key == "你的DeepSeek-API密钥" or 
              "your_" in api_key.lower() or 
              "example" in api_key.lower() or
              "placeholder" in api_key.lower() or
              api_key == "your-deepseek-api-key"):
            print(f"  ✅ API密钥是占位符: '{api_key}'（安全）")
            return True
        else:
            # 检查是否是明显的占位符格式
            placeholder_patterns = [
                r"^<.*>$",  # <your-api-key>
                r"^\[.*\]$",  # [API_KEY]
                r"^\{.*\}$",  # {API_KEY}
                r"^YOUR_.*_KEY$",  # YOUR_DEEPSEEK_API_KEY
                r"^placeholder.*$",  # placeholder-api-key
                r"^demo.*$",  # demo-api-key
                r"^test.*$",  # test-api-key
            ]
            
            import re
            if any(re.match(pattern, api_key, re.IGNORECASE) for pattern in placeholder_patterns):
                print(f"  ✅ API密钥是占位符格式: '{api_key}'（安全）")
                return True
            else:
                print("  ⚠️  警告: config.json中包含可能是真实的API密钥")
                print(f"    密钥值: '{api_key}'")
                print(f"    密钥长度: {len(api_key)} 字符")
                print("    建议: 使用占位符或环境变量")
                return False
            
    except json.JSONDecodeError as e:
        print(f"  ❌ 错误: config.json格式错误 - {e}")
        return False
    except Exception as e:
        print(f"  ❌ 错误: 检查config.json时出错 - {e}")
        return False

def check_empty_directories():
    """检查空目录是否有.gitkeep文件"""
    print("\n🔍 检查空目录...")
    
    empty_dirs_needing_gitkeep = [
        "data/logs",
        "data/processed", 
        "outputs/figures",
        "outputs/reports"
    ]
    
    all_have_gitkeep = True
    for dir_path in empty_dirs_needing_gitkeep:
        path = Path(dir_path)
        if path.exists():
            # 检查是否为空或只有.gitkeep
            items = list(path.iterdir())
            has_gitkeep = any(item.name == ".gitkeep" for item in items)
            is_empty = len(items) == 0
            
            if has_gitkeep:
                print(f"  ✅ {dir_path}/ 有.gitkeep文件")
            elif is_empty:
                print(f"  ⚠️  {dir_path}/ 是空目录，建议添加.gitkeep")
                all_have_gitkeep = False
            else:
                print(f"  ✅ {dir_path}/ 非空目录")
        else:
            print(f"  ⚠️  {dir_path}/ 目录不存在")
    
    return all_have_gitkeep

def check_core_files():
    """检查核心文件是否存在"""
    print("\n🔍 检查核心文件...")
    
    core_files = [
        "README.md",
        "config.json",
        "requirements.txt",
        "main.py",
        "core/__init__.py",
        "core/tuner.py",
        "core/serial_manager.py",
        "core/data_collector.py",
        "core/analyzer.py"
    ]
    
    missing_files = []
    for file_path in core_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        print("  ❌ 缺失核心文件:")
        for file in missing_files:
            print(f"    • {file}")
        return False
    else:
        print("  ✅ 所有核心文件都存在")
        return True

def main():
    print("=" * 60)
    print("GitHub上传准备检查")
    print("=" * 60)
    
    results = {
        ".gitignore配置": check_gitignore(),
        "敏感文件检查": check_sensitive_files(),
        "config.json安全": check_config_json(),
        "空目录管理": check_empty_directories(),
        "核心文件完整": check_core_files()
    }
    
    print("\n" + "=" * 60)
    print("检查结果汇总")
    print("=" * 60)
    
    all_passed = True
    for check_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{check_name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有检查通过！项目可以安全上传到GitHub。")
        print("\n建议操作:")
        print("1. 运行: git add .")
        print("2. 运行: git commit -m \"准备GitHub上传\"")
        print("3. 在GitHub创建新仓库")
        print("4. 按照GitHub提示推送代码")
    else:
        print("⚠️  部分检查未通过，请修复问题后再上传。")
        print("\n常见问题解决:")
        print("1. 如果config.json包含真实API密钥，请替换为占位符")
        print("2. 如果.gitignore配置不完整，请参考Python.gitignore模板")
        print("3. 空目录需要添加.gitkeep文件以保留目录结构")
    
    print("=" * 60)

if __name__ == "__main__":
    main()