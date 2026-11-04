"""Export a scanned source snapshot. Never include the private working runtime."""
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = {"ai", "challenge", "events", "execution", "market", "risk", "strategy", "terminal", "web", "tests", "scripts"}
ROOT_FILES = {".gitignore", ".env.example", "README.md", "使用说明.md", "requirements.txt", "requirements-research.txt", "requirements-win-py312.lock", "THIRD_PARTY_NOTICES.md",
              "install.bat", "start.bat", "start.cmd", "stop.bat", "launch.py", "server.py", "terminal_host.py"}
DOCS = {"PHASE_C1_RESULTS.md", "CHALLENGE_TEMPLATE_UPDATE.md", "LIVE_TRADING_VERIFICATION.md", "GITHUB_UPLOAD.md", "WINDOWS_QUICK_START.md", "README.md", "V1_ROADMAP.md", "PRODUCT_DECISION_POOL.md", "SmartMoney_Stable_Plan.md"}
DOCS.update({"OPEN_SOURCE_AUDIT.md", "PHASE_D_COMPONENTS.md", "PHASE_D2_CCXT.md", "PHASE_D3_DISCOVERY.md", "PHASE_D4_MONITOR_POOL.md", "PROGRESS_STATUS.md", "PHASE_C2_FOUNDATION.md", "PHASE_C2_TRANSPORT.md", "PHASE_C2_SETTLEMENT.md",
             "PHASE_C2_MAINTENANCE.md", "PHASE_C2_RUNTIME.md", "PHASE_C2_LIFECYCLE.md", "PHASE_C2_RECOVERY.md", "PHASE_C2_DIAGNOSTICS.md", "PHASE_C3_READINESS.md"})
DOCS.update({"DEPENDENCY_AUDIT.json", "COMPONENT_DECISIONS.md", "PHASE_D_RESULTS.md", "COMPONENT_TEST_RESULTS.json"})
VERSION = "1.0-D-components-accepted"
BANNED = {"runtime", ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "screenshots"}
PATTERNS = {
    "provider_token": re.compile(r"(?:sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{20,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal_chat": re.compile(r"\b(?:ou_|oc_)[A-Za-z0-9]{20,}\b"),
    "user_profile_path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|YOUR_USER\b)[^\\/\s\"']+", re.I),
}


def allowed(name):
    p = Path(name); parts=p.parts
    if any(v in BANNED for v in parts) or p.suffix.lower() in {".db",".dpapi",".log",".pem",".key"}:
        return False
    if len(parts)==1: return name in ROOT_FILES
    if parts[0] in FOLDERS:
        return p.suffix in {".py", ".html", ".css", ".js", ".mjs"}
    if parts[0]=="third_party": return len(parts)==2 and parts[1] in {"lightweight-charts-LICENSE.txt","lightweight-charts-NOTICE.txt","ccxt-LICENSE.txt"}
    if parts[0]=="docs": return len(parts)==2 and parts[1] in DOCS
    if parts[0]=="assets": return p.suffix.lower() == ".svg"
    if parts[0]=="frontend":
        return (parts[1]=="src" and p.suffix in {".tsx",".ts",".css"}) or (
            len(parts)==2 and parts[1] in {"package.json","package-lock.json","tsconfig.json","vite.config.ts","index.html"}
        ) or (parts[1]=="dist" and p.suffix in {".js",".css",".html"})
    if parts[0]=="data":
        return len(parts)==2 and (parts[1] in {"okx-spot-rules.json","SHA256SUMS.txt","indicator-reference.json"} or
            bool(re.fullmatch(r"(BTC|ETH|SOL|DOGE|XRP|AVAX|LINK|ADA)USDT-1m-2024-08-0[45]\.zip",parts[1])))
    return False


def scan_content(name, data):
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.namelist()) != 1 or not z.namelist()[0].endswith(".csv"):
                raise ValueError("历史数据归档结构不符：" + name)
            return scan_content(name+"/"+z.namelist()[0], z.read(z.namelist()[0]))
    try: content=data.decode("utf-8-sig")
    except UnicodeDecodeError: raise ValueError("未批准的二进制文件："+name) from None
    return [name+": "+label for label, pattern in PATTERNS.items() if pattern.search(content)]


def verify_component_audit(files):
    name="docs/DEPENDENCY_AUDIT.json"
    if name not in files:
        return False  # Compatibility with earlier source-edition snapshots.
    data=json.loads(files[name].decode("utf-8-sig"))
    for path,key in (("requirements.txt","requirements_sha256"),
                     ("requirements-research.txt","research_requirements_sha256"),
                     ("frontend/package-lock.json","npm_lock_sha256")):
        if path not in files or hashlib.sha256(files[path]).hexdigest()!=data.get(key):
            raise ValueError("组件审查与当前依赖清单不一致，禁止导出旧验收结论")
    for value in (data.get("python_active_advisories"),data.get("research_active_advisories"),
                  data.get("npm_advisories",{}).get("total")):
        if type(value) is not int or value!=0:
            raise ValueError("依赖漏洞审查存在未关闭项或结果无效")
    return True


def build(root, destination):
    root, destination=Path(root).resolve(),Path(destination).resolve()
    if destination == root or root in destination.parents:
        raise ValueError("发布目录必须在主工程之外")
    if destination.exists():
        raise ValueError("发布目录已存在，拒绝覆盖")
    files={}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in BANNED and not Path(directory,d).is_symlink())
        for filename in sorted(names):
            file=Path(directory,filename)
            name=file.relative_to(root).as_posix()
            if not allowed(name): continue
            if file.is_symlink() or root not in file.resolve().parents:
                raise ValueError("拒绝导出符号链接或工程外文件："+name)
            files[name]=file.read_bytes()
    required={"terminal/api.py","frontend/dist/index.html","frontend/package-lock.json","data/BTCUSDT-1m-2024-08-05.zip"}
    if not required <= files.keys(): raise ValueError("缺少源码、已构建前端或回测数据")
    findings=[hit for name,data in files.items() for hit in scan_content(name,data)]
    if findings: raise ValueError("敏感信息扫描未通过（仅显示文件与规则）：\n"+"\n".join(findings))
    components_reviewed=verify_component_audit(files)
    manifest={"version":VERSION,"stable":False,"real_funds_verified":False,
              "components_reviewed":components_reviewed,
              "built_at":datetime.now(timezone.utc).isoformat(),"files": {
                  name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
              "sensitive_scan":{"matches":0,"method":"allowlist + known token/private key/chat ID/profile path patterns; not a proof of absence"}}
    files["SOURCE_MANIFEST.json"]=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()
    destination.mkdir(parents=True)
    export=destination/"SmartMoneyAITrader"
    for name,data in files.items():
        target=export/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
    archive=destination/("SmartMoneyAITrader-"+VERSION+"-source.zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items(): z.writestr("SmartMoneyAITrader/"+name,data)
    # Reopen and scan the delivered bytes too.
    with zipfile.ZipFile(archive) as z:
        if z.testzip(): raise ValueError("发布归档校验失败")
        for info in z.infolist():
            if info.filename.endswith("SOURCE_MANIFEST.json"): continue
            name=info.filename.removeprefix("SmartMoneyAITrader/")
            if not allowed(name) or scan_content(name,z.read(info)):
                raise ValueError("发布归档二次扫描失败")
    result={"source_directory":str(export),"archive":str(archive),
            "sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
            "file_count":len(files),"sensitive_pattern_matches":0}
    (destination/"BUILD_RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


if __name__=="__main__":
    target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT.parent/"SmartMoneyAITrader_releases"/("template_ui_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    print(json.dumps(build(ROOT,target),ensure_ascii=False,indent=2))
