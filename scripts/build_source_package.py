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
ROOT_FILES = {".gitignore", ".env.example", "README.md", "使用说明.md", "requirements.txt",
              "install.bat", "start.bat", "start.cmd", "stop.bat", "launch.py", "server.py", "terminal_host.py"}
DOCS = {"PHASE_C1_RESULTS.md", "CHALLENGE_TEMPLATE_UPDATE.md", "LIVE_TRADING_VERIFICATION.md", "GITHUB_UPLOAD.md"}
VERSION = "1.0-C1-template-ui"
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
        return p.suffix in {".py", ".html", ".css", ".js"}
    if parts[0]=="docs": return len(parts)==2 and parts[1] in DOCS
    if parts[0]=="frontend":
        return (parts[1]=="src" and p.suffix in {".tsx",".ts",".css"}) or (
            len(parts)==2 and parts[1] in {"package.json","package-lock.json","tsconfig.json","vite.config.ts","index.html"}
        ) or (parts[1]=="dist" and p.suffix in {".js",".css",".html"})
    if parts[0]=="data":
        return len(parts)==2 and (parts[1] in {"okx-spot-rules.json","SHA256SUMS.txt"} or
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
    manifest={"version":VERSION,"stable":False,"real_funds_verified":False,
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
