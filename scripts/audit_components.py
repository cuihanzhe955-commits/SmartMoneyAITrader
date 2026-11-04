"""Audit exactly pinned dependencies against public registry advisories.

Development command only. No credentials, trading account access, or installs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def pins(path):
    result={}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line=line.strip()
        if not line or line.startswith("#"):continue
        match=re.fullmatch(r"([A-Za-z0-9_-]+)==([A-Za-z0-9.+_-]+)",line)
        if not match:raise ValueError("所有生产依赖必须精确锁定版本")
        name,version=match.groups();name=name.lower().replace("_","-")
        if name in result:raise ValueError("依赖清单重复")
        result[name]=version
    return result


def pypi(item):
    name,version=item
    url="https://pypi.org/pypi/"+name+"/"+version+"/json"
    with urlopen(url,timeout=15) as r:data=json.load(r)
    if data["info"]["version"]!=version or not isinstance(data.get("vulnerabilities"),list):
        raise ValueError("注册表版本或漏洞回报无法核验："+name)
    dist=distribution(name)
    if dist.version!=version:raise ValueError("本地安装版本不同于锁定版本："+name)
    license_files=[]
    for file in dist.files or []:
        leaf=Path(str(file)).name.lower()
        if leaf.startswith(("license","licence","copying","notice")):
            p=dist.locate_file(file)
            if p.is_file():license_files.append(dict(file=str(file).replace("\\","/"),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    return dict(name=name,version=version,license=dist.metadata.get("License-Expression") or dist.metadata.get("License") or data["info"].get("license") or "See license files",
        source=url,license_files=license_files,
        vulnerabilities=[dict(id=v["id"],aliases=v.get("aliases",[]),fixed_in=v.get("fixed_in",[]),link=v.get("link")) for v in data["vulnerabilities"] if not v.get("withdrawn")])


def audit(npm_audit,include_research=False):
    requirements=ROOT/"requirements.txt";lock=ROOT/"frontend/package-lock.json"
    expected=pins(requirements)
    with ThreadPoolExecutor(max_workers=6) as pool:python=list(pool.map(pypi,sorted(expected.items())))
    research=[]
    if include_research:
        with ThreadPoolExecutor(max_workers=2) as pool:research=list(pool.map(pypi,sorted(pins(ROOT/"requirements-research.txt").items())))
    package_lock=json.loads(lock.read_text(encoding="utf-8"));npm=[]
    for path,p in package_lock["packages"].items():
        if not path:continue
        integrity=p.get("integrity","")
        integrity_source=path
        if p.get("inBundle") is True:
            integrity_source=path.rsplit("/node_modules/",1)[0]
            integrity=package_lock["packages"].get(integrity_source,{}).get("integrity","")
        if not p.get("version") or not integrity.startswith(("sha512-","sha256-")) or not p.get("license"):
            raise ValueError("npm 锁定版本、完整性或许可缺失："+path)
        npm.append(dict(path=path,version=p["version"],license=p["license"],integrity=integrity,integrity_source=integrity_source,installed=(ROOT/"frontend"/path/"package.json").is_file()))
    npm_report=json.loads(Path(npm_audit).read_text(encoding="utf-8-sig"))
    if "error" in npm_report or "vulnerabilities" not in npm_report or "metadata" not in npm_report:raise ValueError("npm audit 未成功完成")
    return dict(checked_at=datetime.now(timezone.utc).isoformat(),
        scope="Windows CPython 3.12 x64 production dependency closure and complete npm lockfile; known-advisory lookup, not proof of absence",
        requirements_sha256=hashlib.sha256(requirements.read_bytes()).hexdigest(),npm_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        python=python,npm=npm,research=research,research_active_advisories=sum(len(p["vulnerabilities"]) for p in research),
        research_requirements_sha256=hashlib.sha256((ROOT/"requirements-research.txt").read_bytes()).hexdigest() if include_research else None,
        python_active_advisories=sum(len(p["vulnerabilities"]) for p in python),
        npm_advisories=npm_report["metadata"]["vulnerabilities"],
        npm_audit_sha256=hashlib.sha256(Path(npm_audit).read_bytes()).hexdigest())


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--npm-audit",required=True);p.add_argument("--output",required=True);p.add_argument("--research-path");args=p.parse_args()
    if args.research_path:sys.path.insert(0,args.research_path)
    result=audit(args.npm_audit,bool(args.research_path))
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(python_packages=len(result["python"]),npm_packages=len(result["npm"]),python_active_advisories=result["python_active_advisories"],npm_advisories=result["npm_advisories"]),ensure_ascii=False))
    raise SystemExit(1 if result["python_active_advisories"] or result["research_active_advisories"] or result["npm_advisories"]["total"] else 0)
